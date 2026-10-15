import json
from io import BytesIO
from pathlib import Path

import pandas as pd
import pytest
from fastapi import UploadFile
from fastapi.testclient import TestClient

from salary_web.app import app, require_legacy_api_access
from salary_web.auth import (
    _ensure_user_department, ensure_default_auth_data, make_session_token,
    validate_security_config, verify_password,
)
from salary_web.database import get_db
from salary_web.models import Calculation, Department, Employee, Period, UploadedReport, User
from salary_web.snapshot_editor import append_additional_payment, refresh_calculated_values
from tests.test_generators import manager_report


def test_all_legacy_api_routes_enforce_department_and_active_user(db):
    department = Department(code="b2b", name="B2B")
    user = User(username="restricted", password_hash="unused", is_admin=0, is_active=1)
    period = Period(year=2040, month=1, department=department)
    calculation = Calculation(period=period, employee=Employee(full_name="Audit Employee"),
                              snapshot_json=json.dumps(manager_report()))
    db.add_all([user, calculation]); db.commit()
    app.dependency_overrides[get_db] = lambda: db
    client = TestClient(app)
    client.cookies.set("salary_user", make_session_token(user.id))
    routes = [route for route in app.routes if getattr(route, "path", "").startswith(
        ("/api/periods", "/api/calculations"))]
    try:
        for route in routes:
            assert any(dep.call is require_legacy_api_access for dep in route.dependant.dependencies)
            url = route.path.format(period_id=period.id, year=2040, month=1,
                                    calculation_id=calculation.id, report_type="profit")
            response = client.request(next(iter(route.methods)), url,
                                      data={"year": 2040, "month": 1})
            assert response.status_code == 403, (url, response.text)
        user.is_active = 0; db.commit()
        assert client.get(f"/api/periods/{period.id}").status_code == 401
        user.is_active = 1
        _ensure_user_department(db, user, department); db.commit()
        assert client.get(f"/api/periods/{period.id}").status_code == 200
        assert client.post("/api/periods/2040/2").status_code == 200
        assert client.get("/api/periods/not-a-number").status_code == 422
        db.delete(user); db.commit()
        assert client.get(f"/api/periods/{period.id}").status_code == 401
    finally:
        client.close()
        app.dependency_overrides.clear()


def test_bootstrap_never_restores_renamed_or_deleted_admin(db, monkeypatch):
    monkeypatch.delenv("SALARY_ADMIN_PASSWORD", raising=False)
    with pytest.raises(RuntimeError, match="SALARY_ADMIN_PASSWORD"):
        ensure_default_auth_data(db)
    monkeypatch.setenv("SALARY_ADMIN_PASSWORD", "test-admin-password")
    ensure_default_auth_data(db)
    admin = db.query(User).one()
    assert verify_password("test-admin-password", admin.password_hash)
    _ensure_user_department(db, admin, db.query(Department).one())
    admin.username = "renamed"; db.commit()
    ensure_default_auth_data(db)
    assert db.query(User).count() == 1
    db.add(User(username="another-admin", password_hash="x", is_admin=1)); db.commit()
    db.delete(admin); db.commit()
    ensure_default_auth_data(db)
    assert db.query(User).filter_by(username="admin").first() is None


@pytest.mark.parametrize("secret", ["", "short", "change-me-before-production",
    "replace-this-with-a-long-random-string", "salary-web-local-session-change-me"])
def test_docker_rejects_missing_or_default_secret(monkeypatch, secret):
    monkeypatch.setenv("SALARY_REQUIRE_SECURE_CONFIG", "1")
    monkeypatch.setenv("SALARY_SESSION_SECRET", secret)
    with pytest.raises(RuntimeError, match="SALARY_SESSION_SECRET"):
        validate_security_config()


def test_docker_accepts_custom_secret(monkeypatch):
    monkeypatch.delenv("SALARY_REQUIRE_SECURE_CONFIG", raising=False)
    validate_security_config()
    monkeypatch.setenv("SALARY_REQUIRE_SECURE_CONFIG", "1")
    monkeypatch.setenv("SALARY_SESSION_SECRET", "a-valid-test-secret-for-docker-123456789")
    validate_security_config()


def test_timesheet_reupload_replaces_legacy_duplicates(db, tmp_path, monkeypatch):
    import salary_web.report_storage as storage
    monkeypatch.setattr(storage, "UPLOADS_DIR", tmp_path)
    period = Period(year=2041, month=1, department=Department(code="b2b", name="B2B"))
    db.add(period); db.commit()
    for _ in range(2):
        db.add(UploadedReport(period=period, report_type="timesheet", original_filename="Табель.xlsx",
                              stored_path="old.xlsx", file_hash="old", status="uploaded"))
    db.commit()
    result = storage.save_uploaded_report(db, period, "timesheet",
        UploadFile(filename="Табель.xlsx", file=BytesIO(b"new")))
    db.commit()
    assert db.query(UploadedReport).count() == 1
    from salary_web.config import resolve_service_data_path
    assert resolve_service_data_path(result.stored_path).read_bytes() == b"new"
    storage.save_uploaded_report(db, period, "timesheet",
        UploadFile(filename="Другой табель.xlsx", file=BytesIO(b"second")))
    assert db.query(UploadedReport).count() == 2


def test_duplicate_timesheet_employee_is_rejected(monkeypatch):
    from tests.test_context import valid_frames, REQUIRED
    import services.calculation_context as context
    frames = valid_frames()
    frames["timesheet-2.xlsx"] = pd.DataFrame([["Заголовок", "Часы"], ["Иванов И.И.", 160]])
    monkeypatch.setattr(context, "read_excel", lambda path: frames[Path(path).name])
    with pytest.raises(ValueError, match="Повтор сотрудника"):
        context.load_context_from_files(2040, 1, REQUIRED)


def test_manual_edit_invalidates_existing_pdf():
    calculation = Calculation(snapshot_json=json.dumps(manager_report()), pdf_path="old.pdf")
    append_additional_payment(calculation, "Correction", 500)
    assert calculation.pdf_path is None
    report = json.loads(calculation.snapshot_json)
    report["total_bonus"] = -999
    calculation.snapshot_json = json.dumps(report)
    calculation.pdf_path = "old.pdf"
    assert refresh_calculated_values(calculation)
    assert calculation.pdf_path is None
