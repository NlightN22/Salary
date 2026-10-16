import json
import hashlib
import hmac
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pandas as pd
import pytest
from fastapi import HTTPException
from starlette.requests import Request

from salary_web import auth
from salary_web.app import (
    _remove_empty_parents,
    _set_api_key_departments,
    _set_user_departments,
    create_period,
    default_department_for_period_form,
    departments_for_user,
    ensure_period_access,
    get_adjustment_or_404,
    get_department_by_code_or_404,
    get_payment_or_404,
    get_period_by_department_date_or_404,
    periods_query_for_user,
    reports_by_type,
    serialize_calculation,
    serialize_calculation_summary,
    serialize_pdf_result,
    template_context,
)
from salary_web.models import (
    ApiKey,
    Calculation,
    CalculationAdjustment,
    Department,
    Employee,
    Period,
    User,
    UserDepartment,
)
from salary_web.snapshot_presenter import (
    _debt_large_items,
    _flatten_value,
    _format_value,
    _key_client_items,
    _salary_total,
    _section_visible_value,
    build_final_summary_rows,
    build_snapshot_sections,
)
from salary_web.snapshot_editor import (
    _amount_matches, append_adjustment, generate_pdf_for_calculation, save_snapshot_text,
    update_adjustment,
)
from salary_web.ui_helpers import report_type_label, status_label
from services import calculation_context
from tests.test_generators import chief_report


def request_with_cookie(token=None):
    headers = [] if token is None else [(b"cookie", f"salary_session={token}".encode())]
    return Request({"type": "http", "method": "GET", "path": "/", "headers": headers})


def simple_request_with_cookie(token):
    return SimpleNamespace(cookies={auth.SESSION_COOKIE: token})


def test_presenter_remaining_branches():
    assert build_final_summary_rows({}) == []
    chief = {
        "report_type": "chief", "total_bonus": 1, "salary_total": None,
        "profit": {"kpi": {"bonus": 2}}, "cycle": {"bonus": 3}, "zic": {"bonus": 4},
        "other": {"bonus": 5}, "lukoil": {"bonus": 0},
        "key_clients_profit": {"bonus": 6}, "debt": {"responsibility": "bad"},
        "additional_payments": {"total": 7}, "timesheet": {"hours": 8, "salary": 9},
    }
    assert build_final_summary_rows(chief)
    assert _salary_total({"total_bonus": None}) is None
    assert _salary_total({"total_bonus": 2, "timesheet": {"salary": 3}}) == 5
    assert _section_visible_value("key_clients_profit", {"bonus_percent": 0.1, "items": []})["bonus_percent"] == 10
    assert _key_client_items([]) == []
    assert _key_client_items({"items": [None, {}, {"client": "A", "profit": 1, "bonus": 0.1}]})[0]["client"] == "A"
    assert _debt_large_items([]) == []
    assert _debt_large_items({"large_items": [None, {"contractor": "A", "overdue": 1}]})[0]["number"] == "2"
    assert _flatten_value([])[0]["field"] == "Список"
    assert _flatten_value({})[0]["field"] == "Значение"
    assert _format_value("manager") == "Менеджер"
    assert _format_value("chief") == "Руководитель"
    assert _format_value(True) == "да"
    assert _format_value(False) == "нет"
    assert _format_value(2, "ratio") == "2%"
    assert _format_value(2.5, "x") == "2.50"
    sections = build_snapshot_sections({"lukoil": {"calculation_enabled": False}, "debt": [], "key_clients_profit": []})
    assert sections[0]["hide_field_table"] is True
    assert status_label(None) == ""
    assert report_type_label(None) == ""


def test_context_load_and_errors(monkeypatch, tmp_path):
    folder = tmp_path / "2026" / "1"; folder.mkdir(parents=True)
    monkeypatch.setattr(calculation_context, "get_latest_period", lambda **_kwargs: folder)
    monkeypatch.setattr(calculation_context, "find_files", lambda _p: {})
    with pytest.raises(FileNotFoundError):
        calculation_context.load_context("B2B-направление")

    files = {name: tmp_path / f"{name}.xlsx" for name in calculation_context.REQUIRED_FILES}
    frames = {
        str(files["profit"]): pd.DataFrame([[1]]),
        str(files["brand"]): pd.DataFrame([[1] * 9]),
        str(files["debt"]): pd.DataFrame([[1]]),
        str(files["communications"]): pd.DataFrame([[1]]),
        str(files["cycle"]): pd.DataFrame([[1]]),
        str(files["timesheet"]): pd.DataFrame([[1, 2]]),
    }
    monkeypatch.setattr(calculation_context, "find_files", lambda _p: files)
    monkeypatch.setattr(calculation_context, "read_excel", lambda p: frames[str(p)])
    for parser_name in ("ProfitParser", "BrandParser", "DebtParser", "CommParser", "CycleParser", "TimesheetParser"):
        monkeypatch.setattr(calculation_context, parser_name, lambda frame: frame)
    result = calculation_context.load_context("B2B-направление")
    assert result["year"] == 2026
    aliased = dict(files); aliased["brand_sales"] = aliased.pop("brand")
    assert calculation_context.load_context_from_files(2026, 1, aliased)["month"] == 1
    with pytest.raises(ValueError):
        calculation_context._require_columns(pd.DataFrame([[1]]), 2, "x")


