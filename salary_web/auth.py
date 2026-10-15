import hashlib
import hmac
import os
import secrets
from datetime import UTC, datetime

from fastapi import HTTPException, Request
from sqlalchemy.orm import Session

from salary_web.models import ApiKey, ApiKeyDepartment, Department, User, UserDepartment


DEFAULT_DEPARTMENT_CODE = "b2b"
DEFAULT_DEPARTMENT_NAME = "B2B-направление"
SESSION_COOKIE = "salary_user"
SESSION_SECRET = os.getenv("SALARY_SESSION_SECRET") or secrets.token_urlsafe(32)
API_KEY_HEADER = "X-API-Key"


def validate_security_config() -> None:
    if os.getenv("SALARY_REQUIRE_SECURE_CONFIG") != "1":
        return
    secret = os.getenv("SALARY_SESSION_SECRET", "")
    if len(secret) < 32 or secret in {
        "salary-web-local-session-change-me", "change-me-before-production",
        "replace-this-with-a-long-random-string",
    }:
        raise RuntimeError("Задайте SALARY_SESSION_SECRET: случайный секрет не короче 32 символов")


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 120_000)
    return f"pbkdf2_sha256$120000${salt.hex()}${digest.hex()}"


def generate_api_key_secret() -> str:
    return f"sk_salary_{secrets.token_urlsafe(32)}"


def hash_api_key(api_key: str) -> str:
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        algorithm, iterations, salt_hex, digest_hex = stored_hash.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            bytes.fromhex(salt_hex),
            int(iterations),
        )
        return hmac.compare_digest(digest.hex(), digest_hex)
    except (AttributeError, ValueError, TypeError):
        return False


def make_session_token(user_id: int) -> str:
    payload = str(user_id)
    signature = hmac.new(
        SESSION_SECRET.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"{payload}:{signature}"


def read_session_user_id(request: Request) -> int | None:
    token = request.cookies.get(SESSION_COOKIE)
    if not token or ":" not in token:
        return None
    payload, signature = token.split(":", 1)
    expected = hmac.new(
        SESSION_SECRET.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(signature, expected):
        return None
    try:
        return int(payload)
    except ValueError:
        return None


def ensure_default_auth_data(db: Session) -> None:
    department = get_or_create_default_department(db)
    if db.query(User).first() is None:
        password = os.getenv("SALARY_ADMIN_PASSWORD", "")
        if len(password) < 12 or password == "replace-with-a-strong-password":
            raise RuntimeError("Для первой настройки задайте SALARY_ADMIN_PASSWORD (не менее 12 символов)")
        admin = User(
            username="admin",
            password_hash=hash_password(password),
            full_name="Администратор",
            is_admin=1,
            is_active=1,
        )
        db.add(admin)
        db.flush()
        _ensure_user_department(db, admin, department)
    db.commit()


def get_or_create_default_department(db: Session) -> Department:
    department = db.query(Department).filter(Department.code == DEFAULT_DEPARTMENT_CODE).one_or_none()
    if department is None:
        department = Department(code=DEFAULT_DEPARTMENT_CODE, name=DEFAULT_DEPARTMENT_NAME)
        db.add(department)
        db.flush()
    return department


def authenticate_user(db: Session, username: str, password: str) -> User | None:
    user = db.query(User).filter(User.username == username).one_or_none()
    if user is None or not user.is_active:
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user


def current_user(request: Request, db: Session) -> User | None:
    user_id = read_session_user_id(request)
    if not user_id:
        return None
    user = db.get(User, int(user_id))
    if user is None or not user.is_active:
        return None
    return user


def require_user(request: Request, db: Session) -> User:
    user = current_user(request, db)
    if user is None:
        raise HTTPException(status_code=401, detail="Требуется авторизация")
    return user


def require_admin(request: Request, db: Session) -> User:
    user = require_user(request, db)
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    return user


def user_department_ids(user: User) -> list[int]:
    if user.is_admin:
        return []
    return [link.department_id for link in user.departments]


def can_access_department(user: User, department_id: int | None) -> bool:
    if user.is_admin:
        return True
    if department_id is None:
        return False
    return department_id in user_department_ids(user)


def authenticate_api_key(db: Session, api_key: str | None) -> ApiKey | None:
    if not api_key:
        return None
    key_hash = hash_api_key(api_key)
    key = db.query(ApiKey).filter(ApiKey.key_hash == key_hash).one_or_none()
    if key is None or not key.is_active:
        return None
    key.last_used_at = datetime.now(UTC).replace(tzinfo=None)
    db.commit()
    return key


def api_key_department_ids(api_key: ApiKey) -> list[int]:
    return [link.department_id for link in api_key.departments]


def can_api_key_access_department(api_key: ApiKey, department_id: int | None) -> bool:
    if department_id is None:
        return False
    return department_id in api_key_department_ids(api_key)


def require_api_key_for_department(
    request: Request,
    db: Session,
    department: Department,
) -> ApiKey:
    key = authenticate_api_key(db, request.headers.get(API_KEY_HEADER))
    if key is None:
        raise HTTPException(status_code=401, detail="Требуется API-ключ")
    if not can_api_key_access_department(key, department.id):
        raise HTTPException(status_code=403, detail="Нет доступа к подразделению")
    return key


def _ensure_user_department(db: Session, user: User, department: Department) -> None:
    exists = (
        db.query(UserDepartment)
        .filter(
            UserDepartment.user_id == user.id,
            UserDepartment.department_id == department.id,
        )
        .one_or_none()
    )
    if exists is None:
        db.add(UserDepartment(user_id=user.id, department_id=department.id))
