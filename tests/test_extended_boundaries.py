"""Behavioral boundaries checked with isolated databases and synthetic files."""
import json
from io import BytesIO
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, UploadFile
from fastapi.testclient import TestClient

from salary_web.app import app, create_period
from salary_web.auth import hash_api_key, make_session_token, read_session_user_id
from salary_web.config import period_storage_dir, resolve_service_data_path
from salary_web.database import get_db
from salary_web.models import (
    ApiKey, ApiKeyDepartment, Calculation, Department, Employee, Period, User,
)
from tests.test_generators import manager_report
from tests.test_rounding_and_auth import request_with_cookie


@pytest.fixture
def scoped_client(db):
    own = Department(code="own", name="Own")
    other = Department(code="other", name="Other")
    user = User(username="audit-admin", password_hash="unused", is_admin=1, is_active=1)
    first = Period(year=2050, month=1, department=own)
    second = Period(year=2050, month=1, department=other)
    key = ApiKey(name="boundary-key", key_hash=hash_api_key("boundary-secret"), is_active=1)
    calculation = Calculation(period=second, employee=Employee(full_name="Boundary Employee"),
                              snapshot_json=json.dumps(manager_report()))
    db.add_all([first, calculation, user, key]); db.flush()
    db.add(ApiKeyDepartment(api_key_id=key.id, department_id=own.id)); db.commit()
    app.dependency_overrides[get_db] = lambda: db
    client = TestClient(app, raise_server_exceptions=False, follow_redirects=False)
    try:
        yield client, first, second, calculation, user, key
    finally:
        client.close()
        app.dependency_overrides.clear()


API_ACTIONS = [
    ("GET", ""), ("POST", ""), ("GET", "/validation"), ("POST", "/validate"),
    ("POST", "/reports/profit"), ("POST", "/calculate"), ("POST", "/pdf"),
    ("GET", "/calculations"), ("GET", "/calculations/{id}"),
    ("POST", "/calculations/{id}/pdf"), ("GET", "/calculations/{id}/pdf/download"),
]


@pytest.mark.parametrize("method,suffix", API_ACTIONS)
@pytest.mark.parametrize("credential", ["missing", "invalid", "foreign", "disabled"])
def test_api_key_access_matrix(scoped_client, db, method, suffix, credential):
    client, _, _, calculation, _, key = scoped_client
    if credential == "disabled":
        key.is_active = 0; db.commit()
    headers = {} if credential == "missing" else {
        "X-API-Key": "wrong" if credential == "invalid" else "boundary-secret"}
    response = client.request(method, "/api/departments/other/periods/2050/1" + suffix.format(id=calculation.id),
                              headers=headers, files={"file": ("profit.xlsx", b"unreadable")})
    assert response.status_code == (403 if credential == "foreign" else 401), response.text
    assert db.query(Calculation).count() == 1


@pytest.mark.parametrize("suffix,method", [("", "GET"), ("/pdf", "POST"), ("/pdf/download", "GET")])
def test_own_api_key_cannot_fetch_foreign_calculation(scoped_client, method, suffix):
    client, _, _, calculation, _, _ = scoped_client
    response = client.request(method,
        f"/api/departments/own/periods/2050/1/calculations/{calculation.id}{suffix}",
        headers={"X-API-Key": "boundary-secret"})
    assert response.status_code == 404


@pytest.mark.parametrize("method,path,expected", [
    ("GET", "/api/departments/own/periods/not-a-year/1", 422),
    ("POST", "/api/departments/own/periods/2051/13", 400),
    ("GET", "/api/departments/unknown/periods/2050/1", 404),
])
def test_api_invalid_period_paths_return_client_errors(scoped_client, method, path, expected):
    client, *_ = scoped_client
    response = client.request(method, path, headers={"X-API-Key": "boundary-secret"})
    assert response.status_code == expected


def test_api_rejects_invalid_upload_without_creating_period(scoped_client, db):
    client, *_ = scoped_client
    headers = {"X-API-Key": "boundary-secret"}
    missing_file = client.post("/api/departments/own/periods/2051/1/reports/profit", headers=headers)
    assert missing_file.status_code == 422
    invalid_type = client.post(
        "/api/departments/own/periods/2051/1/reports/unknown",
        headers=headers,
        files={"file": ("report.xlsx", b"content")},
    )
    assert invalid_type.status_code == 400
    assert db.query(Period).count() == 2


def test_api_calculation_without_reports_returns_client_error(scoped_client):
    client, *_ = scoped_client
    response = client.post(
        "/api/departments/own/periods/2050/1/calculate",
        headers={"X-API-Key": "boundary-secret"},
    )
    assert response.status_code == 400


def test_repeated_api_upload_replaces_file_and_record(scoped_client, db, tmp_path, monkeypatch):
    import salary_web.report_storage as storage
    from salary_web.config import resolve_service_data_path
    from salary_web.models import UploadedReport

    monkeypatch.setattr(storage, "UPLOADS_DIR", tmp_path)
    client, period, *_ = scoped_client
    url = f"/api/departments/own/periods/{period.year}/{period.month}/reports/profit"
    headers = {"X-API-Key": "boundary-secret"}
    for payload in (b"first upload", b"replacement upload"):
        response = client.post(url, headers=headers, files={"file": ("profit.xlsx", payload)})
        assert response.status_code == 200, response.text

    reports = db.query(UploadedReport).filter_by(period_id=period.id, report_type="profit").all()
    assert len(reports) == 1
    assert resolve_service_data_path(reports[0].stored_path).read_bytes() == b"replacement upload"


