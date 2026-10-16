"""Build one JSON calculation file per employee for the latest period."""

from directions.b2b.chief_salary import calculate_chief
from directions.b2b.config import DEPARTMENT_NAME
from directions.b2b.manager_salary import calculate_managers
from services.calculation_context import load_context
from services.report_io import save_report


def main():
    context = load_context(DEPARTMENT_NAME)
    managers = calculate_managers(context)
    reports = [*managers, calculate_chief(context, managers)]
    for report in reports:
        path = save_report(report, context["year"], context["month"], DEPARTMENT_NAME)
        print(f"Создан: {path}")
    print(f"JSON-файлов создано: {len(reports)}")


if __name__ == "__main__":  # pragma: no cover - exercised as a process entry point
    main()
