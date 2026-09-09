import pandas as pd
import pytest

from parsers.debt_parser import DebtParser
from parsers.brand_parser import BrandParser
from parsers.comm_parser import CommParser
from parsers.cycle_parser import CycleParser
from parsers.profit_parser import ProfitParser
from parsers.timesheet_parser import TimesheetParser


def profit_frame():
    return pd.DataFrame([
        ["Менеджер", "Сумма продажи", "Доход текущий", "Рентабельность текущая"],
        ["Иванов Иван Иванович", 100000.005, 20000.005, 0.2],
        ["Итого", 100000.005, 20000.005, 0.2],
    ])


def test_profit_parser_finds_employee_and_rounds_like_excel():
    parser = ProfitParser(profit_frame())
    assert parser.get_employees() == {"Иванов Иван Иванович"}
    assert parser.get_income("Иванов Иван Иванович")["sales"] == 100000.01
    assert parser.get_total()["income"] == 20000.01


def test_profit_parser_rejects_unknown_structure():
    with pytest.raises(ValueError, match="колонки Profit"):
        ProfitParser(pd.DataFrame([["не тот отчет", 1]]))


def test_profit_total_is_required():
    frame = profit_frame().iloc[:-1]
    with pytest.raises(ValueError, match="Итого"):
        ProfitParser(frame).get_total()


def test_debt_parser_returns_contractor_and_threshold_rows():
    frame = pd.DataFrame({
        "Менеджер": ["Иванов Иван Иванович", "Иванов Иван Иванович", "Другой"],
        "Наименование контрагента": ["Клиент А", "Клиент Б", "Клиент В"],
        "Просроченная задолженность": [100000, 99999.99, "ошибка"],
    })
    result = DebtParser(frame).get_data("Иванов Иван Иванович")
    assert result["total"] == pytest.approx(199999.99)
    assert result["large_items"][0]["contractor"] == "Клиент А"
    assert len(result["large_items"]) == 1


@pytest.mark.parametrize("columns", [{"Менеджер": ["Иванов"]}, {"Просрочено": [1]}])
def test_debt_parser_requires_critical_columns(columns):
    with pytest.raises(ValueError):
        DebtParser(pd.DataFrame(columns))


def test_timesheet_accepts_comma_decimal_and_multiline_cell():
    parser = TimesheetParser(pd.DataFrame([["Иванов И.И.", "160,5\nдней"]]))
    assert parser.get_data("Иванов Иван Иванович", hour_rate=10) == {
        "hours": 160.5,
        "salary": 1605.0,
    }


def test_timesheet_returns_zero_for_missing_or_invalid_employee():
    parser = TimesheetParser(pd.DataFrame([["Иванов И.И.", "bad"]]))
    assert parser.get_data("Один") == {"hours": 0, "salary": 0}
    assert parser.get_data("Петров Петр") == {"hours": 0, "salary": 0}


def brand_frame():
    rows = [
        ["Иванов Иван Иванович", None, None, None, None, None, None, None, None],
        [None, None, None, "ZIC X7", None, 100, None, 50, None],
        [None, None, None, "Лукойл", None, 1000, None, 2000, None],
        [None, None, None, "VEGA", None, 100, None, 80, None],
        [None, None, None, "Поляр", None, 100, None, 60, None],
        [None, None, None, "GSK", None, 100, None, 40, None],
    ]
    return pd.DataFrame(rows)


def test_brand_parser_calculates_all_kpi_groups():
    parser = BrandParser(brand_frame())
    assert parser.get_employees() == {"Иванов Иван Иванович"}
    result = parser.get_employee_kpi("Иванов Иван Иванович")
    assert result["zic"][0]["percent"] == 50
    assert result["lukoil"] == {"kg": 2000.0, "rate": 8, "bonus": 16000.0}
    assert {item["weight"] for item in result["other"]} == {22.5, 50.0, 27.5}
    assert result["bonus_total"] > 0


def test_brand_parser_caps_and_floors_other_kpi_ratio():
    high = brand_frame()
    high.iloc[3:, 7] = 1000
    assert BrandParser(high).get_employee_kpi("Иванов Иван Иванович")["other_bonus_total"] > 0
    low = brand_frame()
    low.iloc[3:, 7] = 0
    assert BrandParser(low).get_employee_kpi("Иванов Иван Иванович")["other_bonus_total"] == 0


def test_brand_raw_kpi_lookup_handles_missing_and_bad_numbers():
    frame = brand_frame().astype(object)
    frame.iloc[1, 5] = "bad"
    parser = BrandParser(frame)
    assert parser.get_kpi_row("Иванов Иван Иванович", "ZIC")["plan"] == 0
    assert parser.get_kpi_row("Иванов Иван Иванович", "нет такого")["fact"] == 0


