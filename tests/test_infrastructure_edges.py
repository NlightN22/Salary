import sqlite3
from io import BytesIO
from pathlib import Path

import pytest
from fastapi import UploadFile
from sqlalchemy import create_engine, text

import salary_web.config as config
import salary_web.database as database
import salary_web.report_validation as validation
from salary_web.models import Department, Period, ReportStatus, UploadedReport
from salary_web.report_storage import save_uploaded_reports_batch
from salary_web.report_storage import detect_report_type
from salary_web.calculation_runner import _period_files as runner_period_files, calculate_period
from services.file_finder import find_files


def test_department_scoped_path_resolution(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DEPARTMENTS_DIR", tmp_path / "data")
    existing = tmp_path / "existing.pdf"; existing.write_bytes(b"x")
    assert config.resolve_service_data_path(existing) == existing
    assert config.resolve_service_data_path("data_root/B2B/2026/6/report.pdf") == tmp_path / "data/B2B/2026/6/report.pdf"
    assert config.resolve_service_data_path("old/path.pdf") == Path("old/path.pdf")
    outside = tmp_path / "outside" / "x.pdf"
    assert config.stored_service_data_path(outside) == str(outside)
    assert config.department_storage_code(None) == "default"
    assert config.department_storage_code(type("D", (), {"code": " !! "})()) == "default"


def test_batch_upload_ignores_noise_and_unknown(db, tmp_path, monkeypatch):
    import salary_web.report_storage as storage
    monkeypatch.setattr(storage, "UPLOADS_DIR", tmp_path)
    period = Period(year=2026, month=1, department=Department(code="batch", name="Batch"))
    db.add(period); db.commit()
    uploads = [
        UploadFile(filename="notes.txt", file=BytesIO(b"x")),
        UploadFile(filename="unknown.xlsx", file=BytesIO(b"x")),
        UploadFile(filename="profit.xlsx", file=BytesIO(b"x")),
    ]
    saved = save_uploaded_reports_batch(db, period, uploads)
    assert [item.report_type for item in saved] == ["profit"]


def test_validation_skips_non_required_report(db, tmp_path, monkeypatch):
    from tests.test_validation_and_runner import complete_period
    period = complete_period(db, tmp_path)
    period.reports.append(UploadedReport(
        report_type="optional", original_filename="optional.xlsx",
        stored_path=str(tmp_path / "optional.xlsx"), file_hash="x", status=ReportStatus.UPLOADED.value,
    ))
    monkeypatch.setattr(validation, "read_excel", lambda path: object())
    monkeypatch.setattr(validation, "load_context_from_files", lambda *args, **kwargs: {})
    assert validation.validate_period_reports(db, period)["validated"]
    assert period.reports[-1].status == ReportStatus.UPLOADED.value


def test_database_non_sqlite_guards(monkeypatch):
    monkeypatch.setattr(database, "DATABASE_URL", "postgresql://example")
    assert database.configure_sqlite(object(), None) is None
    assert database.migrate_db() is None


def test_add_column_helper_missing_existing_and_new(tmp_path, request):
    engine = create_engine(f"sqlite:///{tmp_path / 'columns.db'}")
    request.addfinalizer(engine.dispose)
    with engine.begin() as connection:
        database._add_column_if_missing(connection, "missing", "x", "INTEGER")
        connection.execute(text("CREATE TABLE sample (id INTEGER PRIMARY KEY)"))
        database._add_column_if_missing(connection, "sample", "id", "INTEGER")
        database._add_column_if_missing(connection, "sample", "added", "TEXT")
        names = [row[1] for row in connection.execute(text("PRAGMA table_info(sample)"))]
    assert names == ["id", "added"]


def test_legacy_uploaded_reports_unique_constraint_migration(tmp_path, monkeypatch, request):
    path = tmp_path / "legacy.db"
    connection = sqlite3.connect(path)
    request.addfinalizer(connection.close)
    connection.executescript("""
        CREATE TABLE departments (id INTEGER PRIMARY KEY, code TEXT, name TEXT, is_active INTEGER);
        CREATE TABLE periods (id INTEGER PRIMARY KEY, year INTEGER, month INTEGER, status TEXT, department_id INTEGER);
        CREATE TABLE calculations (id INTEGER PRIMARY KEY, status TEXT);
        CREATE TABLE additional_payments (id INTEGER PRIMARY KEY);
        CREATE TABLE calculation_adjustments (id INTEGER PRIMARY KEY);
        CREATE TABLE api_keys (id INTEGER PRIMARY KEY);
        CREATE TABLE uploaded_reports (
          id INTEGER PRIMARY KEY, period_id INTEGER NOT NULL, report_type TEXT NOT NULL,
          original_filename TEXT NOT NULL, stored_path TEXT NOT NULL, file_hash TEXT NOT NULL,
          status TEXT NOT NULL, error_message TEXT, uploaded_at DATETIME NOT NULL,
          UNIQUE(period_id, report_type)
        );
        INSERT INTO periods VALUES (1, 2026, 1, 'pdf_created', NULL);
        INSERT INTO calculations VALUES (1, 'pdf_created');
        INSERT INTO uploaded_reports VALUES (1,1,'profit','p.xlsx','p.xlsx','h','uploaded',NULL,'2026-01-01');
    """)
    connection.commit(); connection.close()
    engine = create_engine(f"sqlite:///{path}")
    request.addfinalizer(engine.dispose)
    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setattr(database, "DATABASE_URL", f"sqlite:///{path}")
    database.migrate_db()
    with engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM uploaded_reports")).scalar_one() == 1
        assert connection.execute(text("SELECT status FROM calculations")).scalar_one() == "calculated"
        assert connection.execute(text("SELECT department_id FROM periods")).scalar_one() is not None
        columns = [row[1] for row in connection.execute(text("PRAGMA table_info(api_keys)"))]
        assert "key_secret" in columns


def test_get_db_always_closes(monkeypatch):
    class FakeSession:
        closed = False
        def close(self): self.closed = True
    fake = FakeSession()
    monkeypatch.setattr(database, "SessionLocal", lambda: fake)
    generator = database.get_db()
    assert next(generator) is fake
    generator.close()
    assert fake.closed


def test_ignored_upload_and_empty_file_collections(tmp_path):
    assert detect_report_type(".hidden.xlsx") is None
    assert find_files(tmp_path) == {}
    assert runner_period_files(type("P", (), {"reports": []})()) == {}
    assert validation._period_files(type("P", (), {"reports": []})()) == {}


def test_runner_rejects_complete_but_unvalidated(db, monkeypatch):
    period = Period(year=2026, month=9, department=Department(code="b2b", name="B2B"))
    db.add(period); db.commit()
    monkeypatch.setattr("salary_web.calculation_runner.report_completeness", lambda *_: {
        "complete": True, "validated": False, "missing": [],
    })
    with pytest.raises(ValueError, match="не прошли проверку"):
        calculate_period(db, period)


def test_validation_failure_leaves_optional_report_untouched(db, tmp_path, monkeypatch):
    from tests.test_validation_and_runner import complete_period
    period = complete_period(db, tmp_path)
    optional = UploadedReport(
        report_type="optional", original_filename="o", stored_path="o", file_hash="x",
        status=ReportStatus.UPLOADED.value,
    )
    period.reports.append(optional)
    monkeypatch.setattr(validation, "read_excel", lambda *_: object())
    monkeypatch.setattr(validation, "load_context_from_files", lambda *_a, **_k: (_ for _ in ()).throw(ValueError("bad")))
    validation.validate_period_reports(db, period)
    assert optional.status == ReportStatus.UPLOADED.value


def test_migration_without_legacy_uploaded_reports(tmp_path, monkeypatch, request):
    engine = create_engine(f"sqlite:///{tmp_path / 'empty.db'}")
    request.addfinalizer(engine.dispose)
    database.Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE uploaded_reports"))
    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setattr(database, "DATABASE_URL", "sqlite:///empty.db")
    database.migrate_db()
