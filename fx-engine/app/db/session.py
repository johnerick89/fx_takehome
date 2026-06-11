"""Database engine and session management."""

from collections.abc import Generator

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.db.base import Base

_engine: Engine | None = None
SessionLocal: sessionmaker[Session] | None = None


def _sqlite_connect_args(database_url: str) -> dict[str, bool]:
    """Return SQLite-specific connect args when applicable."""
    if database_url.startswith("sqlite"):
        return {"check_same_thread": False}
    return {}


def _configure_sqlite_pragmas(dbapi_connection, _connection_record) -> None:
    """Enable WAL mode and foreign keys for SQLite connections."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def configure_engine(database_url: str | None = None) -> Engine:
    """Create or replace the global engine and session factory."""
    global _engine, SessionLocal

    settings = get_settings()
    url = database_url or settings.database_url

    if _engine is not None:
        _engine.dispose()

    _engine = __create_engine(url)
    SessionLocal = sessionmaker(bind=_engine, autoflush=False, autocommit=False)
    return _engine


def __create_engine(database_url: str) -> Engine:
    """Build a configured SQLAlchemy engine."""
    engine = create_engine(
        database_url,
        connect_args=_sqlite_connect_args(database_url),
    )
    if database_url.startswith("sqlite"):
        event.listen(engine, "connect", _configure_sqlite_pragmas)
    return engine


def get_engine() -> Engine:
    """Return the configured database engine."""
    if _engine is None:
        configure_engine()
    assert _engine is not None
    return _engine


def get_db() -> Generator[Session, None, None]:
    """Yield a database session for request scope."""
    if SessionLocal is None:
        configure_engine()
    assert SessionLocal is not None
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def check_db_connectivity() -> None:
    """Verify the database accepts connections."""
    with get_engine().connect() as connection:
        connection.execute(text("SELECT 1"))


# Initialise engine on module import for application use.
configure_engine()
