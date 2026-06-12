"""API error response schemas."""

from pydantic import BaseModel


class ErrorResponse(BaseModel):
    """Structured error envelope per SPEC §10."""

    error_code: str
    message: str
    trace_id: str
