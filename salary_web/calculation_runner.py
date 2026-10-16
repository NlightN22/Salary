import json
from pathlib import Path

from sqlalchemy.orm import Session

from directions.b2b.chief_salary import calculate_chief
from directions.b2b.config import DEPARTMENT_CODE
from directions.b2b.manager_salary import calculate_managers
from services.calculation_context import load_context_from_files
from salary_web.config import REQUIRED_REPORT_TYPES, resolve_service_data_path
from salary_web.models import (
    AdditionalPayment,
    Calculation,
    CalculationAdjustment,
    Employee,
    Period,
    PeriodStatus,
)
from salary_web.report_storage import report_completeness


def calculate_period(db: Session, period: Period, employee_name: str | None = None) -> list[Calculation]:
    if period.department is None or period.department.code != DEPARTMENT_CODE:
        department = period.department.name if period.department else "неизвестное подразделение"
        raise ValueError(f"Для подразделения «{department}» расчетный модуль не настроен")
    completeness = report_completeness(period)
    if not completeness["complete"]:
        missing = ", ".join(completeness["missing"])
        raise ValueError(f"Не хватает обязательных отчетов: {missing}")
    if not completeness["validated"]:
        raise ValueError("Нельзя запустить расчет: отчеты еще не прошли проверку")

    files = _period_files(period)
    context = load_context_from_files(period.year, period.month, files)

    manager_reports = calculate_managers(context)
    reports = [*manager_reports, calculate_chief(context, manager_reports)]
    if employee_name is not None:
        reports = [report for report in reports if report["employee"] == employee_name]
        if not reports:
            raise ValueError("Сотрудник отсутствует в исходных отчетах. Прежний расчет сохранен.")

    calculations = []
    for report in reports:
        employee = _get_or_create_employee(
            db,
            full_name=report["employee"],
            role=report.get("report_type", "manager"),
        )
        snapshot_json = json.dumps(
            report,
            ensure_ascii=False,
            indent=2,
            allow_nan=False,
        )
        calculation = (
            db.query(Calculation)
            .filter(
                Calculation.period_id == period.id,
                Calculation.employee_id == employee.id,
            )
            .one_or_none()
        )
        if calculation is None:
            calculation = Calculation(
                period_id=period.id,
                employee_id=employee.id,
            )
            db.add(calculation)
        elif calculation.snapshot_json and json.loads(calculation.snapshot_json).get("report_type") == "manual":
            calculations.append(calculation)
            continue

        calculation.status = "calculated"
        calculation.snapshot_json = snapshot_json
        calculation.pdf_path = None
        if calculation.id is not None:
            db.query(AdditionalPayment).filter(
                AdditionalPayment.calculation_id == calculation.id
            ).delete()
            db.query(CalculationAdjustment).filter(
                CalculationAdjustment.calculation_id == calculation.id
            ).delete()
        calculations.append(calculation)

    period.status = PeriodStatus.CALCULATION_CREATED.value
    db.flush()
    return calculations


def _period_files(period: Period) -> dict[str, Path | list[Path]]:
    reports_by_type: dict[str, list[Path]] = {}
    for report in period.reports:
        reports_by_type.setdefault(report.report_type, []).append(
            resolve_service_data_path(report.stored_path)
        )

    files: dict[str, Path | list[Path]] = {}
    for report_type in REQUIRED_REPORT_TYPES:
        paths = reports_by_type.get(report_type, [])
        if not paths:
            continue
        if report_type == "timesheet":
            files[report_type] = paths
        else:
            files[report_type] = paths[-1]
    return files


def _get_or_create_employee(db: Session, full_name: str, role: str) -> Employee:
    employee = db.query(Employee).filter(Employee.full_name == full_name).one_or_none()
    if employee is None:
        employee = Employee(full_name=full_name, role=role)
        db.add(employee)
        db.flush()
    else:
        employee.role = role
    return employee
