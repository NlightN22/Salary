from collections.abc import Generator

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from salary_web.config import DATA_DIR, DATABASE_URL


class Base(DeclarativeBase):
    pass


engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
)


@event.listens_for(engine, "connect")
def configure_sqlite(connection, _connection_record):
    if not DATABASE_URL.startswith("sqlite"):
        return
    cursor = connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def init_db() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    from salary_web import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    migrate_db()
    _ensure_seed_data()


def migrate_db() -> None:
    """Apply lightweight SQLite migrations for early development schemas."""
    if not DATABASE_URL.startswith("sqlite"):
        return

    with engine.begin() as connection:
        _add_column_if_missing(connection, "users", "session_version", "INTEGER NOT NULL DEFAULT 0")
        has_uploaded_reports = connection.execute(text(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name='uploaded_reports'"
        )).scalar_one_or_none()
        if has_uploaded_reports:
            indexes = connection.execute(text("PRAGMA index_list(uploaded_reports)")).fetchall()
            has_period_type_unique = any(
                bool(row[2]) and str(row[1]).startswith("sqlite_autoindex_uploaded_reports")
                for row in indexes
            )
            if has_period_type_unique:
                connection.execute(text("PRAGMA foreign_keys=OFF"))
                connection.execute(text("ALTER TABLE uploaded_reports RENAME TO uploaded_reports_old"))
                connection.execute(text("""
                    CREATE TABLE uploaded_reports (
                        id INTEGER NOT NULL PRIMARY KEY,
                        period_id INTEGER NOT NULL,
                        report_type VARCHAR(50) NOT NULL,
                        original_filename VARCHAR(255) NOT NULL,
                        stored_path VARCHAR(500) NOT NULL,
                        file_hash VARCHAR(64) NOT NULL,
                        status VARCHAR(50) NOT NULL,
                        error_message TEXT,
                        uploaded_at DATETIME NOT NULL,
                        FOREIGN KEY(period_id) REFERENCES periods (id)
                    )
                """))
                connection.execute(text("""
                    INSERT INTO uploaded_reports (
                        id,
                        period_id,
                        report_type,
                        original_filename,
                        stored_path,
                        file_hash,
                        status,
                        error_message,
                        uploaded_at
                    )
                    SELECT
                        id,
                        period_id,
                        report_type,
                        original_filename,
                        stored_path,
                        file_hash,
                        status,
                        error_message,
                        uploaded_at
                    FROM uploaded_reports_old
                """))
                connection.execute(text("DROP TABLE uploaded_reports_old"))
                connection.execute(text("PRAGMA foreign_keys=ON"))

        _add_column_if_missing(
            connection,
            "additional_payments",
            "calculation_id",
            "INTEGER",
        )
        _add_column_if_missing(
            connection,
            "calculation_adjustments",
            "calculation_id",
            "INTEGER",
        )
        _add_column_if_missing(
            connection,
            "periods",
            "department_id",
            "INTEGER",
        )
        _add_column_if_missing(
            connection,
            "api_keys",
            "key_secret",
            "VARCHAR(255)",
        )

        department_id = connection.execute(text(
            "SELECT id FROM departments WHERE code='b2b'"
        )).scalar_one_or_none()
        if department_id is None:
            connection.execute(text(
                "INSERT INTO departments (code, name, is_active) "
                "VALUES ('b2b', 'B2B-направление', 1)"
            ))
            department_id = connection.execute(text(
                "SELECT id FROM departments WHERE code='b2b'"
            )).scalar_one()
        connection.execute(text(
            "UPDATE periods SET department_id=:department_id WHERE department_id IS NULL"
        ), {"department_id": department_id})
        connection.execute(text(
            "UPDATE calculations SET status='calculated' WHERE status='pdf_created'"
        ))
        connection.execute(text(
            "UPDATE periods SET status='calculation_created' WHERE status='pdf_created'"
        ))


def _ensure_seed_data() -> None:
    from salary_web.auth import ensure_default_auth_data

    db = SessionLocal()
    try:
        ensure_default_auth_data(db)
    finally:
        db.close()


def _add_column_if_missing(connection, table_name: str, column_name: str, definition: str) -> None:
    has_table = connection.execute(text(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=:table_name"
    ), {"table_name": table_name}).scalar_one_or_none()
    if not has_table:
        return

    columns = connection.execute(text(f"PRAGMA table_info({table_name})")).fetchall()
    if any(row[1] == column_name for row in columns):
        return
    connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}"))


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
