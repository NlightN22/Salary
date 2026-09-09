import json
from types import SimpleNamespace

import pytest

from tests.test_generators import manager_report, chief_report
from salary_web.snapshot_editor import (
    append_adjustment, refresh_calculated_values, load_snapshot,
    update_adjustment, remove_adjustment, _recalculate_debt_adjustments,
)


@pytest.mark.parametrize("chief", [False, True])
def test_debt_adjustment_lifecycle(chief):
    report = chief_report() if chief else manager_report()
    report["debt"]["total"] = 56375.46
    report["additional_payments"] = {"items": [{"description": "Тест", "amount": 3000}]}
    calculation = SimpleNamespace(snapshot_json=json.dumps(report))
    append_adjustment(calculation, "debt", "correction", 1128859.39, "Агинское ДРСУ")
    result = load_snapshot(calculation)
    assert result["debt"]["total"] == 1185234.85
    assert result["debt"]["responsibility"] == pytest.approx(11852.35, abs=.005)
    assert result["additional_payments"]["total"] == 3000
    assert not refresh_calculated_values(calculation)
    update_adjustment(calculation, "debt", "correction", 1128859.39, "Агинское ДРСУ",
                      "debt", "correction", -1000, "Исправление")
    assert load_snapshot(calculation)["debt"]["total"] == 55375.46
    remove_adjustment(calculation, "debt", "correction", -1000, "Исправление")
    assert load_snapshot(calculation)["debt"]["total"] == 56375.46
    update_adjustment(calculation, "debt", "correction", 1, "нет", "debt", "correction", 2, "нет")
    remove_adjustment(calculation, "debt", "correction", 1, "нет")
    assert load_snapshot(calculation)["additional_payments"]["total"] == 3000


def test_legacy_debt_entry_without_payment_and_without_sales():
    report = {"debt": {"total": 100}, "manual_adjustments": [
        {"section_code": "debt", "amount": 20, "comment": "x", "adjustment_type": "correction"}
    ]}
    _recalculate_debt_adjustments(report)
    assert report["debt"]["total"] == 120
    assert report["debt"]["ratio"] == 0
    _recalculate_debt_adjustments(report)
    assert report["debt"]["total"] == 120
