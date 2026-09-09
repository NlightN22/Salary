import pytest

import directions.b2b.manager_salary as manager_module
from directions.b2b.chief_salary import calculate_chief
from directions.b2b.config import CHIEF_EMPLOYEE


class Profit:
    def get_total(self):
        return {"sales": 1000, "income": 200, "profitability": 20}


class Brand:
    def __init__(self, other_percent=100):
        self.other_percent = other_percent

    def get_kpi_row(self, employee, name):
        return {"brand": name, "plan": 100, "fact": 100, "percent": 100}

    def get_employee_kpi(self, employee):
        return {"other": [{"brand": "В2В VegaOil", "percent": self.other_percent}]}


class Debt:
    def get_direction_data(self, threshold):
        return {"total": 1000, "large_items": []}


class Timesheet:
    def get_data(self, employee, rate):
        return {"hours": 10, "salary": 100}


@pytest.mark.parametrize(("percent", "expected"), [(1000, 120), (40, 6.4), (400, 80)])
def test_chief_special_product_branches_and_totals(percent, expected):
    context = {"profit": Profit(), "brand": Brand(percent), "debt": Debt(), "timesheet": Timesheet()}
    managers = [{"cycle": {"plan_count": 2, "fact_count": 2, "plan_days_sum": 20, "fact_days_sum": 40}}]
    report = calculate_chief(context, managers)
    assert report["other"]["calculation_percent"] == expected
    assert report["lukoil"]["bonus"] == 0
    assert report["salary_total"] == report["total_bonus"] + 100


def test_chief_handles_missing_cycle_data():
    context = {"profit": Profit(), "brand": Brand(), "debt": Debt(), "timesheet": Timesheet()}
    report = calculate_chief(context, [])
    assert report["cycle"]["bonus"] == 0


def test_chief_skips_special_product_without_configured_weight():
    class MixedBrand(Brand):
        def get_employee_kpi(self, employee):
            return {"other": [
                {"brand": "Неизвестный товар", "percent": 100},
                {"brand": "В2В VegaOil", "percent": 100},
            ]}
    context = {"profit": Profit(), "brand": MixedBrand(), "debt": Debt(), "timesheet": Timesheet()}
    assert len(calculate_chief(context, [])["other"]["items"]) == 1


def test_manager_calculation_intersects_sources_and_skips_chief(monkeypatch):
    class Employees:
        def __init__(self, values): self.values = values
        def get_employees(self): return set(self.values)
    context = {
        "profit": Employees([CHIEF_EMPLOYEE, "Иванов Иван Иванович", "Только Profit Один"]),
        "brand": Employees([CHIEF_EMPLOYEE, "Иванов Иван Иванович"]),
        "debt": object(), "communications": object(), "cycle": object(), "timesheet": object(),
        "year": 2026, "month": 1,
    }
    monkeypatch.setattr(manager_module, "build_employee_report", lambda **kwargs: {"employee": kwargs["employee"]})
    reports = manager_module.calculate_managers(context)
    assert reports == [{"employee": "Иванов Иван Иванович", "report_type": "manager"}]
