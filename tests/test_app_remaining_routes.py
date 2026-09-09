import importlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

web = importlib.import_module("salary_web.app")
from salary_web.models import Calculation, CalculationAdjustment, Department, Employee, Period, User
from salary_web.auth import make_session_token
from tests.test_generators import chief_report, manager_report


def make_calculation(db, report=None):
    department = Department(code="route", name="Route", is_active=1)
    period = Period(year=2040, month=4, department=department)
    employee = Employee(full_name="Route Employee")
    calculation = Calculation(
        period=period,
        employee=employee,
        snapshot_json=json.dumps(report or manager_report(), ensure_ascii=False),
    )
    db.add(calculation); db.commit()
    return period, calculation


def patch_access(monkeypatch, period, calculation):
    monkeypatch.setattr(web, "get_period_by_date_or_404", lambda *_: period)
    monkeypatch.setattr(web, "get_calculation_or_404", lambda *_: calculation)
    monkeypatch.setattr(web, "ensure_period_access", lambda *_: None)


def test_public_and_authenticated_middleware_paths():
    with TestClient(web.app, follow_redirects=False) as client:
        assert client.get("/health").json() == {"status": "ok"}
        assert client.get("/login").status_code == 200
        assert client.get("/api/periods/999").status_code == 401
        client.post("/login", data={"username": "admin", "password": "admin"})
        assert client.get("/").headers["location"] == "/periods"


def test_direct_form_success_and_upload_branches(db, monkeypatch):
    period, calculation = make_calculation(db)
    patch_access(monkeypatch, period, calculation)
    request = Mock()
    monkeypatch.setattr(web, "save_uploaded_reports_batch", Mock(side_effect=ValueError("bad")))
    with pytest.raises(HTTPException):
        web.upload_report_form(2040, 4, request, [], db)
    monkeypatch.setattr(web, "save_uploaded_reports_batch", Mock(return_value=[object()]))
    monkeypatch.setattr(web, "remove_period_calculations", Mock())
    monkeypatch.setattr(web, "report_completeness", Mock(return_value={"complete": True}))
    monkeypatch.setattr(web, "validate_period_reports", Mock())
    assert web.upload_report_form(2040, 4, request, [], db).status_code == 303

    monkeypatch.setattr(web, "calculate_period", Mock(return_value=[]))
    assert web.calculate_period_form(2040, 4, request, db).status_code == 303
    c_without = SimpleNamespace(snapshot_json="")
    monkeypatch.setattr(web, "calculate_period", Mock(return_value=[calculation, c_without]))
    monkeypatch.setattr(web, "generate_pdf_for_calculation", Mock(return_value=Path("x.pdf")))
    assert web.generate_period_pdfs_form(2040, 4, request, db).status_code == 303

    monkeypatch.setattr(web, "save_snapshot_text", Mock())
    assert web.update_calculation_snapshot(calculation.id, request, "{}", db).status_code == 303
    monkeypatch.setattr(web, "refresh_calculated_values", lambda *_: False)
    monkeypatch.setattr(web, "current_user", lambda *_: None)
    monkeypatch.setattr(web.templates, "TemplateResponse", lambda *_a, **_k: "page")
    assert web.calculation_page(calculation.id, request, db) == "page"


def test_key_client_adjustment_all_paths(db, monkeypatch):
    report = chief_report(); report["report_type"] = "chief"
    period, calculation = make_calculation(db, report)
    patch_access(monkeypatch, period, calculation)
    request = Mock()
    with pytest.raises(HTTPException):
        web.add_calculation_adjustment(calculation.id, request, "key_clients_profit", "x", client="", profit=1, db=db)
    with pytest.raises(HTTPException):
        web.add_calculation_adjustment(calculation.id, request, "key_clients_profit", "x", client="A", profit=None, db=db)
    response = web.add_calculation_adjustment(
        calculation.id, request, "key_clients_profit", "x", client="A", profit=100, return_to="", db=db
    )
    assert response.status_code == 303
    adjustment = calculation.adjustments[0]
    with pytest.raises(HTTPException):
        web.update_calculation_adjustment(calculation.id, adjustment.id, request, 100, "", db)
    assert web.update_calculation_adjustment(calculation.id, adjustment.id, request, 200, "B", db).status_code == 303
    assert web.delete_calculation_adjustment(calculation.id, adjustment.id, request, db).status_code == 303

    legacy = CalculationAdjustment(
        period_id=period.id, employee_id=calculation.employee_id, calculation_id=calculation.id,
        section_code="key_clients_profit", adjustment_type="bonus", amount=10, comment="old",
    )
    db.add(legacy); db.commit()
    assert web.update_calculation_adjustment(calculation.id, legacy.id, request, 50, "C", db).status_code == 303


