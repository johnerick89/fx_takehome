"""Metrics API routes."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.metrics import MetricsResponse
from app.services.metrics_service import get_metrics

router = APIRouter(tags=["metrics"])


@router.get("/metrics", response_model=MetricsResponse)
def metrics_endpoint(db: Session = Depends(get_db)) -> MetricsResponse:
    """Return aggregate system metrics."""
    return get_metrics(db)
