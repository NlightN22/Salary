"""Calculation of B2B manager salary reports. Rendering is deliberately separate."""

from directions.b2b.config import CHIEF_EMPLOYEE, DEPARTMENT_NAME
from services.calculation_context import load_context
from services.report_builder import build_employee_report
from services.report_io import save_report


def calculate_managers(context):
    employees = sorted(
        context["profit"].get_employees().intersection(context["brand"].get_employees())
    )
    reports = []
    for employee in employees:
        if employee == CHIEF_EMPLOYEE:
            continue
        report = build_employee_report(
            employee=employee,
            profit_parser=context["profit"],
            brand_parser=context["brand"],
            debt_parser=context["debt"],
            comm_parser=context["communications"],
            cycle_parser=context["cycle"],
            timesheet_parser=context["timesheet"],
            year=context["year"],
            month=context["month"],
        )
        report["report_type"] = "manager"
        reports.append(report)
    return reports


def main():
    context = load_context(DEPARTMENT_NAME)
    for report in calculate_managers(context):
        path = save_report(report, context["year"], context["month"], DEPARTMENT_NAME)
        print(f"Создан JSON менеджера: {path}")


if __name__ == "__main__":  # pragma: no cover - exercised as a process entry point
    main()