def test_api_wrapper_success_and_error_paths(db, monkeypatch, tmp_path):
    period, calculation = make_calculation(db)
    monkeypatch.setattr(web, "get_period_by_date_or_404", lambda *_: period)
    monkeypatch.setattr(web, "calculate_period", Mock(return_value=[]))
    assert web.calculate_period_response(db, period)["calculations_created"] == 0
    assert web.create_period_by_date_api(2041, 5, db)["year"] == 2041
    assert web.validate_period_by_date_api(2040, 4, db)
    monkeypatch.setattr(web, "validate_period_reports", Mock(return_value={"valid": True}))
    assert web.validate_period_reports_by_date_api(2040, 4, db) == {"valid": True}
    monkeypatch.setattr(web, "upload_report_to_period_api", Mock(return_value={"ok": 1}))
    assert web.upload_report_by_date_api(2040, 4, "profit", Mock(), db) == {"ok": 1}
    assert web.calculate_period_by_date_api(2040, 4, db)["calculations_created"] == 0

    monkeypatch.setattr(web, "generate_period_pdfs_response", Mock(return_value={"pdfs": []}))
    assert web.generate_period_pdfs_by_date_api(2040, 4, db) == {"pdfs": []}

    monkeypatch.setattr(web, "generate_pdf_for_calculation", Mock(side_effect=ValueError("bad")))
    monkeypatch.setattr(web, "get_period_calculation_or_404", lambda *_: calculation)
    with pytest.raises(HTTPException):
        web.generate_period_calculation_pdf_by_date_api(2040, 4, calculation.id, db)
    with pytest.raises(HTTPException):
        web.generate_calculation_pdf_api(calculation.id, db)

    calculation.pdf_path = "does-not-exist.pdf"
    with pytest.raises(HTTPException):
        web.calculation_pdf_response(calculation)

    pdf = tmp_path / "ok.pdf"; pdf.write_bytes(b"pdf")
    monkeypatch.setattr(web, "generate_pdf_for_calculation", lambda *_: pdf)
    result = web.generate_period_calculation_pdf_by_date_api(2040, 4, calculation.id, db)
    assert result["calculation_id"] == calculation.id


def test_generate_period_pdf_response_branches(db, monkeypatch, tmp_path):
    period, calculation = make_calculation(db)
    empty = Calculation(period=period, employee=Employee(full_name="Empty"), snapshot_json=None)
    db.add(empty); db.commit()
    pdf = tmp_path / "a.pdf"; pdf.write_bytes(b"pdf")
    monkeypatch.setattr(web, "calculate_period", lambda *_: [empty, calculation])
    monkeypatch.setattr(web, "generate_pdf_for_calculation", lambda *_: pdf)
    result = web.generate_period_pdfs_response(db, period, "route")
    assert result["pdfs_created"] == 1 and result["department_code"] == "route"
    monkeypatch.setattr(web, "calculate_period", Mock(side_effect=ValueError("bad")))
    with pytest.raises(HTTPException):
        web.generate_period_pdfs_response(db, period)
    monkeypatch.setattr(web, "calculate_period", lambda *_: [])
    assert web.generate_period_pdfs_response(db, period)["department_code"] == "route"


def test_remaining_access_admin_and_department_pdf_errors(db, monkeypatch):
    period, calculation = make_calculation(db)
    user = User(username="denied", password_hash="x", is_active=1, is_admin=0)
    db.add(user); db.commit()
    request = SimpleNamespace(cookies={web.SESSION_COOKIE: make_session_token(user.id)})
    with pytest.raises(HTTPException): web.ensure_period_access(request, db, period)

    # Duplicate profile name exercises the transaction rollback/error response.
    other = User(username="other", password_hash="x", is_active=1)
    db.add(other); db.commit()
    monkeypatch.setattr(web, "require_admin", lambda *_: user)
    with pytest.raises(HTTPException):
        web.update_user_profile_form(user.id, Mock(), "other", "", db)

    monkeypatch.setattr(web, "get_department_by_code_or_404", lambda *_: period.department)
    monkeypatch.setattr(web, "require_api_key_for_department", lambda *_: None)
    monkeypatch.setattr(web, "get_period_by_department_date_or_404", lambda *_: period)
    monkeypatch.setattr(web, "get_period_calculation_or_404", lambda *_: calculation)
    monkeypatch.setattr(web, "generate_pdf_for_calculation", Mock(side_effect=ValueError("bad")))
    with pytest.raises(HTTPException):
        web.generate_department_calculation_pdf_api("route", 2040, 4, calculation.id, Mock(), db)


