"""Request/response logging middleware."""

import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.logging import get_logger

logger = get_logger(__name__)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Log inbound requests and outbound responses without body content."""

    async def dispatch(self, request: Request, call_next) -> Response:
        """Log request received and response completed with timing."""
        method = request.method
        path = request.url.path
        logger.info(
            f"→ {method} {path}",
            extra={"event": "request.received", "method": method, "path": path},
        )
        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = int((time.perf_counter() - start) * 1000)
        logger.info(
            f"← {response.status_code} {method} {path} {duration_ms}ms",
            extra={
                "event": "request.completed",
                "method": method,
                "path": path,
                "status_code": response.status_code,
                "duration_ms": duration_ms,
            },
        )
        return response
