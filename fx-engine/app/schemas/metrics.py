"""Metrics response schemas."""

from datetime import datetime

from pydantic import BaseModel


class MetricsResponse(BaseModel):
    """System metrics payload per SPEC §11."""

    quotes_generated_total: int
    executions_successful_total: int
    executions_failed_total: int
    rates_last_updated: datetime | None
    active_quotes_count: int
