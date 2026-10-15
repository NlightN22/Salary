import json
import uuid

from fastapi.testclient import TestClient

from salary_web.app import app
from salary_web.database import SessionLocal
from salary_web.models import ApiKey, Calculation, Department, Employee, Period, User
from tests.test_generators import manager_report
from tests.test_generators import chief_report


def test_complete_web_admin_and_manual_entry_workflow():
    marker = uuid.uuid4().hex[:8]
    year = 2100 + int(marker[:2], 16)
    with TestClient(app, follow_redirects=False) as client:
        assert client.get("/").headers["location"] == "/login"
        assert client.get("/periods").status_code == 303
        assert client.post("/login", data={"username": "bad", "password": "bad"}).status_code == 401
        login = client.post("/login", data={"username": "admin", "password": "test-admin-password"})
        assert login.status_code == 303
        assert client.get("/login").status_code == 303
        assert client.get("/periods").status_code == 200
        assert client.get("/api-docs").status_code == 200
        assert client.get("/admin").status_code == 200

        code = f"dept-{marker}"
        assert client.post("/admin/departments", data={"code": code, "name": "Тестовый отдел"}).status_code == 303
        assert client.post("/admin/departments", data={"code": code, "name": "Дубль"}).status_code == 400
        db = SessionLocal()
        department = db.query(Department).filter_by(code=code).one()
        department_id = department.id
        db.close()

        username = f"user-{marker}"
        create_user = client.post("/admin/users", data={
            "username": username, "password": "old", "full_name": "Тестовый пользователь",
            "is_admin": "0", "department_ids": str(department_id),
        })
        assert create_user.status_code == 303
        assert client.post("/admin/users", data={"username": username, "password": "x"}).status_code == 400
        db = SessionLocal(); user = db.query(User).filter_by(username=username).one(); user_id = user.id; db.close()
        assert client.post(f"/admin/users/{user_id}/password", data={"password": "new"}).status_code == 303
        assert client.post(f"/admin/users/{user_id}/profile", data={"username": username + "x", "full_name": "Новое имя"}).status_code == 303
        assert client.post(f"/admin/users/{user_id}/departments", data={
            "department_ids": str(department_id), "is_admin": "0", "is_active": "1",
        }).status_code == 303
        assert client.post("/admin/users/999999/password", data={"password": "x"}).status_code == 404
        assert client.post("/admin/users/999999/profile", data={"username": "x"}).status_code == 404
        assert client.post("/admin/users/999999/departments", data={}).status_code == 404

        create_key = client.post("/admin/api-keys", data={"name": f"key-{marker}", "department_ids": str(department_id)})
        assert create_key.status_code == 200
        db = SessionLocal(); api_key = db.query(ApiKey).filter_by(name=f"key-{marker}").one(); api_key_id = api_key.id; db.close()
        assert client.post(f"/admin/api-keys/{api_key_id}/rights", data={
            "name": "updated", "department_ids": str(department_id), "is_active": "1",
        }).status_code == 303
        assert client.post("/admin/api-keys/999999/rights", data={"name": "x"}).status_code == 404

        create_period = client.post("/periods", data={"year": year, "month": 1, "department_id": department_id})
        assert create_period.status_code == 303
        db = SessionLocal(); period = db.query(Period).filter_by(year=year, month=1, department_id=department_id).one(); period_id = period.id; db.close()
        assert client.get(f"/periods/{year}/1").status_code == 200
        assert client.get(f"/periods/{period_id}").status_code == 303
        assert client.post(f"/periods/{year}/1/validate").status_code == 303
        assert client.post(f"/periods/{year}/1/calculate").status_code == 400
        assert client.post(f"/periods/{year}/1/pdf").status_code == 400
        assert client.post(f"/periods/{year}/1/calculations/delete").status_code == 303

        upload = client.post(
            f"/periods/{year}/1/reports",
            files=[("files", ("unknown.xlsx", b"not excel", "application/octet-stream"))],
        )
        assert upload.status_code == 303

        report = manager_report(); report["report_type"] = "manager"; report["salary_total"] = 70000
        db = SessionLocal()
        period = db.get(Period, period_id)
        employee = Employee(full_name=f"Сотрудник {marker} Тестович")
        report["employee"] = employee.full_name
        calculation = Calculation(period=period, employee=employee, snapshot_json=json.dumps(report, ensure_ascii=False))
        db.add(calculation); db.commit(); calculation_id = calculation.id; db.close()

        assert client.get(f"/calculations/{calculation_id}").status_code == 200
        payment = client.post(f"/calculations/{calculation_id}/additional-payments", data={
            "title": "Доплата", "amount": "100", "comment": "Комментарий",
        })
        assert payment.status_code == 303
        db = SessionLocal(); calculation = db.get(Calculation, calculation_id); payment_id = calculation.additional_payments[0].id; db.close()
        assert client.post(f"/calculations/{calculation_id}/additional-payments/{payment_id}/update", data={
            "title": "Новая доплата", "amount": "200", "comment": "Новый комментарий",
        }).status_code == 303

        adjustment = client.post(f"/calculations/{calculation_id}/adjustments", data={
            "section_code": "profit", "adjustment_type": "bonus", "amount": "50", "comment": "Правка",
        })
        assert adjustment.status_code == 303
        db = SessionLocal(); calculation = db.get(Calculation, calculation_id); adjustment_id = calculation.adjustments[0].id; db.close()
        assert client.post(f"/calculations/{calculation_id}/adjustments/{adjustment_id}/update", data={
            "amount": "60", "comment": "Обновлено",
        }).status_code == 303
        assert client.post(f"/calculations/{calculation_id}/debt-large-items/0/comment", data={"comment": "Оплатят"}).status_code == 303
        assert client.post(f"/calculations/{calculation_id}/debt-large-items/99/comment", data={"comment": "x"}).status_code == 404
        assert client.post(f"/calculations/{calculation_id}/pdf").status_code == 303
        assert client.get(f"/calculations/{calculation_id}/pdf/download").status_code == 200

        assert client.get(f"/api/periods/{year}/1").status_code == 200
        assert client.get(f"/api/periods/{year}/1/calculations").status_code == 200
        assert client.get(f"/api/periods/{year}/1/calculations/{calculation_id}").status_code == 200
        assert client.get(f"/api/calculations/{calculation_id}").status_code == 200
        assert client.post(f"/api/calculations/{calculation_id}/pdf").status_code == 200
        assert client.get(f"/api/calculations/{calculation_id}/pdf/download").status_code == 200

        assert client.post(f"/calculations/{calculation_id}/adjustments/{adjustment_id}/delete").status_code == 303
        assert client.post(f"/calculations/{calculation_id}/additional-payments/{payment_id}/delete").status_code == 303
        assert client.post(f"/admin/api-keys/{api_key_id}/delete").status_code == 303
        assert client.post(f"/admin/users/{user_id}/delete").status_code == 303
        assert client.post(f"/periods/{period_id}/delete").status_code == 303
        assert client.post("/logout").status_code == 303


