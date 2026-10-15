import hashlib
import uuid
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy.orm import Session

from salary_web.config import (
    REPORT_TYPES,
    REQUIRED_REPORT_TYPES,
    UPLOADS_DIR,
    period_storage_dir,
    stored_service_data_path,
)
from salary_web.models import Period, PeriodStatus, ReportStatus, UploadedReport


def validate_report_type(report_type: str) -> None:
    if report_type not in REPORT_TYPES:
        allowed = ", ".join(sorted(REPORT_TYPES))
        raise ValueError(f"Неизвестный тип отчета: {report_type}. Доступно: {allowed}")


def detect_report_type(filename: str) -> str | None:
    name = filename.lower()
    if should_ignore_upload(filename):
        return None
    if "profit" in name:
        return "profit"
    if "brand" in name:
        return "brand_sales"
    if "debt" in name:
        return "debt"
    if "табель" in name:
        return "timesheet"
    if "цикл" in name:
        return "cycle"
    if "коммуникации" in name:
        return "communications"
    return None


def should_ignore_upload(filename: str) -> bool:
    name = Path(filename or "").name.lower()
    if not name:
        return True
    if name.startswith(".") or name.startswith("~$"):
        return True
    if name in {"__init__.py", "init.py", "thumbs.db", ".ds_store"}:
        return True
    if name.endswith((".py", ".pyc", ".txt", ".md", ".json", ".pdf", ".docx")):
        return True
    return False


def period_upload_dir(period: Period) -> Path:
    return period_storage_dir(UPLOADS_DIR, period)


def save_uploaded_report(
    db: Session,
    period: Period,
    report_type: str,
    upload: UploadFile,
) -> UploadedReport:
    validate_report_type(report_type)

    target_dir = period_upload_dir(period)
    target_dir.mkdir(parents=True, exist_ok=True)

    reports = db.query(UploadedReport).filter(
        UploadedReport.period_id == period.id,
        UploadedReport.report_type == report_type,
    )
    if report_type == "timesheet":
        reports = reports.filter(UploadedReport.original_filename == upload.filename)
    matches = reports.order_by(UploadedReport.id.desc()).all()
    report = matches[0] if matches else None
    # Retire old duplicate rows created by earlier versions on re-upload.
    for duplicate in matches[1:]:
        db.delete(duplicate)
    suffix = Path(upload.filename or "").suffix
    filename = (f"timesheet_{uuid.uuid4().hex}{suffix}" if report_type == "timesheet"
                else f"{report_type}{suffix}")
    target_path = target_dir / filename

    hasher = hashlib.sha256()
    with target_path.open("wb") as output:
        while chunk := upload.file.read(1024 * 1024):
            hasher.update(chunk)
            output.write(chunk)

    file_hash = hasher.hexdigest()

    if report is None:
        report = UploadedReport(
            period_id=period.id,
            report_type=report_type,
            original_filename=upload.filename or filename,
            stored_path=stored_service_data_path(target_path),
            file_hash=file_hash,
            status=ReportStatus.UPLOADED.value,
        )
        db.add(report)
    else:
        report.original_filename = upload.filename or filename
        report.stored_path = stored_service_data_path(target_path)
        report.file_hash = file_hash
        report.status = ReportStatus.UPLOADED.value
        report.error_message = None

    db.flush()
    db.expire(period, ["reports"])
    update_period_status(db, period)
    return report


def save_uploaded_reports_batch(
    db: Session,
    period: Period,
    uploads: list[UploadFile],
) -> list[UploadedReport]:
    saved_reports = []
    ignored_files = []
    for upload in uploads:
        filename = upload.filename or "без имени"
        if should_ignore_upload(filename):
            ignored_files.append(filename)
            continue
        report_type = detect_report_type(filename)
        if not report_type:
            ignored_files.append(filename)
            continue
        saved_reports.append(save_uploaded_report(db, period, report_type, upload))

    db.flush()
    db.expire(period, ["reports"])
    update_period_status(db, period)
    return saved_reports


def report_completeness(period: Period) -> dict[str, object]:
    uploaded = {report.report_type for report in period.reports}
    required = set(REQUIRED_REPORT_TYPES)
    errors = [
        {
            "report_type": report.report_type,
            "filename": report.original_filename,
            "message": report.error_message or "Ошибка проверки отчета",
        }
        for report in period.reports
        if report.status == ReportStatus.ERROR.value
    ]
    uploaded_required_reports = [
        report for report in period.reports if report.report_type in required
    ]
    validated = bool(uploaded_required_reports) and all(
        report.status == ReportStatus.VALIDATED.value
        for report in uploaded_required_reports
    )
    return {
        "required": sorted(required),
        "uploaded": sorted(uploaded),
        "missing": sorted(required - uploaded),
        "complete": required.issubset(uploaded),
        "validated": validated and required.issubset(uploaded) and not errors,
        "errors": errors,
    }


def update_period_status(db: Session, period: Period) -> None:
    completeness = report_completeness(period)
    period.status = (
        PeriodStatus.DATA_PARSED.value
        if completeness["validated"]
        else PeriodStatus.REPORT_ERRORS.value
        if completeness["errors"]
        else PeriodStatus.READY_TO_CALCULATE.value
        if completeness["complete"]
        else PeriodStatus.MISSING_REPORTS.value
    )
    db.flush()
