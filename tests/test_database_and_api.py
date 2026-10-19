import json
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from salary_web.app import app
from salary_web.auth import hash_api_key
from salary_web.database import SessionLocal
from salary_web.models import ApiKey, ApiKeyDepartment, Department, Employee, Period
from tests.test_generators import manager_report


def test_same_month_is_allowed_for_different_departments(db):
    first = Department(code="one", name="One")
    second = Department(code="two", name="Two")
    db.add_all([first, second])
    db.flush()
    db.add_all([
        Period(department_id=first.id, year=2026, month=1),
        Period(department_id=second.id, year=2026, month=1),
    ])
    db.commit()
    assert db.query(Period).count() == 2


def test_duplicate_period_in_same_department_is_rejected(db):
    department = Department(code="one", name="One")
    db.add(department)
    db.flush()
    db.add(Period(department_id=department.id, year=2026, month=1))
    db.commit()
    db.add(Period(department_id=department.id, year=2026, month=1))
    with pytest.raises(IntegrityError):
        db.commit()


@pytest.fixture
def client_and_key():
    with TestClient(app) as client:
        db = SessionLocal()
        department = db.query(Department).filter_by(code="b2b").one()
        secret = f"sk_salary_test_{uuid.uuid4().hex}"
        key = ApiKey(name="tests", key_hash=hash_api_key(secret), key_secret=secret, is_active=1)
        db.add(key)
        db.flush()
        db.add(ApiKeyDepartment(api_key_id=key.id, department_id=department.id))
        db.commit()
        db.close()
        yield client, secret


def test_public_health_and_command_discovery(client_and_key):
    client, _ = client_and_key
    assert client.get("/api/health").json() == {"status": "ok"}
    response = client.get("/api/commands")
    assert response.status_code == 200
    assert any(command["path"].startswith("/api/") for command in response.json()["commands"])


def test_api_requires_key(client_and_key):
    client, _ = client_and_key
    response = client.post("/api/departments/b2b/periods/2031/1")
    assert response.status_code == 401
    assert response.json()["detail"] == "Требуется API-ключ"


def test_department_period_api_uses_clear_year_month_path(client_and_key):
    client, secret = client_and_key
    headers = {"X-API-Key": secret}
    created = client.post("/api/departments/b2b/periods/2032/1", headers=headers)
    assert created.status_code == 200
    payload = created.json()
    assert payload["department_code"] == "b2b"
    assert (payload["year"], payload["month"]) == (2032, 1)
    fetched = client.get("/api/departments/b2b/periods/2032/1", headers=headers)
    assert fetched.status_code == 200


def test_invalid_month_is_rejected(client_and_key):
    client, secret = client_and_key
    response = client.post(
        "/api/departments/b2b/periods/2033/13",
        headers={"X-API-Key": secret},
    )
    assert response.status_code == 400
    assert "от 1 до 12" in response.json()["detail"]


def test_calculation_id_must_belong_to_requested_period(db):
    from salary_web.app import get_period_calculation_or_404
    from salary_web.models import Calculation

    department = Department(code="scope", name="Scope")
    employee = Employee(full_name="Тестовый Сотрудник Один")
    first = Period(department=department, year=2026, month=1)
    second = Period(department=department, year=2026, month=2)
    calculation = Calculation(period=first, employee=employee, snapshot_json=json.dumps({}))
    db.add_all([first, second, calculation])
    db.commit()
    with pytest.raises(Exception) as error:
        get_period_calculation_or_404(db, second, calculation.id)
    assert getattr(error.value, "status_code", None) == 404


def test_deleting_period_removes_uploaded_and_pdf_files(db, tmp_path):
    from salary_web.app import delete_period
    from salary_web.models import Calculation, UploadedReport

    department = Department(code="delete", name="Delete")
    employee = Employee(full_name="Удаляемый Сотрудник Один")
    period = Period(department=department, year=2026, month=3)
    upload = tmp_path / "report.xlsx"
    pdf = tmp_path / "salary.pdf"
    upload.write_bytes(b"xlsx")
    pdf.write_bytes(b"pdf")
    period.reports.append(UploadedReport(
        report_type="profit", original_filename=upload.name,
        stored_path=str(upload), file_hash="hash",
    ))
    period.calculations.append(Calculation(
        employee=employee, snapshot_json="{}", pdf_path=str(pdf),
    ))
    db.add(period)
    db.commit()
    period_id = period.id
    delete_period(db, period)
    db.commit()
    assert db.get(Period, period_id) is None
    assert not upload.exists()
    assert not pdf.exists()


def test_all_department_api_wrappers_and_error_responses(client_and_key):
    client, secret = client_and_key
    headers = {"X-API-Key": secret}
    year = 2400 + int(uuid.uuid4().hex[:2], 16)
    create_period = client.post(f"/api/departments/b2b/periods/{year}/2", headers=headers)
    assert create_period.status_code == 200
    duplicate_period = client.post(f"/api/departments/b2b/periods/{year}/2", headers=headers)
    assert duplicate_period.status_code == 409
    assert "уже существует" in duplicate_period.json()["detail"]
    assert client.get(f"/api/departments/b2b/periods/{year}/2/validation", headers=headers).status_code == 200
    assert client.post(f"/api/departments/b2b/periods/{year}/2/validate", headers=headers).status_code == 200
    bad_upload = client.post(
        f"/api/departments/b2b/periods/{year}/2/reports/unknown",
        headers=headers,
        files={"file": ("unknown.xlsx", b"bad")},
    )
    assert bad_upload.status_code == 400
    assert client.post(f"/api/departments/b2b/periods/{year}/2/calculate", headers=headers).status_code == 400
    assert client.post(f"/api/departments/b2b/periods/{year}/2/pdf", headers=headers).status_code == 400

    db = SessionLocal()
    period = db.query(Period).filter_by(year=year, month=2).one()
    employee = Employee(full_name=f"API Сотрудник {uuid.uuid4().hex}")
    report = manager_report(); report["employee"] = employee.full_name; report["report_type"] = "manager"
    calculation = __import__("salary_web.models", fromlist=["Calculation"]).Calculation(
        period=period, employee=employee, snapshot_json=json.dumps(report, ensure_ascii=False)
    )
    db.add(calculation); db.commit(); calculation_id = calculation.id; db.close()

    base = f"/api/departments/b2b/periods/{year}/2"
    listing = client.get(f"{base}/calculations", headers=headers)
    assert listing.status_code == 200 and listing.json()["calculations"]
    assert client.get(f"{base}/calculations/{calculation_id}", headers=headers).status_code == 200
    assert client.get(f"{base}/calculations/999999", headers=headers).status_code == 404
    assert client.post(f"{base}/calculations/{calculation_id}/pdf", headers=headers).status_code == 200
    assert client.get(f"{base}/calculations/{calculation_id}/pdf/download", headers=headers).status_code == 200
    assert client.get("/api/departments/missing/periods/2026/1", headers=headers).status_code == 404


def test_inactive_api_key_is_rejected(client_and_key):
    client, secret = client_and_key
    db = SessionLocal()
    key = db.query(ApiKey).filter_by(key_hash=hash_api_key(secret)).one()
    key.is_active = 0; db.commit(); db.close()
    response = client.post("/api/departments/b2b/periods/2999/1", headers={"X-API-Key": secret})
    assert response.status_code == 401
