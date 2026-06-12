"""Health check API routes."""

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.health import HealthResponse
from app.services.health_service import get_health

router = APIRouter(tags=["health"])


@router.get("/healthz", response_model=HealthResponse)
def healthz_endpoint(db: Session = Depends(get_db)) -> HealthResponse | JSONResponse:
    """Return application health including DB and rates status."""
    try:
        health = get_health(db)
    except Exception:
        return JSONResponse(
            status_code=503,
            content={
                "status": "unavailable",
                "db": "error",
                "rates_age_seconds": None,
                "rates_status": "unavailable",
            },
        )
    return HealthResponse(
        status=health.status,
        db=health.db,
        rates_age_seconds=health.rates_age_seconds,
        rates_status=health.rates_status,
    )
