import json
from urllib.parse import unquote

from salary_web.app import period_url
from salary_web.auth import make_session_token
from salary_web.models import CalculationAdjustment
from salary_web.snapshot_editor import save_snapshot
from tests.test_extended_boundaries import scoped_client  # noqa: F401
from tests.test_validation_and_runner import complete_period, minimal_manager, minimal_chief


def test_named_department_urls(scoped_client, db):
    client, period, _, _, user, _ = scoped_client
    client.cookies.set("salary_user", make_session_token(user.id))
    period.department.name = "Оптовые продажи / Сибирь"
    db.commit()
    url = period_url(period)
    assert unquote(url).startswith("/Оптовые_продажи___Сибирь/")
    assert client.get(url).status_code == 200
    old = f"/departments/{period.department_id}/periods/{period.year}/{period.month}"
    assert client.get(old).status_code == 404
    period.department.name = "Новый отдел"; db.commit()
    assert client.get(url).status_code == 404
    assert client.get(old).status_code == 404
    user.is_admin = 0; db.commit()
    assert client.get(period_url(period)).status_code == 403


def test_short_url_requires_unique_department_name(scoped_client, db):
    client, first, second, _, user, _ = scoped_client
    client.cookies.set("salary_user", make_session_token(user.id))
    second.department.name = first.department.name
    db.commit()
    assert client.get(period_url(first)).status_code == 409


def test_short_url_manual_creation(scoped_client, db):
    client, period, _, _, user, _ = scoped_client
    client.cookies.set("salary_user", make_session_token(user.id))
    url = period_url(period)
    assert unquote(url) == "/Own/2050/01"
    response = client.post(url + "/manual-calculations", data={"employee_name": "Short URL Employee"})
    assert response.status_code == 303
    assert client.get(response.headers["location"]).status_code == 200


def test_individual_recalculation_is_isolated(scoped_client, db, tmp_path, monkeypatch):
    import salary_web.calculation_runner as runner
    client, _, _, _, user, _ = scoped_client
    client.cookies.set("salary_user", make_session_token(user.id))
    period = complete_period(db, tmp_path)
    manager = minimal_manager()
    monkeypatch.setattr(runner, "load_context_from_files", lambda *args: {})
    monkeypatch.setattr(runner, "calculate_managers", lambda _: [manager])
    monkeypatch.setattr(runner, "calculate_chief", lambda *_: minimal_chief())
    target, other = runner.calculate_period(db, period)
    db.commit()
    for calc in (target, other):
        calc.pdf_path = f"old-{calc.id}.pdf"
        db.add(CalculationAdjustment(period_id=period.id, employee_id=calc.employee_id,
            calculation_id=calc.id, section_code="profit", adjustment_type="correction", amount=123))
    db.commit()
    other_snapshot = other.snapshot_json
    manager["value"] = 999
    url = f"/calculations/{target.id}/calculate"
    assert client.post(url).status_code == 303
    db.refresh(target); db.refresh(other)
    assert json.loads(target.snapshot_json)["value"] == 999 and target.pdf_path is None
    assert other.snapshot_json == other_snapshot and other.pdf_path == f"old-{other.id}.pdf"
    assert db.query(CalculationAdjustment).filter_by(calculation_id=target.id).count() == 0
    assert db.query(CalculationAdjustment).filter_by(calculation_id=other.id).count() == 1
    monkeypatch.setattr(runner, "calculate_managers", lambda _: [])
    before = target.snapshot_json
    assert client.post(url).status_code == 400
    assert target.snapshot_json == before
    user.is_admin = 0; db.commit()
    assert client.post(url).status_code == 403


def test_manual_create_button_keeps_entries(scoped_client, db):
    client, _, _, calc, user, _ = scoped_client
    client.cookies.set("salary_user", make_session_token(user.id))
    save_snapshot(calc, {"report_type": "manual", "employee": calc.employee.full_name,
        "additional_payments": {"items": [{"description": "Оклад", "amount": 50000}]}})
    db.commit()
    before = calc.snapshot_json
    response = client.post(f"/calculations/{calc.id}/calculate")
    assert response.status_code == 303
    assert response.headers["location"] == f"/calculations/{calc.id}"
    assert calc.snapshot_json == before
