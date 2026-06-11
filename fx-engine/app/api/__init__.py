"""API routers aggregated for application mounting."""

from app.api.customers import router as customers_router

__all__ = ["customers_router"]
