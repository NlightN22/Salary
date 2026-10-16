from io import BytesIO

import pytest
from fastapi import UploadFile

import salary_web.report_storage as storage
from salary_web.models import Department, Period, ReportStatus, UploadedReport
from salary_web.config import resolve_service_data_path


def make_period(db, code="b2b"):
    department = Department(code=code, name=code.upper())
    period = Period(year=2026, month=1, department=department)
    db.add(period)
    db.commit()
    return period


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("profit.xlsx", "profit"),
        ("BRAND sales.xlsx", "brand_sales"),
        ("debt.xls", "debt"),
        ("Табель №1.xlsx", "timesheet"),
        ("Цикл сделки.xlsx", "cycle"),
        ("Коммуникации.xlsx", "communications"),
        ("unknown.xlsx", None),
    ],
)
def test_detect_report_type(filename, expected):
    assert storage.detect_report_type(filename) == expected


@pytest.mark.parametrize(
    "filename",
    [".DS_Store", "~$profit.xlsx", "__init__.py", "notes.txt", "manual.pdf", ""],
)
def test_noise_files_are_ignored(filename):
    assert storage.should_ignore_upload(filename)


def test_unknown_explicit_report_type_is_rejected():
    with pytest.raises(ValueError, match="Неизвестный тип"):
        storage.validate_report_type("magic")


def test_new_upload_path_contains_department_and_period(db, tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "UPLOADS_DIR", tmp_path)
    period = make_period(db, "sales-east")
    upload = UploadFile(filename="profit.xlsx", file=BytesIO(b"content"))
    report = storage.save_uploaded_report(db, period, "profit", upload)
    path = resolve_service_data_path(report.stored_path)
    assert path.parent == tmp_path / "SALES-EAST" / "2026" / "1" / "reports"
    assert path.read_bytes() == b"content"
    assert report.file_hash


def test_reupload_replaces_single_report_record(db, tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "UPLOADS_DIR", tmp_path)
    period = make_period(db)
    storage.save_uploaded_report(db, period, "profit", UploadFile(filename="profit.xlsx", file=BytesIO(b"old")))
    report = storage.save_uploaded_report(db, period, "profit", UploadFile(filename="profit.xlsx", file=BytesIO(b"new")))
    assert db.query(UploadedReport).filter_by(period_id=period.id, report_type="profit").count() == 1
    assert resolve_service_data_path(report.stored_path).read_bytes() == b"new"


def test_timesheets_are_added_instead_of_replaced(db, tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "UPLOADS_DIR", tmp_path)
    period = make_period(db)
    for name, value in (("Табель.xlsx", b"one"), ("Табель 2.xlsx", b"two")):
        storage.save_uploaded_report(db, period, "timesheet", UploadFile(filename=name, file=BytesIO(value)))
    assert db.query(UploadedReport).filter_by(period_id=period.id, report_type="timesheet").count() == 2


def test_completeness_distinguishes_missing_errors_and_validated(db):
    period = make_period(db)
    for report_type in storage.REQUIRED_REPORT_TYPES:
        period.reports.append(UploadedReport(
            report_type=report_type,
            original_filename=f"{report_type}.xlsx",
            stored_path=f"{report_type}.xlsx",
            file_hash="hash",
            status=ReportStatus.VALIDATED.value,
        ))
    db.flush()
    result = storage.report_completeness(period)
    assert result["complete"] and result["validated"] and not result["errors"]
    period.reports[0].status = ReportStatus.ERROR.value
    period.reports[0].error_message = "поврежден"
    result = storage.report_completeness(period)
    assert not result["validated"]
    assert result["errors"][0]["message"] == "поврежден"
