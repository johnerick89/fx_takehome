"""Database setup tests."""

import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.config import get_settings
from app.db import session as db_session
from app.db.base import Base
from app.models.base import BaseModel


class _SampleRecord(BaseModel):
    """Temporary model for database behaviour tests."""

    __tablename__ = "sample_records"

    name: Mapped[str] = mapped_column(String(50))


@pytest.fixture
def isolated_db(tmp_path, monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """Configure an isolated SQLite database for tests."""
    database_url = f"sqlite:///{tmp_path / 'test.db'}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()
    db_session.configure_engine(database_url)
    db_session.get_engine()
    Base.metadata.create_all(db_session.get_engine(), tables=[_SampleRecord.__table__])
    yield database_url
    get_settings.cache_clear()
    db_session.configure_engine()


def test_engine_connects(isolated_db: str) -> None:
    """Engine connects and SELECT 1 succeeds."""
    with db_session.get_engine().connect() as connection:
        result = connection.execute(text("SELECT 1")).scalar_one()
        assert result == 1


def test_journal_mode_is_wal(isolated_db: str) -> None:
    """SQLite connections use WAL journal mode."""
    with db_session.get_engine().connect() as connection:
        journal_mode = connection.execute(text("PRAGMA journal_mode")).scalar_one()
        assert str(journal_mode).lower() == "wal"


def test_get_db_yields_session(isolated_db: str) -> None:
    """get_db dependency yields a usable session and closes cleanly."""
    generator = db_session.get_db()
    session = next(generator)
    try:
        assert session.execute(text("SELECT 1")).scalar_one() == 1
    finally:
        generator.close()


def test_base_model_generates_uuid_primary_key(isolated_db: str) -> None:
    """BaseModel subclasses receive Python-generated UUID primary keys."""
    assert db_session.SessionLocal is not None
    with db_session.SessionLocal() as session:
        record = _SampleRecord(name="test")
        session.add(record)
        session.commit()
        session.refresh(record)

        parsed = uuid.UUID(record.id, version=4)
        assert str(parsed) == record.id
        assert record.created_at is not None
        assert record.updated_at is not None
