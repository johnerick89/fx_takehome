"""API routers aggregated for application mounting."""

from app.api.customers import router as customers_router
from app.api.quotes import router as quotes_router
from app.api.rates import router as rates_router

__all__ = ["customers_router", "quotes_router", "rates_router"]
