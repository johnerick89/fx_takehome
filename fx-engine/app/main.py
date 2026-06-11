"""FastAPI application entry point."""

from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import customers_router
from app.db.session import check_db_connectivity
from app.middlewares import RequestLoggingMiddleware, TraceIDMiddleware


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Verify database connectivity on startup."""
    check_db_connectivity()
    yield


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="FX Engine",
        version="1.0.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(RequestLoggingMiddleware)
    app.add_middleware(TraceIDMiddleware)

    app.include_router(customers_router)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        """Return application health status."""
        return {"status": "ok"}

    return app


app = create_app()
