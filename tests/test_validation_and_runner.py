import json
from pathlib import Path

import pytest

import salary_web.calculation_runner as runner
import salary_web.report_validation as validation
import salary_web.snapshot_editor as editor
from salary_web.models import (
    AdditionalPayment,
    Calculation,
    Department,
    Employee,
    Period,
    ReportStatus,
    UploadedReport,
)


def complete_period(db, tmp_path):
    department = Department(code="b2b", name="B2B")
    period = Period(year=2026, month=1, department=department)
    for report_type in runner.REQUIRED_REPORT_TYPES:
        path = tmp_path / f"{report_type}.xlsx"
        path.write_bytes(b"placeholder")
        period.reports.append(UploadedReport(
            report_type=report_type,
            original_filename=path.name,
            stored_path=str(path),
            file_hash="hash",
            status=ReportStatus.VALIDATED.value,
        ))
    db.add(period)
    db.commit()
    return period


def test_validation_stops_when_reports_are_missing(db):
    period = Period(year=2026, month=1, department=Department(code="x", name="X"))
    db.add(period)
    db.commit()
    result = validation.validate_period_reports(db, period)
    assert not result["complete"]
    assert len(result["missing"]) == len(runner.REQUIRED_REPORT_TYPES)


def test_validation_marks_only_unreadable_report_as_error(db, tmp_path, monkeypatch):
    period = complete_period(db, tmp_path)

    def fake_read(path):
        if "debt" in Path(path).name:
            raise ValueError("поврежденный файл")
        return object()

    monkeypatch.setattr(validation, "read_excel", fake_read)
    result = validation.validate_period_reports(db, period)
    assert not result["validated"]
    assert result["errors"] == [{
        "report_type": "debt",
        "filename": "debt.xlsx",
        "message": "поврежденный файл",
    }]


def test_validation_reports_structural_error_for_all_sources(db, tmp_path, monkeypatch):
    period = complete_period(db, tmp_path)
    monkeypatch.setattr(validation, "read_excel", lambda path: object())
    monkeypatch.setattr(
        validation,
        "load_context_from_files",
        lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("нет колонки Менеджер")),
    )
    result = validation.validate_period_reports(db, period)
    assert len(result["errors"]) == len(runner.REQUIRED_REPORT_TYPES)
    assert all("нет колонки Менеджер" in item["message"] for item in result["errors"])


def test_validation_success_marks_all_reports(db, tmp_path, monkeypatch):
    period = complete_period(db, tmp_path)
    monkeypatch.setattr(validation, "read_excel", lambda path: object())
    monkeypatch.setattr(validation, "load_context_from_files", lambda *args, **kwargs: {})
    result = validation.validate_period_reports(db, period)
    assert result["validated"]
    assert {report.status for report in period.reports} == {ReportStatus.VALIDATED.value}


def minimal_manager():
    return {"employee": "Иванов Иван Иванович", "report_type": "manager", "value": 1}


def minimal_chief():
    return {"employee": "Руководитель Роман Олегович", "report_type": "chief", "value": 2}


def test_period_calculation_stores_snapshot_only_in_database(db, tmp_path, monkeypatch):
    period = complete_period(db, tmp_path)
    monkeypatch.setattr(runner, "load_context_from_files", lambda *args, **kwargs: {"context": True})
    monkeypatch.setattr(runner, "calculate_managers", lambda context: [minimal_manager()])
    monkeypatch.setattr(runner, "calculate_chief", lambda context, reports: minimal_chief())
    calculations = runner.calculate_period(db, period)
    db.commit()

    assert len(calculations) == 2
    assert json.loads(calculations[0].snapshot_json)["value"] == 1
    assert not list(tmp_path.rglob("*.json"))


def test_recalculation_replaces_snapshot_and_clears_manual_rows(db, tmp_path, monkeypatch):
    period = complete_period(db, tmp_path)
    state = {"value": 1}
    monkeypatch.setattr(runner, "load_context_from_files", lambda *args, **kwargs: {})
    monkeypatch.setattr(
        runner,
        "calculate_managers",
        lambda context: [{**minimal_manager(), "value": state["value"]}],
    )
    monkeypatch.setattr(runner, "calculate_chief", lambda context, reports: minimal_chief())
    calculation = runner.calculate_period(db, period)[0]
    db.commit()
    db.add(AdditionalPayment(
        period_id=period.id,
        employee_id=calculation.employee_id,
        calculation_id=calculation.id,
        title="old",
        amount=1,
    ))
    db.commit()
    state["value"] = 9
    updated = runner.calculate_period(db, period)[0]
    db.commit()
    assert json.loads(updated.snapshot_json)["value"] == 9
    assert db.query(AdditionalPayment).filter_by(calculation_id=updated.id).count() == 0


def test_calculation_requires_complete_and_validated_reports(db):
    period = Period(year=2026, month=1, department=Department(code="b2b", name="B2B"))
    db.add(period)
    db.commit()
    with pytest.raises(ValueError, match="Не хватает"):
        runner.calculate_period(db, period)


def test_calculation_rejects_unconfigured_department_before_reading_reports(db):
    period = Period(year=2026, month=1, department=Department(code="north", name="Северный отдел"))
    db.add(period)
    db.commit()
    with pytest.raises(ValueError, match="Северный отдел.*модуль не настроен"):
        runner.calculate_period(db, period)


def test_pdf_path_is_partitioned_by_department(db, tmp_path, monkeypatch):
    department = Department(code="north sales", name="North")
    period = Period(year=2026, month=4, department=department)
    employee = Employee(full_name="Иванов Иван Иванович")
    report = {
        "report_type": "manager",
        "employee": employee.full_name,
        "profit": {}, "brand": {}, "debt": {}, "cycle": {},
        "communications": {}, "timesheet": {}, "additional_payments": {},
    }
    calculation = Calculation(period=period, employee=employee, snapshot_json=json.dumps(report, ensure_ascii=False))
    db.add(calculation)
    db.commit()
    monkeypatch.setattr(editor, "GENERATED_DIR", tmp_path)

    def fake_generate(path, *args, **kwargs):
        path.write_bytes(b"%PDF-test")

    monkeypatch.setattr(editor, "generate_pdf", fake_generate)
    path = editor.generate_pdf_for_calculation(db, calculation)
    assert path.parent == tmp_path.parent / "periods" / f"North_{department.id}" / "2026" / "04_Апрель" / tmp_path.name
    assert path.read_bytes().startswith(b"%PDF")
