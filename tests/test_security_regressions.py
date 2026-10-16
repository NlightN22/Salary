import json
from io import BytesIO
from pathlib import Path

import pandas as pd
import pytest
from fastapi import UploadFile
from fastapi.testclient import TestClient

from salary_web.app import app
from salary_web.auth import (
    _ensure_user_department, ensure_default_auth_data, make_session_token,
    validate_security_config, verify_password,
)
from salary_web.database import get_db
from salary_web.models import Calculation, Department, Employee, Period, UploadedReport, User
from salary_web.snapshot_editor import append_additional_payment, refresh_calculated_values
from tests.test_generators import manager_report




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


def test_department_period_pages_and_storage_are_isolated(db, tmp_path, monkeypatch):
    from salary_web.app import period_url
    from salary_web.config import resolve_service_data_path
    from salary_web.report_storage import save_uploaded_report
    from salary_web.models import UserDepartment
    import salary_web.report_storage as storage
    monkeypatch.setattr(storage, "UPLOADS_DIR", tmp_path)
    first = Period(year=2044, month=6, department=Department(code="east", name="East"))
    second = Period(year=2044, month=6, department=Department(code="west", name="West"))
    user = User(username="west-user", password_hash="unused", is_active=1, is_admin=0)
    db.add_all([first, second, user]); db.flush()
    db.add(UserDepartment(user_id=user.id, department_id=second.department_id)); db.commit()
    a = save_uploaded_report(db, first, "profit", UploadFile(filename="profit.xlsx", file=BytesIO(b"east")))
    b = save_uploaded_report(db, second, "profit", UploadFile(filename="profit.xlsx", file=BytesIO(b"west")))
    db.commit()
    assert resolve_service_data_path(a.stored_path) != resolve_service_data_path(b.stored_path)
    assert resolve_service_data_path(a.stored_path).read_bytes() == b"east"
    assert resolve_service_data_path(b.stored_path).read_bytes() == b"west"
    app.dependency_overrides[get_db] = lambda: db
    client = TestClient(app, follow_redirects=False)
    client.cookies.set("salary_user", make_session_token(user.id))
    try:
        assert client.get(period_url(first)).status_code == 403
        response = client.get(period_url(second))
        assert response.status_code == 200
        assert period_url(second) + "/reports" in response.text
        assert client.get("/periods/2044/06").status_code == 404
        assert client.get(f"/periods/{second.id}").status_code == 404
        for suffix in ["validate", "calculate", "pdf", "calculations/delete"]:
            assert client.post(period_url(first) + "/" + suffix).status_code == 403
        assert client.post(period_url(second) + "/validate").status_code == 303
        assert client.get(f"/departments/{second.department_id}/periods/2044/7").status_code == 404
        user.is_admin = 1; db.commit()
        assert client.get(period_url(first)).status_code == 200
        assert client.get(period_url(second)).status_code == 200
    finally:
        client.close()
        app.dependency_overrides.clear()


def test_report_filename_uses_full_name_month_and_year():
    from services.report_naming import report_stem
    assert report_stem("Иванов Иван Иванович", 2026, 10) == "Иванов_Иван_Иванович_октябрь_2026"
    assert report_stem("Иванов Петр Петрович", 2026, 10) != report_stem("Иванов Иван Иванович", 2026, 10)


def test_interrupted_upload_and_db_rollback_preserve_previous_file(db, tmp_path, monkeypatch):
    import salary_web.report_storage as storage
    from salary_web.config import resolve_service_data_path
    monkeypatch.setattr(storage, "UPLOADS_DIR", tmp_path)
    period = Period(year=2047, month=1, department=Department(code="safe", name="Safe"))
    db.add(period); db.commit()
    report = storage.save_uploaded_report(db, period, "profit",
        UploadFile(filename="profit.xlsx", file=BytesIO(b"original")))
    db.commit()
    original_path, report_id, period_id = report.stored_path, report.id, period.id

    class InterruptedFile:
        first = True

        def read(self, size):
            if self.first:
                self.first = False
                return b"partial"
            raise OSError("Connection lost")

    with pytest.raises(OSError, match="Connection lost"):
        storage.save_uploaded_report(db, period, "profit",
            UploadFile(filename="profit.xlsx", file=InterruptedFile()))
    db.rollback()
    assert db.get(UploadedReport, report_id).stored_path == original_path
    assert resolve_service_data_path(original_path).read_bytes() == b"original"
    assert not list(tmp_path.rglob("*.part"))
    storage.save_uploaded_report(db, db.get(Period, period_id), "profit",
        UploadFile(filename="profit.xlsx", file=BytesIO(b"complete-but-rolled-back")))
    db.rollback()
    assert db.get(UploadedReport, report_id).stored_path == original_path
    assert resolve_service_data_path(original_path).read_bytes() == b"original"


