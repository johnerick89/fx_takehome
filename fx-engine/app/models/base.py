"""Shared ORM base model."""

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class BaseModel(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Abstract base model with UUID primary key and timestamps."""

    __abstract__ = True
