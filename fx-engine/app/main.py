"""FastAPI application entry point."""

import asyncio
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import customers_router, quotes_router, rates_router
from app.core.exception_handlers import register_exception_handlers
from app.db.session import SessionLocal, check_db_connectivity
from app.middlewares import RequestLoggingMiddleware, TraceIDMiddleware
from app.services.rate_scheduler import rate_refresh_loop
from app.services.rate_service import seed_corridor_spreads


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Verify database connectivity and start background tasks on startup."""
    check_db_connectivity()
    assert SessionLocal is not None
    with SessionLocal() as db:
        seed_corridor_spreads(db)

    refresh_task = asyncio.create_task(rate_refresh_loop())
    try:
        yield
    finally:
        refresh_task.cancel()
        try:
            await refresh_task
        except asyncio.CancelledError:
            pass


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="FX Engine",
        version="1.0.0",
        lifespan=lifespan,
    )
    register_exception_handlers(app)

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
    app.include_router(rates_router)
    app.include_router(quotes_router)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        """Return application health status."""
        return {"status": "ok"}

    return app


app = create_app()
