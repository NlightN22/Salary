from pathlib import Path

import pandas as pd
import pytest

import services.calculation_context as context_module


REQUIRED = {
    "profit": Path("profit.xlsx"),
    "brand_sales": Path("brand.xlsx"),
    "debt": Path("debt.xlsx"),
    "communications": Path("communications.xlsx"),
    "cycle": Path("cycle.xlsx"),
    "timesheet": [Path("timesheet-1.xlsx"), Path("timesheet-2.xlsx")],
}


def valid_frames():
    return {
        "profit.xlsx": pd.DataFrame([
            ["Менеджер", "Сумма продажи", "Доход текущий", "Рентабельность текущая"],
            ["Итого", 1, 1, 1],
        ]),
        "brand.xlsx": pd.DataFrame([[None] * 9]),
        "debt.xlsx": pd.DataFrame({"Менеджер": ["Иванов"], "Просрочено": [0]}),
        "communications.xlsx": pd.DataFrame([[">> Группа: пусто"]]),
        "cycle.xlsx": pd.DataFrame({
            "Сделки": [">> Группа: пусто"],
            "Дата первичного контакта": [None],
            "Дата последнего изменения": [None],
        }),
        "timesheet-1.xlsx": pd.DataFrame([["Иванов И.И.", 80]]),
        "timesheet-2.xlsx": pd.DataFrame([["Иванов И.И.", 80]]),
    }


def test_context_reports_all_missing_files():
    with pytest.raises(FileNotFoundError, match="brand, debt"):
        context_module.load_context_from_files(2026, 1, {"profit": "profit.xlsx"})


def test_context_accepts_brand_sales_alias_and_combines_timesheets(monkeypatch):
    frames = valid_frames()
    monkeypatch.setattr(context_module, "read_excel", lambda path: frames[Path(path).name])
    context = context_module.load_context_from_files("2026", "1", REQUIRED)
    assert context["year"] == 2026
    assert len(context["timesheet"].df) == 2


def test_context_rejects_short_brand_report(monkeypatch):
    frames = valid_frames()
    frames["brand.xlsx"] = pd.DataFrame([[1, 2]])
    monkeypatch.setattr(context_module, "read_excel", lambda path: frames[Path(path).name])
    with pytest.raises(ValueError, match="Brand Sales.*2 колонок"):
        context_module.load_context_from_files(2026, 1, REQUIRED)


def test_context_rejects_short_timesheet(monkeypatch):
    frames = valid_frames()
    frames["timesheet-1.xlsx"] = pd.DataFrame([[1]])
    monkeypatch.setattr(context_module, "read_excel", lambda path: frames[Path(path).name])
    with pytest.raises(ValueError, match="Табель"):
        context_module.load_context_from_files(2026, 1, REQUIRED)