def test_remove_calculation_files_and_directories(db, monkeypatch, tmp_path):
    period, calculation = make_calculation(db)
    pdf = tmp_path / "nested" / "file.pdf"; pdf.parent.mkdir(); pdf.write_bytes(b"x")
    calculation.pdf_path = str(pdf)
    output = tmp_path / "output"; output.mkdir()
    monkeypatch.setattr(web, "resolve_service_data_path", lambda p: Path(p))
    monkeypatch.setattr(web, "period_storage_dir", lambda *_: output)
    monkeypatch.setattr(web, "report_completeness", lambda *_: {"validated": False, "errors": False, "complete": False})
    web.remove_period_calculations(db, period)
    assert not pdf.exists() and not output.exists()
    web._remove_empty_parents(tmp_path / "missing")


def test_upload_api_complete_validation_branch(db, monkeypatch):
    period, _ = make_calculation(db)
    report = SimpleNamespace(
        id=1, report_type="profit", original_filename="profit.xlsx", file_hash="h"
    )
    monkeypatch.setattr(web, "save_uploaded_report", lambda *_: report)
    monkeypatch.setattr(web, "remove_period_calculations", lambda *_: None)
    monkeypatch.setattr(web, "report_completeness", lambda *_: {"complete": True})
    validate = Mock(); monkeypatch.setattr(web, "validate_period_reports", validate)
    assert web.upload_report_to_period_api(db, period, "profit", Mock())["id"] == 1
    validate.assert_called_once()


def test_file_cleanup_os_errors_are_nonfatal(db, monkeypatch):
    period, calculation = make_calculation(db)
    calculation.pdf_path = "bad.pdf"
    class BadPath:
        parent = None
        def is_file(self): raise OSError("blocked")
        def exists(self): raise OSError("blocked")
    bad = BadPath(); bad.parent = bad
    monkeypatch.setattr(web, "resolve_service_data_path", lambda *_: bad)
    monkeypatch.setattr(web, "period_storage_dir", lambda *_: Path("/definitely/missing/salary"))
    monkeypatch.setattr(web, "report_completeness", lambda *_: {"validated": False, "errors": False, "complete": False})
    web.remove_period_calculations(db, period)

    period2 = Period(year=2041, month=1, department=Department(code="delete", name="Delete"))
    from salary_web.models import UploadedReport
    period2.reports.append(UploadedReport(
        report_type="profit", original_filename="p", stored_path="bad", file_hash="h", status="uploaded"
    ))
    db.add(period2); db.commit()
    web.delete_period(db, period2)


def test_cleanup_false_branches(db, monkeypatch, tmp_path):
    department = Department(code="false", name="False")
    period = Period(year=2042, month=1, department=department)
    period.calculations.extend([
        Calculation(employee=Employee(full_name="No path"), snapshot_json="{}", pdf_path=None),
        Calculation(employee=Employee(full_name="Missing path"), snapshot_json="{}", pdf_path=str(tmp_path / "missing.pdf")),
    ])
    db.add(period); db.commit()
    monkeypatch.setattr(web, "resolve_service_data_path", lambda p: Path(p))
    monkeypatch.setattr(web, "period_storage_dir", lambda *_: tmp_path / "no-output")
    monkeypatch.setattr(web, "report_completeness", lambda *_: {"validated": False, "errors": False, "complete": False})
    web.remove_period_calculations(db, period)

    from salary_web.models import UploadedReport
    period2 = Period(year=2042, month=2, department=department)
    period2.reports.extend([
        UploadedReport(report_type="profit", original_filename="a", stored_path="", file_hash="a", status="uploaded"),
        UploadedReport(report_type="debt", original_filename="b", stored_path=str(tmp_path / "absent"), file_hash="b", status="uploaded"),
    ])
    db.add(period2); db.commit()
    web.delete_period(db, period2)
