"""Trace ID middleware for request correlation."""

import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.logging import trace_id_var

TRACE_HEADER = "X-Trace-ID"


class TraceIDMiddleware(BaseHTTPMiddleware):
    """Assign or propagate a trace ID for each request."""

    async def dispatch(self, request: Request, call_next) -> Response:
        """Set trace ID on request state and response headers."""
        trace_id = request.headers.get(TRACE_HEADER) or str(uuid.uuid4())
        request.state.trace_id = trace_id
        token = trace_id_var.set(trace_id)
        try:
            response = await call_next(request)
            response.headers[TRACE_HEADER] = trace_id
            return response
        finally:
            trace_id_var.reset(token)
