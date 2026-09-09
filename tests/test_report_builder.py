from services.report_builder import build_employee_report


class Profit:
    def get_income(self, employee):
        return {"sales": 1000, "income": 200, "profitability": 20, "bonus": 10}


class Brand:
    def get_employee_kpi(self, employee):
        return {
            "zic": [], "other": [], "lukoil": None,
            "zic_bonus_total": 20, "lukoil_bonus": 0, "other_bonus_total": 30,
        }


class Debt:
    def get_data(self, employee):
        return {
            "total": 100, "indicator": 5, "threshold": 100000,
            "large_items": [], "contractor_column_found": True,
        }


class Communications:
    def get_employee_stats(self, employee):
        return {"звонок": {"total": 1, "success": 1, "failed": 0}}


class Cycle:
    def get_cycle_data(self, employee, year, month):
        return {"bonus": 40, "plan": 10, "fact": 20}


class Timesheet:
    def get_data(self, employee):
        return {"hours": 160, "salary": 1000}


def test_employee_report_contains_all_sections_and_consistent_totals():
    report = build_employee_report(
        "Иванов Иван Иванович", Profit(), Brand(), Debt(), Communications(),
        Cycle(), Timesheet(), 2026, 1,
    )
    assert report["debt"]["ratio"] == 10
    assert report["total_bonus"] == 95
    assert report["salary_total"] == 1095
    assert len(report["additional_payments"]["items"]) == 2


def test_zero_sales_does_not_divide_by_zero():
    profit = Profit()
    profit.get_income = lambda employee: {"sales": 0, "income": 0, "profitability": 0, "bonus": 0}
    report = build_employee_report(
        "Иванов Иван Иванович", profit, Brand(), Debt(), Communications(),
        Cycle(), Timesheet(), 2026, 1,
    )
    assert report["debt"]["ratio"] == 0
