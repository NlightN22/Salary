from datetime import datetime

import pandas as pd
import pytest

from parsers.brand_parser import BrandParser
from parsers.comm_parser import CommParser
from parsers.cycle_parser import CycleParser
from parsers.debt_parser import DebtParser
from parsers.profit_parser import ProfitParser
from parsers.timesheet_parser import TimesheetParser


def test_brand_all_input_and_rate_branches(capsys):
    assert BrandParser(pd.DataFrame())._is_employee("") is False
    rows = [
        ["Иванов Иван Иванович", None, None, None, None, None, None, None, None],
        [None, None, None, None, None, None, None, None, None],
        [None, None, None, "", None, None, None, None, None],
        [None, None, None, "ZIC", None, None, None, None, None],
        [None, None, None, "Лукойл", None, 1, None, 100, 1],
        [None, None, None, "Лукойл", None, 1, None, 1000, 1],
        [None, None, None, "Лукойл", None, 1, None, 3000, 1],
        [None, None, None, "Лукойл", None, 1, None, 6000, 1],
        [None, None, None, "unknown", None, 100, None, 100, 1],
        [None, None, None, "broken", None, object(), None, 1, 1],
    ]
    parser = BrandParser(pd.DataFrame(rows))
    result = parser.get_employee_kpi("Иванов Иван Иванович")
    assert result["lukoil"]["rate"] == 10 and result["other"][0]["weight"] == 0
    assert parser.get_kpi_row("Другой Другой Другой", "x")["plan"] == 0
    parser.print_employee_count(); assert "Найдено сотрудников" in capsys.readouterr().out


def test_comm_every_branch():
    df = pd.DataFrame([
        [None], [">> группа: другой"], [">> группа: Иванов Иван"],
        ["не раздел"], [">> группа: звонок"], ["завершено неудачно"],
        ["завершено неудачно (2)"], ["завершено успешно"], ["завершено успешно (3)"],
        [">> группа: Аверкиева чужая"],
    ])
    result = CommParser(df).get_employee_stats("Иванов Иван Иванович")
    assert result["звонок"] == {"total": 0, "success": 3, "failed": 2}


def test_cycle_every_branch(monkeypatch):
    with pytest.raises(ValueError):
        CycleParser(pd.DataFrame(columns=["Сделки", "Дата первичного контакта"]))
    parser = CycleParser(pd.DataFrame(columns=["x", "Дата первичного контакта", "Дата последнего изменения"]))
    assert parser.stage_col == 0
    assert parser._parse_date(datetime(2026, 1, 1)).year == 2026
    monkeypatch.setattr(pd, "to_datetime", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError()))
    assert parser._parse_date("nonsense") is None

    df = pd.DataFrame([
        [None, None, None], ["before", "01.01.2026", "02.01.2026"],
        [">> группа: Иванов Иван", None, None], [">> группа: другое (1)", None, None],
        ["skip", "01.01.2026", "02.01.2026"], [">> группа: отгрузка и доставка", None, None],
        ["bad first", None, "02.01.2026"], ["bad last", "01.01.2026", None],
        ["negative", "03.01.2026", "02.01.2026"], ["ok", "01.01.2026", "02.01.2026"],
        [">> группа: первичный контакт", None, None], ["future", "01.01.2027", None],
    ], columns=["Сделки", "Дата первичного контакта", "Дата последнего изменения"])
    result = CycleParser(df).get_cycle_data("Иванов Иван Иванович", 2026, 1)
    assert result["plan_count"] == 1 and result["fact_count"] == 0


def test_debt_every_branch():
    with pytest.raises(ValueError): DebtParser(pd.DataFrame(columns=["Просрочено"]))
    with pytest.raises(ValueError): DebtParser(pd.DataFrame(columns=["Менеджер"]))
    df = pd.DataFrame([
        [None, None, None], ["", 1, ""], ["A A A", None, ""],
        ["A A A", "bad", ""], ["A A A", 200000, "Client"],
    ], columns=["Менеджер", "Просрочено", "Контрагент"])
    parser = DebtParser(df)
    assert parser.get_employees() == {"A A A"}
    assert parser.get_data("A A A")["large_items"][0]["contractor"] == "Client"
    assert parser.get_direction_data()["large_items"][0]["contractor"] == "Client"
    empty = DebtParser(pd.DataFrame(
        [["A A A", 200000, "", "Contract", "x"]],
        columns=["Менеджер", "Просрочено", "Контрагент", "Договор контрагента", "Прочее"],
    ))
    assert empty.contract_col == 3
    assert empty.get_data("A A A")["large_items"][0]["contractor"] is None
    assert empty.get_direction_data()["large_items"][0]["contractor"] is None


def test_profit_every_branch(capsys):
    header = [None, "Менеджер", "Сумма продажи", "Доход текущий", "Рентабельность текущая"]
    rows = [header, [None, None, 1, 1, 1], [None, "", 1, 1, 1], [None, "A B", 1, 1, 1],
            [None, "A B C", None, 1, 1], [None, "X Y Z", 1, 1, 1],
            [None, "A B C", 1, "bad", "bad"], [None, "Итого", "bad", "bad", "bad"]]
    parser = ProfitParser(pd.DataFrame(rows))
    result = parser.get_income("A B C")
    assert result == {"sales": 1.0, "income": 0.0, "profitability": 0, "bonus": 0.0}
    assert parser.get_total()["sales"] == 0
    parser.print_columns(); assert "Менеджер" in capsys.readouterr().out


def test_timesheet_remaining_branches():
    df = pd.DataFrame([["Иванов И.", "bad"], ["Иванов Х.", "2"]])
    assert TimesheetParser(df).get_data("Иванов Иван Иванович")["hours"] == 0
