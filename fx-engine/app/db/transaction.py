"""Database transaction helpers."""

from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import text
from sqlalchemy.orm import Session


@contextmanager
def immediate_transaction(db: Session) -> Generator[Session, None, None]:
    """BEGIN IMMEDIATE wrapper for SQLite concurrency safety."""
    if db.in_transaction():
        db.rollback()
    db.execute(text("BEGIN IMMEDIATE"))
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
