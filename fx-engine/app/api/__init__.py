"""API routers aggregated for application mounting."""

from app.api.customers import router as customers_router
from app.api.health import router as health_router
from app.api.metrics import router as metrics_router
from app.api.quotes import router as quotes_router
from app.api.rates import router as rates_router
from app.api.transactions import router as transactions_router

__all__ = [
    "customers_router",
    "health_router",
    "metrics_router",
    "quotes_router",
    "rates_router",
    "transactions_router",
]
