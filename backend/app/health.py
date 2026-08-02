from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import PlainTextResponse
from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import BrokerSource, IngestionFile, IngestionStatus
from app.observability import render_metrics

router = APIRouter(tags=["health"])


def _check_database(db: Session) -> None:
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"status": "degraded", "database": "unavailable"},
        ) from exc


@router.get("/live")
def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
def ready(db: Session = Depends(get_db)) -> dict[str, str]:
    _check_database(db)
    return {"status": "ok", "database": "ok"}


@router.get("/health")
def health(db: Session = Depends(get_db)) -> dict[str, str]:
    """Backward-compatible readiness check."""
    _check_database(db)

    return {"status": "ok", "database": "ok"}


@router.get("/metrics", response_class=PlainTextResponse)
def metrics(db: Session = Depends(get_db)) -> str:
    now = datetime.now(timezone.utc)
    try:
        latest = db.execute(
            select(BrokerSource.id, func.max(IngestionFile.synced_at))
            .join(IngestionFile, IngestionFile.broker_source_id == BrokerSource.id)
            .where(IngestionFile.status == IngestionStatus.SUCCEEDED)
            .group_by(BrokerSource.id)
        ).all()
    except SQLAlchemyError:
        latest = []
    source_lags = {
        source_id: (now - _as_utc(synced_at)).total_seconds() for source_id, synced_at in latest
    }
    return render_metrics(source_lags)


def _as_utc(value: datetime) -> datetime:
    return (
        value.replace(tzinfo=timezone.utc)
        if value.tzinfo is None
        else value.astimezone(timezone.utc)
    )
