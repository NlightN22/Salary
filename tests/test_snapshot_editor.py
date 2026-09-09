import json

import pytest

from salary_web.models import Calculation
from salary_web.snapshot_editor import (
    append_additional_payment,
    append_adjustment,
    append_key_client_profit,
    load_snapshot,
    remove_adjustment,
    remove_key_client_profit,
    remove_additional_payment,
    refresh_calculated_values,
    save_snapshot_text,
    update_additional_payment,
    update_adjustment,
    update_key_client_profit,
    update_debt_large_item_comment,
)


def manager_report():
    return {
        "report_type": "manager",
        "employee": "Иванов Иван Иванович",
        "profit": {"bonus": 100},
        "brand": {"zic_bonus_total": 20, "lukoil_bonus": 0, "other_bonus_total": 30},
        "cycle": {"bonus": 40},
        "debt": {"responsibility": 10, "large_items": [{"contractor": "Клиент", "overdue": 100000, "comment": ""}]},
        "timesheet": {"salary": 1000},
        "additional_payments": {"items": [{"description": "", "amount": None}]},
    }


def chief_report():
    return {
        "report_type": "chief",
        "employee": "Руководитель",
        "profit": {"kpi": {"bonus": 100}},
        "cycle": {"bonus": 20},
        "zic": {"bonus": 30},
        "other": {"bonus": 40},
        "lukoil": {"bonus": 999},
        "key_clients_profit": {"bonus_percent": 0.1, "items": []},
        "debt": {"responsibility": 10},
        "timesheet": {"salary": 1000},
        "additional_payments": {"items": []},
    }


def calculation(report):
    return Calculation(snapshot_json=json.dumps(report, ensure_ascii=False))


def test_additional_payment_changes_bonus_and_salary_totals():
    item = calculation(manager_report())
    append_additional_payment(item, "За результат", 1500)
    report = load_snapshot(item)
    assert report["additional_payments"]["total"] == 1500
    assert report["total_bonus"] == 1680
    assert report["salary_total"] == 2680
    assert report["additional_payments"]["items"] == [
        {"description": "За результат", "amount": 1500},
        {"description": "", "amount": None},
    ]


def test_adjustment_is_added_to_end_and_can_be_removed():
    item = calculation(manager_report())
    append_adjustment(item, "profit", "bonus", 500, "Корректировка дохода")
    assert load_snapshot(item)["manual_adjustments"][0]["amount"] == 500
    remove_adjustment(item, "profit", "bonus", 500, "Корректировка дохода")
    report = load_snapshot(item)
    assert report["manual_adjustments"] == []
    assert report["additional_payments"]["total"] == 0


def test_key_client_bonus_is_ten_percent_and_not_generic_payment():
    item = calculation(chief_report())
    append_key_client_profit(item, "Тандан Голд", 100000)
    report = load_snapshot(item)
    assert report["key_clients_profit"]["items"][0]["bonus"] == 10000
    assert report["key_clients_profit"]["bonus"] == 10000
    assert report["additional_payments"]["total"] == 0
    assert report["salary_total"] == 11180


def test_chief_lukoil_is_forced_to_empty_and_zero():
    item = calculation(chief_report())
    append_key_client_profit(item, "Клиент", 0)
    report = load_snapshot(item)
    assert report["lukoil"]["bonus"] == 0
    assert report["lukoil"]["manager_items"] == []
    assert report["lukoil"]["calculation_enabled"] is False


def test_removing_last_key_client_restores_empty_table_row():
    item = calculation(chief_report())
    append_key_client_profit(item, "Клиент", 500)
    remove_key_client_profit(item, "Клиент", 500)
    assert load_snapshot(item)["key_clients_profit"]["items"] == [
        {"client": "", "profit": None, "bonus": None}
    ]


def test_debt_comment_targets_exact_row():
    item = calculation(manager_report())
    update_debt_large_item_comment(item, 0, "Ждут оплат от государства. Будем взыскивать неустойку")
    assert "государства" in load_snapshot(item)["debt"]["large_items"][0]["comment"]
    with pytest.raises(ValueError, match="не найдена"):
        update_debt_large_item_comment(item, 1, "x")


@pytest.mark.parametrize("value", ["{", '{"x": NaN}', "\x00"])
def test_invalid_json_text_is_rejected(value):
    item = calculation(manager_report())
    with pytest.raises(ValueError, match="JSON заполнен некорректно"):
        save_snapshot_text(item, value)


def test_missing_snapshot_is_rejected():
    with pytest.raises(ValueError, match="нет JSON-снимка"):
        load_snapshot(Calculation(snapshot_json=None))


def test_refresh_detects_changes_and_then_is_idempotent():
    report = chief_report()
    report["lukoil"]["bonus"] = 999
    item = calculation(report)
    assert refresh_calculated_values(item)
    assert not refresh_calculated_values(item)


def test_update_and_remove_additional_payments_found_and_missing():
    item = calculation(manager_report())
    append_additional_payment(item, "Старая", 10)
    update_additional_payment(item, "Старая", 10, "Новая", 20)
    assert load_snapshot(item)["additional_payments"]["total"] == 20
    update_additional_payment(item, "Не найдена", 1, "Добавлена", 5)
    assert load_snapshot(item)["additional_payments"]["total"] == 25
    remove_additional_payment(item, "Новая", 20)
    remove_additional_payment(item, "Нет", 999)
    assert load_snapshot(item)["additional_payments"]["total"] == 5


def test_update_key_client_found_and_missing_paths():
    item = calculation(chief_report())
    append_key_client_profit(item, "Первый", 100)
    update_key_client_profit(item, "Первый", 100, "Изменен", 200)
    update_key_client_profit(item, "Отсутствует", 1, "Добавлен", 300)
    rows = load_snapshot(item)["key_clients_profit"]["items"]
    assert [(row["client"], row["bonus"]) for row in rows] == [("Изменен", 20.0), ("Добавлен", 30.0)]
    remove_key_client_profit(item, "Не найден", 0)


def test_update_adjustment_and_missing_adjustment_paths():
    item = calculation(manager_report())
    append_adjustment(item, "profit", "bonus", 10, "Старая")
    update_adjustment(item, "profit", "bonus", 10, "Старая", "cycle", "bonus", 20, "Новая")
    report = load_snapshot(item)
    assert report["manual_adjustments"][0]["comment"] == "Новая"
    update_adjustment(item, "missing", "missing", 1, "Нет", "profit", "bonus", 2, "Добавка")
    remove_adjustment(item, "missing", "missing", 1, "Нет")


def test_non_object_json_is_rejected():
    with pytest.raises(ValueError, match="корневое значение"):
        save_snapshot_text(calculation(manager_report()), "[]")
