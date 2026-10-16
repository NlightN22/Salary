import pytest

import salary_web.app as web
from salary_web.auth import make_session_token
from salary_web.models import UserDepartment
from tests.test_extended_boundaries import scoped_client  # noqa: F401


@pytest.mark.parametrize("path", [
    "/periods/1", "/periods/2050/1", "/departments/1/periods/2050/1",
    "/Own/1/periods/2050/1", "/periods/2050/1/reports", "/periods/2050/1/calculate",
    "/api/periods", "/api/periods/1", "/api/periods/2050/1",
    "/api/periods/2050/1/calculations", "/api/calculations/1",
    "/api/calculations/1/pdf", "/api/calculations/1/pdf/download",
])
@pytest.mark.parametrize("method", ["GET", "POST"])
def test_removed_addresses_are_not_redirected(scoped_client, path, method):
    client, _, _, _, user, _ = scoped_client
    client.cookies.set("salary_user", make_session_token(user.id))
    response = client.request(method, path, files={"files": ("profit.xlsx", b"invalid")})
    assert response.status_code in {404, 405}
    assert "location" not in response.headers


def test_registered_routes_and_documentation_have_no_legacy_api(scoped_client):
    client, _, _, _, user, _ = scoped_client
    client.cookies.set("salary_user", make_session_token(user.id))
    paths = [route.path for route in web.app.routes]
    assert not any(path.startswith(("/api/periods", "/api/calculations", "/departments/")) for path in paths)
    assert not any("{department_id}/periods" in path for path in paths)
    assert "/api/periods/" not in client.get("/api-docs").text
    assert "/api/calculations/" not in client.get("/api/commands").text


def test_department_cannot_be_overridden_by_query_parameter(scoped_client, db):
    client, first, second, _, user, _ = scoped_client
    user.is_admin = 0
    db.add(UserDepartment(user_id=user.id, department_id=second.department_id)); db.commit()
    client.cookies.set("salary_user", make_session_token(user.id))
    assert client.get(web.period_url(first) + f"?department_id={second.department_id}").status_code == 403


def test_current_route_edge_cases(scoped_client, db, monkeypatch):
    client, period, _, calc, user, _ = scoped_client
    client.cookies.set("salary_user", make_session_token(user.id))
    assert client.get("/Own/2050/1").headers["location"] == web.period_url(period)
    assert client.post("/periods/999999/delete").status_code == 404
    calc.pdf_path = "/definitely-missing/salary.pdf"; db.commit()
    assert client.get(f"/calculations/{calc.id}/pdf/download").status_code == 404
    monkeypatch.setattr(web, "calculate_period", lambda *_: [])
    assert web.calculate_period_response(db, period)["calculations_created"] == 0
    assert web.create_period(db, 2099, 1).department_id is not None
