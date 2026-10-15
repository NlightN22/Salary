import os
import tempfile
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker


TEST_DATA_DIR = Path(tempfile.mkdtemp(prefix="salary-tests-"))
os.environ.setdefault("SALARY_DATA_DIR", str(TEST_DATA_DIR))
os.environ.setdefault("DATABASE_URL", f"sqlite:///{TEST_DATA_DIR / 'web.db'}")
os.environ.setdefault("SALARY_SESSION_SECRET", "test-only-secret-not-for-production-123456")
os.environ.setdefault("SALARY_ADMIN_PASSWORD", "test-admin-password")

from salary_web.database import Base  # noqa: E402
from salary_web import models  # noqa: E402,F401


@pytest.fixture(scope="session", autouse=True)
def close_web_database_pool():
    from salary_web.database import engine
    yield
    engine.dispose()


@pytest.fixture
def db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)
        engine.dispose()