def test_sessions_expire_and_password_change_revokes_old_cookie(db, monkeypatch):
    import salary_web.auth as auth
    from tests.test_rounding_and_auth import request_with_cookie
    user = User(username="session-admin", password_hash=auth.hash_password("before"),
                is_active=1, is_admin=1)
    db.add(user); db.commit()
    monkeypatch.setattr(auth.time, "time", lambda: 1000)
    token = auth.make_session_token(user.id)
    request = request_with_cookie(token)
    assert auth.current_user(request, db).id == user.id
    monkeypatch.setattr(auth.time, "time", lambda: 1000 + auth.SESSION_LIFETIME)
    assert auth.current_user(request, db) is None
    monkeypatch.setattr(auth.time, "time", lambda: 1001)
    app.dependency_overrides[get_db] = lambda: db
    client = TestClient(app, follow_redirects=False)
    client.cookies.set(auth.SESSION_COOKIE, token)
    try:
        assert client.post(f"/admin/users/{user.id}/password", data={"password": "after"}).status_code == 303
        assert auth.current_user(request, db) is None
        assert client.get("/admin").status_code == 401
        client.cookies.clear()
        assert client.post("/login", data={"username": user.username, "password": "before"}).status_code == 401
        response = client.post("/login", data={"username": user.username, "password": "after"})
        assert response.status_code == 303
        assert f"Max-Age={auth.SESSION_LIFETIME}" in response.headers["set-cookie"]
        assert client.get("/admin").status_code == 200
    finally:
        client.close()
        app.dependency_overrides.clear()


@pytest.mark.parametrize("value", ["nan", "inf", "-inf", "1e100", "-1e100"])
def test_invalid_money_is_rejected_without_changing_calculation(db, value):
    from salary_web.models import AdditionalPayment, CalculationAdjustment
    user = User(username="money-admin", password_hash="unused", is_active=1, is_admin=1)
    report = manager_report()
    calculation = Calculation(period=Period(year=2048, month=1,
        department=Department(code="money", name="Money")),
        employee=Employee(full_name=report["employee"]), snapshot_json=json.dumps(report))
    db.add_all([user, calculation]); db.commit()
    original = calculation.snapshot_json
    app.dependency_overrides[get_db] = lambda: db
    client = TestClient(app, raise_server_exceptions=False)
    client.cookies.set("salary_user", make_session_token(user.id))
    base = f"/calculations/{calculation.id}"
    try:
        for path in ["additional-payments", "additional-payments/1/update", "adjustments", "adjustments/1/update"]:
            response = client.post(f"{base}/{path}", data={"title": "test", "amount": value,
                "section_code": "debt", "adjustment_type": "correction"})
            assert response.status_code == 422, response.text
        response = client.post(f"{base}/adjustments", data={"section_code": "key_clients_profit",
            "adjustment_type": "correction", "profit": value})
        assert response.status_code == 422
        assert db.get(Calculation, calculation.id).snapshot_json == original
        assert db.query(AdditionalPayment).count() == 0
        assert db.query(CalculationAdjustment).count() == 0
    finally:
        client.close()
        app.dependency_overrides.clear()


def test_session_version_migration_keeps_existing_user(tmp_path, monkeypatch):
    from sqlalchemy import create_engine, text
    import salary_web.database as database
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy-user.db'}")
    try:
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT, password_hash TEXT)"))
            connection.execute(text("INSERT INTO users VALUES (1, 'existing', 'unchanged-hash')"))
            connection.execute(text("CREATE TABLE departments (id INTEGER PRIMARY KEY, code TEXT, name TEXT, is_active INTEGER)"))
            connection.execute(text("CREATE TABLE periods (id INTEGER PRIMARY KEY, department_id INTEGER, status TEXT)"))
            connection.execute(text("CREATE TABLE calculations (id INTEGER PRIMARY KEY, status TEXT)"))
        monkeypatch.setattr(database, "engine", engine)
        monkeypatch.setattr(database, "DATABASE_URL", "sqlite:///legacy-user.db")
        database.migrate_db()
        database.migrate_db()
        with engine.connect() as connection:
            assert connection.execute(text("SELECT username, password_hash, session_version FROM users")).one() == (
                "existing", "unchanged-hash", 0)
    finally:
        engine.dispose()
