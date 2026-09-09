import pytest
from fastapi import HTTPException
from starlette.requests import Request

from salary_web.auth import (
    api_key_department_ids, authenticate_api_key, authenticate_user,
    can_access_department, can_api_key_access_department, current_user,
    generate_api_key_secret, hash_api_key, hash_password, make_session_token,
    read_session_user_id, require_admin, require_api_key_for_department,
    require_user, user_department_ids, verify_password,
)
from salary_web.models import ApiKey, ApiKeyDepartment, Department, User, UserDepartment
from services.rounding import round_half_up


@pytest.mark.parametrize(
    ("value", "expected"),
    [(1.005, 1.01), (2.675, 2.68), (-1.005, -1.01), (0, 0.0), ("12.345", 12.35)],
)
def test_excel_rounding(value, expected):
    assert round_half_up(value) == expected


def test_password_hash_is_salted_and_verifiable():
    first = hash_password("секрет")
    second = hash_password("секрет")
    assert first != second
    assert verify_password("секрет", first)
    assert not verify_password("другой", first)


@pytest.mark.parametrize("broken", ["", "plain", "x$y$z$q", None])
def test_broken_password_hash_is_rejected(broken):
    assert not verify_password("secret", broken)


def test_api_key_hash_is_stable_without_storing_plaintext():
    assert hash_api_key("key") == hash_api_key("key")
    assert hash_api_key("key") != "key"


def request_with_cookie(token=None, api_key=None):
    headers = []
    if token is not None:
        headers.append((b"cookie", f"salary_user={token}".encode()))
    if api_key is not None:
        headers.append((b"x-api-key", api_key.encode()))
    return Request({"type": "http", "method": "GET", "path": "/", "headers": headers})


def test_session_tokens_and_access_control(db):
    department = Department(code="auth", name="Auth")
    admin = User(username="root", password_hash=hash_password("pw"), is_admin=1, is_active=1)
    user = User(username="user", password_hash=hash_password("pw"), is_admin=0, is_active=1)
    inactive = User(username="off", password_hash=hash_password("pw"), is_active=0)
    db.add_all([department, admin, user, inactive]); db.flush()
    db.add(UserDepartment(user_id=user.id, department_id=department.id)); db.commit()

    assert authenticate_user(db, "missing", "pw") is None
    assert authenticate_user(db, "off", "pw") is None
    assert authenticate_user(db, "user", "bad") is None
    assert authenticate_user(db, "user", "pw").id == user.id
    token = make_session_token(user.id)
    request = request_with_cookie(token)
    assert read_session_user_id(request) == user.id
    assert current_user(request, db).id == user.id
    assert require_user(request, db).id == user.id
    with pytest.raises(HTTPException) as error:
        require_admin(request, db)
    assert error.value.status_code == 403
    assert user_department_ids(user) == [department.id]
    assert user_department_ids(admin) == []
    assert can_access_department(admin, None)
    assert can_access_department(user, department.id)
    assert not can_access_department(user, None)

    assert read_session_user_id(request_with_cookie("broken")) is None
    assert read_session_user_id(request_with_cookie("x:bad")) is None
    invalid_payload = "x:" + make_session_token(1).split(":", 1)[1]
    assert read_session_user_id(request_with_cookie(invalid_payload)) is None
    with pytest.raises(HTTPException):
        require_user(request_with_cookie(), db)


def test_api_key_authentication_and_department_scope(db):
    first = Department(code="first", name="First")
    second = Department(code="second", name="Second")
    secret = generate_api_key_secret()
    key = ApiKey(name="key", key_hash=hash_api_key(secret), is_active=1)
    db.add_all([first, second, key]); db.flush()
    db.add(ApiKeyDepartment(api_key_id=key.id, department_id=first.id)); db.commit()
    assert secret.startswith("sk_salary_")
    assert authenticate_api_key(db, None) is None
    assert authenticate_api_key(db, "wrong") is None
    assert authenticate_api_key(db, secret).id == key.id
    assert api_key_department_ids(key) == [first.id]
    assert can_api_key_access_department(key, first.id)
    assert not can_api_key_access_department(key, None)
    assert require_api_key_for_department(request_with_cookie(api_key=secret), db, first).id == key.id
    with pytest.raises(HTTPException) as forbidden:
        require_api_key_for_department(request_with_cookie(api_key=secret), db, second)
    assert forbidden.value.status_code == 403