def test_web_and_legacy_api_error_branches():
    marker = uuid.uuid4().hex[:8]
    year = 2600 + int(marker[:2], 16)
    with TestClient(app, follow_redirects=False) as client:
        client.post("/login", data={"username": "admin", "password": "test-admin-password"})
        db = SessionLocal()
        admin = db.query(User).filter_by(username="admin").one()
        department = db.query(Department).filter_by(code="b2b").one()
        admin_id, department_id = admin.id, department.id
        db.close()
        assert client.post(f"/admin/users/{admin_id}/delete").status_code == 400
        assert client.post(f"/admin/users/{admin_id}/departments", data={"is_admin": "0", "is_active": "0"}).status_code == 400
        assert client.post("/admin/users/999999/delete").status_code == 404
        assert client.post("/admin/api-keys/999999/delete").status_code == 404

        created = client.post("/api/periods", data={"year": year, "month": 3})
        assert created.status_code == 200
        period_id = created.json()["id"]
        assert client.get(f"/api/periods/{period_id}").status_code == 200
        assert client.get(f"/api/periods/{period_id}/validation").status_code == 200
        assert client.post(f"/api/periods/{period_id}/validate").status_code == 200
        assert client.post(f"/api/periods/{period_id}/calculate").status_code == 400
        assert client.post(f"/api/periods/{period_id}/pdf").status_code == 400
        assert client.get("/api/periods/999999").status_code == 404
        assert client.get("/api/periods/2999/12").status_code == 404

        invalid_type = client.post(
            f"/api/periods/{period_id}/reports/not-a-report",
            files={"file": ("bad.xlsx", b"bad")},
        )
        assert invalid_type.status_code == 400
        assert client.post(
            f"/api/periods/{period_id}/reports/profit",
            files={"file": ("profit.xlsx", b"broken excel")},
        ).status_code == 200

        db = SessionLocal(); period = db.get(Period, period_id)
        manager = manager_report(); manager["report_type"] = "manager"; manager["salary_total"] = 1
        employee = Employee(full_name=f"Ошибка {marker} Менеджер")
        calculation = Calculation(period=period, employee=employee, snapshot_json=json.dumps(manager, ensure_ascii=False))
        unknown_employee = Employee(full_name=f"Ошибка {marker} Unknown")
        unknown = Calculation(period=period, employee=unknown_employee, snapshot_json=json.dumps({"employee": unknown_employee.full_name, "report_type": "unknown"}, ensure_ascii=False))
        no_pdf_employee = Employee(full_name=f"Ошибка {marker} NoPdf")
        no_pdf = Calculation(period=period, employee=no_pdf_employee, snapshot_json=json.dumps(manager, ensure_ascii=False))
        db.add_all([calculation, unknown, no_pdf]); db.commit()
        calculation_id, unknown_id, no_pdf_id = calculation.id, unknown.id, no_pdf.id
        db.close()

        assert client.post(f"/calculations/{calculation_id}/snapshot", data={"snapshot_json": "{"}).status_code == 400
        assert client.post(f"/calculations/{unknown_id}/pdf").status_code == 400
        assert client.get(f"/calculations/{no_pdf_id}/pdf/download").status_code == 404
        assert client.get("/calculations/999999").status_code == 404
        assert client.post(f"/calculations/{calculation_id}/additional-payments/999999/update", data={"title": "x", "amount": 1}).status_code == 404
        assert client.post(f"/calculations/{calculation_id}/additional-payments/999999/delete").status_code == 404
        assert client.post(f"/calculations/{calculation_id}/adjustments/999999/update", data={"amount": 1}).status_code == 404
        assert client.post(f"/calculations/{calculation_id}/adjustments/999999/delete").status_code == 404
        assert client.get(f"/api/periods/{year}/3/calculations/{unknown_id}").status_code == 200
        assert client.get(f"/api/periods/{year}/3/calculations/999999").status_code == 404
        assert client.post(f"/api/periods/{year}/3/calculations/{unknown_id}/pdf").status_code == 400
        assert client.get(f"/api/periods/{year}/3/calculations/{no_pdf_id}/pdf/download").status_code == 404
        assert client.post(f"/periods/{period_id}/delete").status_code == 303
