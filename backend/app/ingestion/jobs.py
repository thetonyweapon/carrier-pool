from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from uuid import uuid4

from sqlalchemy import and_, exists, or_, select
from sqlalchemy.exc import DBAPIError, IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.models import IngestionJob, IngestionJobStatus
from app.observability import increment, observe_seconds, record_ingestion_failure

DEFAULT_LEASE_SECONDS = 300
DEFAULT_MAX_ATTEMPTS = 5
RETRYABLE_FAILURE_CLASSES = {"OperationalError", "DBAPIError", "ConnectionError", "TimeoutError"}


def enqueue_job(
    session: Session,
    *,
    broker_id: str,
    broker_source_id: str,
    filename: str,
    file_path: Path,
    checksum: str,
    synced_at: datetime,
    now: Optional[datetime] = None,
) -> IngestionJob:
    now = now or datetime.now(timezone.utc)
    existing = session.scalar(
        select(IngestionJob).where(
            IngestionJob.broker_source_id == broker_source_id,
            IngestionJob.filename == filename,
        )
    )
    if existing is not None:
        if existing.checksum != checksum:
            raise ValueError("ingestion job checksum conflict")
        return existing

    job = IngestionJob(
        id=str(uuid4()),
        broker_id=broker_id,
        broker_source_id=broker_source_id,
        filename=filename,
        file_path=str(file_path),
        checksum=checksum,
        synced_at=synced_at,
        status=IngestionJobStatus.QUEUED,
        attempt_count=0,
        available_at=now,
        created_at=now,
    )
    try:
        with session.begin_nested():
            session.add(job)
            session.flush()
    except IntegrityError:
        existing = session.scalar(
            select(IngestionJob).where(
                IngestionJob.broker_source_id == broker_source_id,
                IngestionJob.filename == filename,
            )
        )
        if existing is None:
            raise
        if existing.checksum != checksum:
            raise ValueError("ingestion job checksum conflict")
        return existing
    return job


def claim_next_job(
    session: Session,
    worker_id: str,
    *,
    now: Optional[datetime] = None,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
) -> Optional[IngestionJob]:
    now = now or datetime.now(timezone.utc)
    earlier = IngestionJob.__table__.alias("earlier_ingestion_job")
    earlier_job_exists = exists(
        select(earlier.c.id).where(
            earlier.c.broker_source_id == IngestionJob.broker_source_id,
            earlier.c.status.in_(
                (
                    IngestionJobStatus.QUEUED,
                    IngestionJobStatus.RETRY_WAIT,
                    IngestionJobStatus.PROCESSING,
                )
            ),
            or_(
                earlier.c.synced_at < IngestionJob.synced_at,
                and_(
                    earlier.c.synced_at == IngestionJob.synced_at,
                    earlier.c.filename < IngestionJob.filename,
                ),
            ),
        )
    )
    expired_jobs = session.scalars(
        select(IngestionJob)
        .where(
            IngestionJob.status == IngestionJobStatus.PROCESSING,
            IngestionJob.lease_expires_at < now,
            IngestionJob.attempt_count >= DEFAULT_MAX_ATTEMPTS,
        )
        .with_for_update(skip_locked=True)
    ).all()
    for expired_job in expired_jobs:
        expired_job.status = IngestionJobStatus.DEAD_LETTER
        expired_job.completed_at = now
        expired_job.lease_owner = None
        expired_job.lease_expires_at = None
        expired_job.lease_token = None
        expired_job.failure_class = "LeaseExpired"
        expired_job.error_message = "LeaseExpired: ingestion failed"
    if expired_jobs:
        session.flush()

    job = session.scalar(
        select(IngestionJob)
        .where(
            or_(
                (
                    IngestionJob.status.in_(
                        (IngestionJobStatus.QUEUED, IngestionJobStatus.RETRY_WAIT)
                    )
                    & (IngestionJob.available_at <= now)
                ),
                (
                    (IngestionJob.status == IngestionJobStatus.PROCESSING)
                    & (IngestionJob.lease_expires_at < now)
                    & (IngestionJob.attempt_count < DEFAULT_MAX_ATTEMPTS)
                ),
            ),
            ~earlier_job_exists,
        )
        .order_by(IngestionJob.synced_at, IngestionJob.filename, IngestionJob.id)
        .with_for_update(skip_locked=True)
    )
    if job is None:
        if expired_jobs:
            session.commit()
            for _ in expired_jobs:
                increment("carrier_pool_ingestion_jobs_total", {"outcome": "dead_letter"})
                record_ingestion_failure("LeaseExpired")
        return None

    job.status = IngestionJobStatus.PROCESSING
    job.attempt_count += 1
    job.lease_owner = worker_id
    job.lease_token = str(uuid4())
    job.lease_expires_at = now + timedelta(seconds=lease_seconds)
    job.started_at = job.started_at or now
    session.commit()
    increment("carrier_pool_ingestion_attempts_total")
    for _ in expired_jobs:
        increment("carrier_pool_ingestion_jobs_total", {"outcome": "dead_letter"})
        record_ingestion_failure("LeaseExpired")
    return job


