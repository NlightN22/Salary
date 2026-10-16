from io import BytesIO

import pytest
from fastapi import UploadFile

from salary_web.auth import make_session_token
from salary_web.models import Calculation, AdditionalPayment, Employee
from salary_web.snapshot_editor import save_snapshot, generate_pdf_for_calculation
from salary_web.config import period_storage_dir, resolve_service_data_path
from tests.test_extended_boundaries import scoped_client  # noqa: F401


def test_delete_one_leaves_other_calculations_and_sources(scoped_client, db, tmp_path, monkeypatch):
    import salary_web.snapshot_editor as editor
    import salary_web.report_storage as storage
    client, period, _, _, user, _ = scoped_client
    client.cookies.set("salary_user", make_session_token(user.id))
    monkeypatch.setattr(editor, "GENERATED_DIR", tmp_path / "generated")
    monkeypatch.setattr(storage, "UPLOADS_DIR", tmp_path / "uploads")
    report = storage.save_uploaded_report(db, period, "profit", UploadFile(filename="profit.xlsx", file=BytesIO(b"source")))
    source = resolve_service_data_path(report.stored_path)
    calc = Calculation(period=period, employee=Employee(full_name="Delete Me"))
    other = Calculation(period=period, employee=Employee(full_name="Keep Me"))
    for row in (calc, other):
        save_snapshot(row, {"report_type": "manual", "employee": row.employee.full_name})
        db.add(row)
    db.commit()
    db.add(AdditionalPayment(period_id=period.id, employee_id=calc.employee_id, calculation_id=calc.id, title="Test", amount=1))
    pdf = generate_pdf_for_calculation(db, calc)
    other_pdf = generate_pdf_for_calculation(db, other)
    db.commit()
    calc_id = calc.id
    url = f"/calculations/{calc_id}/delete"
    user.is_admin = 0; db.commit()
    assert client.post(url).status_code == 403
    assert pdf.exists()
    user.is_admin = 1; db.commit()
    from salary_web.app import period_url
    page = client.get(period_url(period))
    assert url in page.text and "Удалить все расчеты" in page.text
    response = client.post(url)
    assert response.status_code == 303
    assert response.headers["location"].endswith("#calculations")
    assert not pdf.exists() and source.exists() and other_pdf.exists()
    assert db.query(Calculation).filter_by(id=calc_id).first() is None
    assert db.query(AdditionalPayment).filter_by(calculation_id=calc_id).count() == 0
    assert client.post(url).status_code == 404
    assert client.post(f"/calculations/{other.id}/delete").status_code == 303
    assert source.exists()


def test_empty_parent_cleanup_stops_at_data_root(tmp_path, monkeypatch):
    import salary_web.app as web
    monkeypatch.setattr(web, "GENERATED_DIR", tmp_path / "generated")
    monkeypatch.setattr(web, "UPLOADS_DIR", tmp_path / "uploads")
    child = tmp_path / "periods" / "Department"
    child.mkdir(parents=True)
    web._remove_empty_parents(child)
    assert tmp_path.exists() and not child.exists()
