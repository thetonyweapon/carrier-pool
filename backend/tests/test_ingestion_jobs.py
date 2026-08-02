from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.ingestion.jobs import (
    claim_next_job,
    complete_job,
    enqueue_job,
    fail_job,
    is_retryable,
    renew_lease,
    replay_dead_letter,
)
from app.models import Base, Broker, BrokerSource, IngestionJobStatus, TmsType

NOW = datetime(2026, 8, 1, 12, tzinfo=timezone.utc)


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Broker(id="broker-a", name="Broker A", created_at=NOW))
        session.add(
            BrokerSource(
                id="source-a",
                broker_id="broker-a",
                tms_type=TmsType.FREIGHTFLOW,
                source_name="FreightFlow",
                created_at=NOW,
            )
        )
        session.commit()
        yield session
    engine.dispose()


def enqueue(db_session: Session, filename: str = "sync.json"):
    return enqueue_job(
        db_session,
        broker_id="broker-a",
        broker_source_id="source-a",
        filename=filename,
        file_path=f"/data/{filename}",
        checksum=filename.ljust(64, "0")[:64],
        synced_at=NOW,
        now=NOW,
    )


def test_job_claim_lease_and_completion_are_durable(db_session: Session) -> None:
    job = enqueue(db_session)
    claimed = claim_next_job(db_session, "worker-a", now=NOW)
    assert claimed.id == job.id
    assert claimed.status == IngestionJobStatus.PROCESSING
    assert claimed.attempt_count == 1
    assert claim_next_job(db_session, "worker-b", now=NOW) is None

    completed = complete_job(db_session, job.id, "worker-a", now=NOW)
    assert completed.status == IngestionJobStatus.SUCCEEDED
    assert completed.lease_owner is None


def test_retryable_failure_backoff_then_dead_letters_permanent_failure(
    db_session: Session,
) -> None:
    job = enqueue(db_session)
    claim_next_job(db_session, "worker-a", now=NOW)
    retry = fail_job(db_session, job.id, "worker-a", ConnectionError("database reset"), now=NOW)
    assert retry.status == IngestionJobStatus.RETRY_WAIT
    retry_available_at = retry.available_at.replace(tzinfo=timezone.utc)
    assert retry_available_at > NOW

    retry.available_at = NOW - timedelta(seconds=1)
    db_session.commit()
    claim_next_job(db_session, "worker-b", now=NOW)
    dead_letter = fail_job(db_session, job.id, "worker-b", ValueError("invalid payload"), now=NOW)
    assert dead_letter.status == IngestionJobStatus.DEAD_LETTER
    assert dead_letter.failure_class == "ValueError"

    replayed = replay_dead_letter(db_session, job.id, now=NOW)
    assert replayed.status == IngestionJobStatus.QUEUED
    assert replayed.attempt_count == 0


def test_worker_lease_can_be_renewed(db_session: Session) -> None:
    job = enqueue(db_session)
    claim_next_job(db_session, "worker-a", now=NOW)
    renewed = renew_lease(db_session, job.id, "worker-a", now=NOW, lease_seconds=600)
    assert renewed.lease_expires_at.replace(tzinfo=timezone.utc) == NOW + timedelta(seconds=600)


def test_job_checksum_conflict_is_rejected(db_session: Session) -> None:
    first = enqueue(db_session)
    assert enqueue(db_session).id == first.id
    with pytest.raises(ValueError, match="checksum conflict"):
        enqueue_job(
            db_session,
            broker_id="broker-a",
            broker_source_id="source-a",
            filename="sync.json",
            file_path="/data/sync.json",
            checksum="different".ljust(64, "0"),
            synced_at=NOW,
            now=NOW,
        )


def test_integrity_errors_are_not_retryable() -> None:
    assert is_retryable(IntegrityError("constraint", {}, Exception())) is False
