from io import BytesIO
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from fastapi import UploadFile

from salary_web.auth import make_session_token
from salary_web.models import Calculation, Employee
from salary_web.snapshot_editor import load_snapshot, save_snapshot, generate_pdf_for_calculation
from tests.test_extended_boundaries import scoped_client  # noqa: F401


@pytest.mark.parametrize("operation", ["commit", "flush"])
def test_manual_duplicate_race(scoped_client, db, monkeypatch, operation):
    from salary_web.app import create_manual_calculation, department_url_name
    from tests.test_rounding_and_auth import request_with_cookie
    _, period, _, _, user, _ = scoped_client
    request = request_with_cookie(make_session_token(user.id))
    request.scope["path_params"] = {"department_name": department_url_name(period.department)}
    def fail_commit():
        raise IntegrityError("duplicate", {}, Exception("duplicate"))
    monkeypatch.setattr(db, operation, fail_commit)
    with pytest.raises(HTTPException) as error:
        create_manual_calculation(period.year, period.month, request, "New Employee", db)
    assert error.value.status_code == 409
    assert db.query(Employee).filter_by(full_name="New Employee").count() == 0


def test_storage_without_persisted_department(tmp_path):
    from salary_web.config import period_storage_dir
    assert period_storage_dir(tmp_path, SimpleNamespace(year=2026, month=1)) == tmp_path.parent / "periods" / "default" / "2026" / "01_Январь" / tmp_path.name


def test_manual_web_lifecycle(scoped_client, db, tmp_path, monkeypatch):
    import salary_web.snapshot_editor as editor
    client, period, _, _, user, _ = scoped_client
    client.cookies.set("salary_user", make_session_token(user.id))
    from salary_web.app import period_url
    url = period_url(period) + "/manual-calculations"
    assert client.post(url, data={"employee_name": "  "}).status_code == 400
    result = client.post(url, data={"employee_name": "  Иванов   Иван Иванович "})
    assert result.status_code == 303, result.text
    location = result.headers["location"]
    calculation = db.get(Calculation, int(location.rsplit("/", 1)[1]))
    assert load_snapshot(calculation)["salary_total"] == 0
    assert client.post(url, data={"employee_name": "Иванов Иван Иванович"}).status_code == 409
    page = client.get(location)
    assert page.status_code == 200, page.text
    assert "Название выплаты" in page.text
    comment = "Ждут оплат от государства. Будем взыскивать неустойку. " * 5
    for amount in ("10000.25", "-500.10"):
        response = client.post(location + "/additional-payments", data={
            "title": "Премия <тест>", "amount": amount, "comment": comment})
        assert response.status_code == 303, response.text
    db.refresh(calculation)
    assert load_snapshot(calculation)["salary_total"] == 9500.15
    assert "9 500.15" in client.get(location).text
    monkeypatch.setattr(editor, "GENERATED_DIR", tmp_path)
    assert client.post(location + "/pdf").status_code == 303
    pdf = client.get(location + "/pdf/download")
    assert pdf.status_code == 200
    assert pdf.content.startswith(b"%PDF")
    assert len(pdf.content) > 10000
    payment = calculation.additional_payments[0]
    assert client.post(location + f"/additional-payments/{payment.id}/update", data={
        "title": "Оклад", "amount": "20000", "comment": "Изменено"}).status_code == 303
    db.refresh(calculation)
    assert load_snapshot(calculation)["salary_total"] == 19499.9
    assert calculation.pdf_path is None
    assert client.post(location + f"/additional-payments/{payment.id}/delete").status_code == 303
    db.refresh(calculation)
    assert load_snapshot(calculation)["salary_total"] == -500.1
    user.is_admin = 0
    db.commit()
    assert client.post(url, data={"employee_name": "Forbidden"}).status_code == 403


def test_manual_survives_recalculation_and_upload(db, tmp_path, monkeypatch):
    import salary_web.calculation_runner as runner
    import salary_web.snapshot_editor as editor
    import salary_web.report_storage as storage
    from salary_web.app import remove_period_calculations, upload_report_to_period_api
    from tests.test_validation_and_runner import complete_period, minimal_manager, minimal_chief
    period = complete_period(db, tmp_path)
    report = minimal_manager()
    manual = Calculation(period=period, employee=Employee(full_name=report["employee"]))
    save_snapshot(manual, {"report_type": "manual", "employee": report["employee"]})
    db.add(manual); db.commit()
    monkeypatch.setattr(runner, "load_context_from_files", lambda *args: {})
    monkeypatch.setattr(runner, "calculate_managers", lambda context: [report])
    monkeypatch.setattr(runner, "calculate_chief", lambda context, reports: minimal_chief())
    runner.calculate_period(db, period)
    db.commit()
    assert load_snapshot(manual)["report_type"] == "manual"
    monkeypatch.setattr(editor, "GENERATED_DIR", tmp_path / "generated")
    path = generate_pdf_for_calculation(db, manual)
    monkeypatch.setattr(storage, "UPLOADS_DIR", tmp_path / "uploads")
    upload_report_to_period_api(db, period, "profit", UploadFile(filename="profit.xlsx", file=BytesIO(b"bad")))
    db.refresh(manual)
    assert path.exists() and load_snapshot(manual)["report_type"] == "manual"
    assert db.query(Calculation).filter_by(period_id=period.id).count() == 1
    remove_period_calculations(db, period)
    db.commit()
    assert db.query(Calculation).filter_by(period_id=period.id).count() == 0
    assert not path.exists()
