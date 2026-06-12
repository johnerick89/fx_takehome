"""Health check response schemas."""

from pydantic import BaseModel


class HealthResponse(BaseModel):
    """Health check payload per SPEC §11."""

    status: str
    db: str
    rates_age_seconds: int | None
    rates_status: str