def test_auth_remaining(db):
    assert auth.read_session_user_id(request_with_cookie("abc:def")) is None
    assert auth.get_or_create_default_department(db)
    assert auth.get_or_create_default_department(db)
    inactive = User(username="off", password_hash=auth.hash_password("x"), is_active=0)
    db.add(inactive); db.commit()
    assert auth.current_user(request_with_cookie(auth.make_session_token(inactive.id)), db) is None
    payload = "not-an-integer"
    signature = hmac.new(auth.SESSION_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
    assert auth.read_session_user_id(simple_request_with_cookie(f"{payload}:{signature}")) is None
    assert auth.current_user(simple_request_with_cookie(auth.make_session_token(999999)), db) is None


def test_app_helper_remaining_paths(db, tmp_path, monkeypatch):
    d1 = Department(code="one", name="One", is_active=1)
    d2 = Department(code="two", name="Two", is_active=0)
    user = User(username="u", password_hash="x", is_admin=0, is_active=1)
    db.add_all([d1, d2, user]); db.flush()
    db.add(UserDepartment(user_id=user.id, department_id=d1.id)); db.commit()
    assert periods_query_for_user(db, user).count() == 0
    assert departments_for_user(db, user) == [d1]
    empty_user = User(username="empty", password_hash="x", is_admin=0, is_active=1)
    db.add(empty_user); db.commit()
    assert periods_query_for_user(db, empty_user).count() == 0
    assert departments_for_user(db, empty_user) == []
    assert default_department_for_period_form(db, empty_user, []) is None
    assert default_department_for_period_form(db, user, [d1]) == d1.id

    with pytest.raises(HTTPException): create_period(db, 2026, 1, department_id=9999)
    with pytest.raises(HTTPException): create_period(db, 2026, 1, empty_user, d1.id)
    with pytest.raises(HTTPException): get_department_by_code_or_404(db, "missing")
    with pytest.raises(HTTPException): get_period_by_department_date_or_404(db, d1, 2026, 1)
    with pytest.raises(HTTPException): ensure_period_access(request_with_cookie(), db, SimpleNamespace(department_id=d1.id))
    assert template_context(request_with_cookie(), db) ["current_user"] is None

    _set_user_departments(db, user, [d1.id, 9999]); db.flush()
    key = ApiKey(name="k", key_hash="h", key_secret="s"); db.add(key); db.flush()
    _set_api_key_departments(db, key, [d1.id, 9999]); db.flush()

    employee = Employee(full_name="Employee")
    period = Period(year=2026, month=2, department=d1)
    calculation = Calculation(period=period, employee=employee, snapshot_json=json.dumps({"report_type": "manager"}))
    db.add(calculation); db.commit()
    with pytest.raises(HTTPException): get_payment_or_404(db, calculation, 999)
    with pytest.raises(HTTPException): get_adjustment_or_404(db, calculation, 999)
    assert "department_code" in serialize_calculation(calculation, "one")
    assert "api_download_url" not in serialize_calculation_summary(period, calculation)
    calculation.pdf_path = "x.pdf"
    assert "api_download_url" in serialize_calculation_summary(period, calculation, "one")
    assert "/departments/one/" in serialize_pdf_result(period, calculation, Path("x.pdf"), "one")["api_download_url"]
    assert reports_by_type(SimpleNamespace(reports=[SimpleNamespace(report_type="custom")]))["custom"]

    nested = tmp_path / "a" / "b"; nested.mkdir(parents=True)
    _remove_empty_parents(nested)
    assert not nested.exists()


def test_snapshot_editor_remaining_paths(db, monkeypatch):
    assert _amount_matches(object(), 1) is False
    report = chief_report()
    report["key_clients_profit"] = {"bonus_percent": .1, "items": [{"client": "A", "profit": 100}]}
    calculation = SimpleNamespace(snapshot_json=json.dumps(report), status="", period=SimpleNamespace(year=2026, month=1))
    save_snapshot_text(calculation, json.dumps(report))
    alternate = chief_report()
    alternate["key_clients_profit"]["items"] = [{"client": "Only name", "profit": None}]
    save_snapshot_text(calculation, json.dumps(alternate))
    append_adjustment(calculation, "profit", "bonus", 1, "")
    update_adjustment(calculation, "profit", "bonus", 1, "", "profit", "bonus", 2, "new")
    monkeypatch.setattr("salary_web.snapshot_editor.period_storage_dir", lambda *_: Path("/tmp/salary-editor-test"))
    monkeypatch.setattr("salary_web.snapshot_editor.generate_chief_pdf", Mock())
    db_mock = Mock()
    assert generate_pdf_for_calculation(db_mock, calculation).suffix == ".pdf"

    # The second lookup may legitimately miss after a snapshot normalization.
    import salary_web.snapshot_editor as editor
    values = iter([{"section_code": "x", "adjustment_type": "x", "amount": 1, "comment": "x"}, None])
    monkeypatch.setattr(editor, "_find_adjustment", lambda *_: next(values))
    monkeypatch.setattr(editor, "update_additional_payment", lambda *_: None)
    update_adjustment(calculation, "x", "x", 1, "x", "y", "y", 2, "y")
