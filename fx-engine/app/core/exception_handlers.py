"""Global FastAPI exception handlers."""

import logging
import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.core.exceptions import AppError
from app.core.logging import trace_id_var
from app.schemas.error import ErrorResponse

logger = logging.getLogger(__name__)


def _trace_id_for_request(request: Request) -> str:
    """Return the trace ID for the current request."""
    trace_id = getattr(request.state, "trace_id", None)
    if trace_id:
        return trace_id
    context_trace_id = trace_id_var.get()
    if context_trace_id:
        return context_trace_id
    return str(uuid.uuid4())


def _error_response(
    request: Request,
    *,
    error_code: str,
    message: str,
    status_code: int,
) -> JSONResponse:
    """Build a SPEC §10 error JSON response."""
    body = ErrorResponse(
        error_code=error_code,
        message=message,
        trace_id=_trace_id_for_request(request),
    )
    return JSONResponse(status_code=status_code, content=body.model_dump())


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    """Map domain errors to structured API responses."""
    return _error_response(
        request,
        error_code=exc.error_code,
        message=exc.message,
        status_code=exc.http_status,
    )


async def validation_error_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    """Map request validation failures to structured API responses."""
    message = "Request validation failed"
    errors = exc.errors()
    if errors:
        first = errors[0]
        loc = ".".join(str(part) for part in first.get("loc", ()) if part != "body")
        detail = first.get("msg", message)
        message = f"{loc}: {detail}" if loc else detail

    return _error_response(
        request,
        error_code="INVALID_AMOUNT",
        message=message,
        status_code=422,
    )


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Map unexpected exceptions to INTERNAL_ERROR without leaking details."""
    logger.exception(
        "unhandled.exception",
        extra={"event": "unhandled.exception", "error": str(exc)},
    )
    return _error_response(
        request,
        error_code="INTERNAL_ERROR",
        message="An unexpected error occurred",
        status_code=500,
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Register global exception handlers on the application."""
    app.add_exception_handler(AppError, app_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(Exception, unhandled_error_handler)
