from pathlib import Path

from sqlalchemy.orm import Session

from parsers.excel_reader import read_excel
from services.calculation_context import load_context_from_files
from salary_web.config import REQUIRED_REPORT_TYPES, resolve_service_data_path
from salary_web.models import Period, PeriodStatus, ReportStatus
from salary_web.report_storage import report_completeness, update_period_status


def validate_period_reports(db: Session, period: Period) -> dict[str, object]:
    completeness = report_completeness(period)
    if not completeness["complete"]:
        update_period_status(db, period)
        return report_completeness(period)

    _clear_validation_errors(period)
    files = _period_files(period)

    has_file_errors = False
    for report in period.reports:
        if report.report_type not in REQUIRED_REPORT_TYPES:
            continue
        try:
            read_excel(resolve_service_data_path(report.stored_path))
        except Exception as error:
            report.status = ReportStatus.ERROR.value
            report.error_message = str(error)
            has_file_errors = True

    if has_file_errors:
        period.status = PeriodStatus.REPORT_ERRORS.value
        db.flush()
        return report_completeness(period)

    try:
        load_context_from_files(period.year, period.month, files)
    except Exception as error:
        message = f"Ошибка проверки состава отчетов: {error}"
        for report in period.reports:
            if report.report_type in REQUIRED_REPORT_TYPES:
                report.status = ReportStatus.ERROR.value
                report.error_message = message
        period.status = PeriodStatus.REPORT_ERRORS.value
        db.flush()
        return report_completeness(period)

    for report in period.reports:
        if report.report_type in REQUIRED_REPORT_TYPES:
            report.status = ReportStatus.VALIDATED.value
            report.error_message = None
    period.status = PeriodStatus.DATA_PARSED.value
    db.flush()
    return report_completeness(period)


def _clear_validation_errors(period: Period) -> None:
    for report in period.reports:
        if report.report_type in REQUIRED_REPORT_TYPES:
            report.status = ReportStatus.UPLOADED.value
            report.error_message = None


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