def test_cycle_parser_counts_plan_and_fact_rows():
    frame = pd.DataFrame({
        "Сделки": [
            ">> Группа: Иванов Иван",
            ">> Группа: Отгрузка и доставка (2)",
            "Сделка 1",
            "Сделка 2",
            ">> Группа: Первичный контакт (1)",
            "Сделка 3",
        ],
        "Дата первичного контакта": [None, None, "01.01.2026", "2026-01-05", None, "15.01.2026"],
        "Дата последнего изменения": [None, None, "11.01.2026", "2026-01-25", None, None],
    })
    result = CycleParser(frame).get_cycle_data("Иванов Иван Иванович", 2026, 1)
    assert result["plan"] == 15
    assert result["fact"] == 16
    assert result["plan_count"] == 2
    assert result["fact_count"] == 1
    assert result["bonus"] > 0


@pytest.mark.parametrize(
    "columns",
    [
        {"Сделки": ["x"], "Дата последнего изменения": ["x"]},
        {"Сделки": ["x"], "Дата первичного контакта": ["x"]},
    ],
)
def test_cycle_parser_requires_date_columns(columns):
    with pytest.raises(ValueError, match="Не найдена колонка"):
        CycleParser(pd.DataFrame(columns))


def test_communications_parser_counts_statuses():
    frame = pd.DataFrame([
        [">> Группа: Иванов Иван"],
        [">> Группа: Звонок (5)"],
        ["Завершено успешно (3)"],
        ["Завершено неудачно (2)"],
        [">> Группа: Петров Петр"],
    ])
    result = CommParser(frame).get_employee_stats("Иванов Иван Иванович")
    assert result["звонок"] == {"total": 5, "success": 3, "failed": 2}


def test_debt_direction_data_and_missing_contractor():
    frame = pd.DataFrame({
        "Менеджер": ["А", "Б", "В"],
        "Договор контрагента": ["Д1", "Д2", "Д3"],
        "Просрочено": [100000, "bad", None],
    })
    parser = DebtParser(frame)
    assert parser.get_employees() == {"А", "Б", "В"}
    data = parser.get_direction_data()
    assert data["total"] == 100000
    assert data["large_items"][0]["contractor"] is None
    assert not data["contractor_column_found"]
    employee = parser.get_data("А")
    assert employee["large_items"][0]["contractor"] is None


def test_profit_fallback_values_and_debug_output(capsys):
    frame = profit_frame().astype(object)
    frame.iloc[1, 1:] = ["bad", "bad", "bad"]
    parser = ProfitParser(frame)
    assert parser.get_income("Иванов Иван Иванович") == {
        "sales": 0.0, "income": 0.0, "profitability": 0, "bonus": 0.0,
    }
    assert parser.get_income("Нет Такого Сотрудника") == {
        "sales": 0, "income": 0, "profitability": 0, "bonus": 0,
    }
    parser.print_columns()
    assert "Менеджер:" in capsys.readouterr().out


def test_profit_total_invalid_numbers_become_zero():
    frame = profit_frame().astype(object)
    frame.iloc[2, 1:] = ["bad", None, "bad"]
    assert ProfitParser(frame).get_total() == {"sales": 0.0, "income": 0.0, "profitability": 0.0}


def test_brand_parser_ignores_headers_unknown_and_bad_rows(capsys):
    frame = brand_frame().astype(object)
    frame.loc[len(frame)] = ["Итого", None, None, None, None, None, None, None, None]
    frame.loc[len(frame)] = [None, None, None, "Unknown", None, 0, None, 1, None]
    frame.loc[len(frame)] = [None, None, None, "Broken", None, "bad", None, "bad", None]
    parser = BrandParser(frame)
    parser.print_employee_count()
    assert "Найдено сотрудников" in capsys.readouterr().out
    assert parser.get_employee_kpi("Другой Другой Другой")["bonus_total"] == 0


def test_cycle_date_variants_invalid_and_zero_fact():
    parser = CycleParser(pd.DataFrame({
        "Сделки": [">> Группа: Иванов Иван", ">> Группа: Отгрузка и доставка", "Сделка"],
        "Дата первичного контакта": [None, None, "bad-date"],
        "Дата последнего изменения": [None, None, "bad-date"],
    }))
    assert parser._parse_date(None) is None
    assert parser._parse_date("") is None
    assert parser._parse_date("01.01.2026 12:00:00").year == 2026
    assert parser._parse_date("2026-01-01 12:00:00").year == 2026
    result = parser.get_cycle_data("Иванов Иван Иванович", 2026, 1)
    assert result["fact"] == 0 and result["bonus"] == 0
