import pytest

from salary_web.auth import make_session_token
from salary_web.models import CalculationAdjustment
from salary_web.snapshot_presenter import build_snapshot_sections
from tests.test_extended_boundaries import scoped_client  # noqa: F401


@pytest.mark.parametrize("code", ["profit", "brand", "zic", "other", "debt", "cycle", "timesheet", "lukoil", "key_clients_profit"])
def test_only_corrected_section_is_marked(code):
    snapshot = {code: {}, "communications": {}}
    assert all(not section["corrections"] for section in build_snapshot_sections(snapshot))
    records = [{"section_code": code, "amount": 0, "comment": "Проверено"},
               {"section_code": code, "amount": -1000, "comment": "Удержание"}]
    sections = build_snapshot_sections(snapshot, records)
    assert sections[0]["corrections"] == records
    assert sections[1]["corrections"] == []
    snapshot["manual_adjustments"] = records
    assert build_snapshot_sections(snapshot)[0]["corrections"] == records
    assert build_snapshot_sections(snapshot, [])[0]["corrections"] == []


def test_web_marker_tracks_add_update_delete(scoped_client, db):
    client, _, _, calculation, user, _ = scoped_client
    client.cookies.set("salary_user", make_session_token(user.id))
    url = f"/calculations/{calculation.id}"
    assert "Есть корректировки" not in client.get(url).text
    assert client.post(url + "/adjustments", data={"section_code": "profit", "adjustment_type": "correction",
        "amount": "1500", "comment": "Доплата <тест>"}).status_code == 303
    html = client.get(url).text
    assert 'corrected-section" id="section-profit"' in html
    assert 'corrected-section" id="section-cycle"' not in html
    assert "Есть корректировки" in html and "1 500.00" in html and "Доплата &lt;тест&gt;" in html
    record = db.query(CalculationAdjustment).filter_by(calculation_id=calculation.id).one()
    path = url + f"/adjustments/{record.id}"
    assert client.post(path + "/update", data={"amount": "-2000", "comment": "Исправлено"}).status_code == 303
    assert "-2 000.00" in client.get(url).text
    assert client.post(path + "/delete").status_code == 303
    assert "Есть корректировки" not in client.get(url).text