def complete_job(
    session: Session,
    job_id: str,
    worker_id: str,
    *,
    now: Optional[datetime] = None,
    lease_token: str,
) -> IngestionJob:
    job = _owned_job(session, job_id, worker_id, lease_token, now=now)
    job.status = IngestionJobStatus.SUCCEEDED
    job.completed_at = now or datetime.now(timezone.utc)
    job.lease_owner = None
    job.lease_expires_at = None
    job.lease_token = None
    job.failure_class = None
    job.error_message = None
    session.commit()
    increment("carrier_pool_ingestion_jobs_total", {"outcome": "succeeded"})
    if job.started_at is not None:
        observe_seconds(
            "carrier_pool_ingestion_job_duration_seconds",
            (_as_utc(job.completed_at) - _as_utc(job.started_at)).total_seconds(),
        )
    return job


def renew_lease(
    session: Session,
    job_id: str,
    worker_id: str,
    *,
    now: Optional[datetime] = None,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
    lease_token: str,
) -> IngestionJob:
    job = _owned_job(session, job_id, worker_id, lease_token, now=now)
    job.lease_expires_at = (now or datetime.now(timezone.utc)) + timedelta(seconds=lease_seconds)
    session.commit()
    return job


def assert_job_lease(
    session: Session,
    job_id: str,
    worker_id: str,
    lease_token: str,
    *,
    now: Optional[datetime] = None,
) -> None:
    _owned_job(session, job_id, worker_id, lease_token, now=now)


def fail_job(
    session: Session,
    job_id: str,
    worker_id: str,
    error: BaseException,
    *,
    now: Optional[datetime] = None,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    lease_token: str,
) -> IngestionJob:
    now = now or datetime.now(timezone.utc)
    job = _owned_job(session, job_id, worker_id, lease_token, now=now)
    retryable = is_retryable(error)
    job.failure_class = error.__class__.__name__
    job.error_message = _safe_error_message(error)
    job.lease_owner = None
    job.lease_expires_at = None
    job.lease_token = None
    if retryable and job.attempt_count < max_attempts:
        job.status = IngestionJobStatus.RETRY_WAIT
        job.available_at = now + timedelta(seconds=2 ** max(job.attempt_count - 1, 0))
    else:
        job.status = IngestionJobStatus.DEAD_LETTER
        job.completed_at = now
    session.commit()
    increment(
        "carrier_pool_ingestion_jobs_total",
        {"outcome": "retry_wait" if job.status == IngestionJobStatus.RETRY_WAIT else "dead_letter"},
    )
    record_ingestion_failure(job.failure_class or "Unknown")
    if job.started_at is not None:
        observe_seconds(
            "carrier_pool_ingestion_job_duration_seconds",
            (_as_utc(now) - _as_utc(job.started_at)).total_seconds(),
        )
    return job


def replay_dead_letter(
    session: Session,
    job_id: str,
    *,
    now: Optional[datetime] = None,
) -> IngestionJob:
    job = session.get(IngestionJob, job_id)
    if job is None:
        raise ValueError("ingestion job not found")
    if job.status != IngestionJobStatus.DEAD_LETTER:
        raise ValueError("only dead-letter jobs can be replayed")
    job.status = IngestionJobStatus.QUEUED
    job.attempt_count = 0
    job.available_at = now or datetime.now(timezone.utc)
    job.lease_owner = None
    job.lease_expires_at = None
    job.lease_token = None
    job.failure_class = None
    job.error_message = None
    job.completed_at = None
    session.commit()
    return job


def is_retryable(error: BaseException) -> bool:
    if isinstance(error, IntegrityError):
        return False
    if isinstance(error, (OperationalError, DBAPIError, ConnectionError, TimeoutError)):
        return True
    return error.__class__.__name__ in RETRYABLE_FAILURE_CLASSES


def _owned_job(
    session: Session,
    job_id: str,
    worker_id: str,
    lease_token: str,
    *,
    now: Optional[datetime] = None,
) -> IngestionJob:
    now = now or datetime.now(timezone.utc)
    job = session.scalar(select(IngestionJob).where(IngestionJob.id == job_id).with_for_update())
    if job is None:
        raise ValueError("ingestion job not found")
    if (
        job.status != IngestionJobStatus.PROCESSING
        or job.lease_owner != worker_id
        or not job.lease_token
        or not lease_token
        or job.lease_token != lease_token
        or job.lease_expires_at is None
        or _as_utc(job.lease_expires_at) <= _as_utc(now)
    ):
        raise ValueError("ingestion job lease is not owned by worker")
    return job


def _safe_error_message(error: BaseException) -> str:
    """Keep source payload values out of durable operational error records."""
    return f"{error.__class__.__name__}: ingestion failed"


def _as_utc(value: datetime) -> datetime:
    return (
        value.replace(tzinfo=timezone.utc)
        if value.tzinfo is None
        else value.astimezone(timezone.utc)
    )