@pytest.mark.parametrize("mutation", ["user", "version", "expiry", "signature", "truncate", "append"])
def test_session_token_tampering_is_rejected(mutation):
    token = make_session_token(42)
    parts = token.split(":")
    if mutation == "user":
        parts[0] = "43"
    elif mutation == "version":
        parts[1] = "1"
    elif mutation == "expiry":
        parts[2] = str(int(parts[2]) + 99999)
    elif mutation == "signature":
        parts[3] = "0" * 64
    elif mutation == "truncate":
        parts = parts[:-1]
    else:
        parts.append("extra")
    assert read_session_user_id(request_with_cookie(":".join(parts))) is None


@pytest.mark.parametrize("month", [-100, -1, 0, 13, 100])
def test_invalid_month_leaves_no_period(db, month):
    with pytest.raises(HTTPException) as error:
        create_period(db, 2050, month)
    assert error.value.status_code == 400
    assert db.query(Period).count() == 0


@pytest.mark.parametrize("year", [-1, 0, 10000])
def test_invalid_calendar_year_is_rejected(db, year):
    with pytest.raises(HTTPException) as error:
        create_period(db, year, 1)
    assert error.value.status_code in (400, 422)
    assert db.query(Period).count() == 0


@pytest.mark.parametrize("suffix", [".xls", ".xlsx", ".XLSX"])
@pytest.mark.parametrize("content", [b"", b"PK\x03\x04broken", b"\xff\xfe\x00\x80", b"<html>not excel</html>"])
def test_corrupt_excel_variants_are_reported(tmp_path, suffix, content):
    from parsers.excel_reader import read_excel
    path = tmp_path / ("damaged" + suffix)
    path.write_bytes(content)
    with pytest.raises(ValueError, match="пуст|прочитать"):
        read_excel(path)


@pytest.mark.parametrize("size", [0, 1, 1024 * 1024 - 1, 1024 * 1024, 1024 * 1024 + 1, 2 * 1024 * 1024 + 1])
def test_upload_content_and_hash_across_chunk_boundaries(db, tmp_path, monkeypatch, size):
    import hashlib
    import salary_web.report_storage as storage
    monkeypatch.setattr(storage, "UPLOADS_DIR", tmp_path)
    period = Period(year=2050, month=1, department=Department(code="chunks", name="Chunks"))
    db.add(period); db.commit()
    content = b"x" * size
    report = storage.save_uploaded_report(db, period, "profit",
        UploadFile(filename="profit.xlsx", file=BytesIO(content)))
    assert resolve_service_data_path(report.stored_path).read_bytes() == content
    assert report.file_hash == hashlib.sha256(content).hexdigest()
    assert not list(tmp_path.rglob("*.part"))


@pytest.mark.parametrize("value", ["-1000000000000", "-0.01", "0", "0.01", "1000000000000"])
def test_money_boundaries_are_accepted(scoped_client, db, value):
    client, _, _, calculation, user, _ = scoped_client
    client.cookies.set("salary_user", make_session_token(user.id))
    response = client.post(f"/calculations/{calculation.id}/additional-payments",
                           data={"title": "Boundary", "amount": value})
    assert response.status_code == 303, response.text
    db.refresh(calculation)
    snapshot = json.loads(calculation.snapshot_json)
    assert any(item.get("amount") == float(value) and item.get("description") == "Boundary"
               for item in snapshot["additional_payments"]["items"])


@pytest.mark.parametrize("codes", [("sales/a", "sales-a"), ("SALES", "sales"), ("***", "default")])
def test_distinct_department_codes_never_share_storage(tmp_path, codes):
    a, b = [SimpleNamespace(year=2050, month=1,
        department=SimpleNamespace(id=i, code=code)) for i, code in enumerate(codes, start=1)]
    assert period_storage_dir(tmp_path, a) != period_storage_dir(tmp_path, b)


def test_recalculation_preserves_employee_missing_from_new_reports(db, tmp_path, monkeypatch):
    import salary_web.calculation_runner as runner
    from tests.test_validation_and_runner import complete_period, minimal_manager, minimal_chief
    period = complete_period(db, tmp_path)
    stale = Calculation(period=period, employee=Employee(full_name="Removed Employee"),
                        snapshot_json='{}')
    db.add(stale); db.commit()
    monkeypatch.setattr(runner, "load_context_from_files", lambda *args: {})
    monkeypatch.setattr(runner, "calculate_managers", lambda context: [minimal_manager()])
    monkeypatch.setattr(runner, "calculate_chief", lambda context, reports: minimal_chief())
    runner.calculate_period(db, period)
    db.flush()
    assert db.query(Calculation).filter_by(period_id=period.id).count() == 3
    assert db.get(Calculation, stale.id) is stale
