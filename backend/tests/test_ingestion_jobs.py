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
        session.add(
            BrokerSource(
                id="source-b",
                broker_id="broker-a",
                tms_type=TmsType.HAULDESK,
                source_name="HaulDesk",
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

    completed = complete_job(
        db_session, job.id, "worker-a", now=NOW, lease_token=claimed.lease_token
    )
    assert completed.status == IngestionJobStatus.SUCCEEDED
    assert completed.lease_owner is None


def test_retryable_failure_backoff_then_dead_letters_permanent_failure(
    db_session: Session,
) -> None:
    job = enqueue(db_session)
    claimed = claim_next_job(db_session, "worker-a", now=NOW)
    retry = fail_job(
        db_session,
        job.id,
        "worker-a",
        ConnectionError("database reset"),
        now=NOW,
        lease_token=claimed.lease_token,
    )
    assert retry.status == IngestionJobStatus.RETRY_WAIT
    retry_available_at = retry.available_at.replace(tzinfo=timezone.utc)
    assert retry_available_at > NOW

    retry.available_at = NOW - timedelta(seconds=1)
    db_session.commit()
    claimed = claim_next_job(db_session, "worker-b", now=NOW)
    dead_letter = fail_job(
        db_session,
        job.id,
        "worker-b",
        ValueError("invalid payload"),
        now=NOW,
        lease_token=claimed.lease_token,
    )
    assert dead_letter.status == IngestionJobStatus.DEAD_LETTER
    assert dead_letter.failure_class == "ValueError"

    replayed = replay_dead_letter(db_session, job.id, now=NOW)
    assert replayed.status == IngestionJobStatus.QUEUED
    assert replayed.attempt_count == 0


def test_worker_lease_can_be_renewed(db_session: Session) -> None:
    job = enqueue(db_session)
    claimed = claim_next_job(db_session, "worker-a", now=NOW)
    renewed = renew_lease(
        db_session,
        job.id,
        "worker-a",
        now=NOW,
        lease_seconds=600,
        lease_token=claimed.lease_token,
    )
    assert renewed.lease_expires_at.replace(tzinfo=timezone.utc) == NOW + timedelta(seconds=600)


def test_source_head_blocks_later_job_but_not_a_different_source(db_session: Session) -> None:
    first = enqueue(db_session, "first.json")
    later = enqueue_job(
        db_session,
        broker_id="broker-a",
        broker_source_id="source-a",
        filename="later.json",
        file_path="/data/later.json",
        checksum="later".ljust(64, "0"),
        synced_at=NOW + timedelta(seconds=1),
        now=NOW + timedelta(seconds=1),
    )
    parallel = enqueue_job(
        db_session,
        broker_id="broker-a",
        broker_source_id="source-b",
        filename="parallel.json",
        file_path="/data/parallel.json",
        checksum="parallel".ljust(64, "0"),
        synced_at=NOW,
        now=NOW,
    )
    first_claim = claim_next_job(db_session, "worker-a", now=NOW)
    assert first_claim.id in {first.id, parallel.id}
    complete_job(
        db_session,
        first_claim.id,
        "worker-a",
        now=NOW,
        lease_token=first_claim.lease_token,
    )
    second_claim = claim_next_job(db_session, "worker-b", now=NOW)
    assert second_claim.id in {first.id, parallel.id}
    complete_job(
        db_session,
        second_claim.id,
        "worker-b",
        now=NOW,
        lease_token=second_claim.lease_token,
    )
    assert claim_next_job(db_session, "worker-c", now=NOW) is None
    later.available_at = NOW
    db_session.commit()
    assert claim_next_job(db_session, "worker-c", now=NOW).id == later.id


def test_expired_lease_reclaim_fences_the_previous_owner(db_session: Session) -> None:
    job = enqueue(db_session)
    first = claim_next_job(db_session, "worker-a", now=NOW, lease_seconds=1)
    old_token = first.lease_token
    second = claim_next_job(db_session, "worker-b", now=NOW + timedelta(seconds=2))

    assert second.id == job.id
    with pytest.raises(ValueError, match="not owned"):
        complete_job(
            db_session,
            job.id,
            "worker-a",
            now=NOW + timedelta(seconds=2),
            lease_token=old_token,
        )


def test_expired_lease_cannot_be_completed_or_renewed(db_session: Session) -> None:
    job = enqueue(db_session)
    claimed = claim_next_job(db_session, "worker-a", now=NOW, lease_seconds=1)

    with pytest.raises(ValueError, match="not owned"):
        complete_job(
            db_session,
            job.id,
            "worker-a",
            now=NOW + timedelta(seconds=2),
            lease_token=claimed.lease_token,
        )
    with pytest.raises(ValueError, match="not owned"):
        renew_lease(
            db_session,
            job.id,
            "worker-a",
            now=NOW + timedelta(seconds=2),
            lease_token=claimed.lease_token,
        )


def test_repeated_expired_leases_dead_letter_after_max_attempts(db_session: Session) -> None:
    job = enqueue(db_session)
    for attempt in range(5):
        claimed = claim_next_job(
            db_session,
            f"worker-{attempt}",
            now=NOW + timedelta(seconds=attempt * 2),
            lease_seconds=1,
        )
        assert claimed is not None
        if attempt < 4:
            assert claimed.attempt_count == attempt + 1

    assert claim_next_job(db_session, "worker-final", now=NOW + timedelta(seconds=10)) is None
    db_session.refresh(job)
    assert job.status == IngestionJobStatus.DEAD_LETTER
    assert job.failure_class == "LeaseExpired"


def test_exhausted_lease_does_not_block_later_source_job(db_session: Session) -> None:
    db_session.autoflush = False
    first = enqueue(db_session, "first.json")
    later = enqueue_job(
        db_session,
        broker_id="broker-a",
        broker_source_id="source-a",
        filename="later.json",
        file_path="/data/later.json",
        checksum="later".ljust(64, "0"),
        synced_at=NOW + timedelta(seconds=1),
        now=NOW,
    )
    claimed = claim_next_job(db_session, "worker-a", now=NOW, lease_seconds=1)
    assert claimed.id == first.id
    first.attempt_count = 5
    first.lease_expires_at = NOW - timedelta(seconds=1)
    db_session.commit()

    next_job = claim_next_job(db_session, "worker-b", now=NOW)

    assert next_job.id == later.id
    db_session.refresh(first)
    assert first.status == IngestionJobStatus.DEAD_LETTER


def test_source_head_uses_sync_time_not_enqueue_time(db_session: Session) -> None:
    late = enqueue_job(
        db_session,
        broker_id="broker-a",
        broker_source_id="source-a",
        filename="late.json",
        file_path="/data/late.json",
        checksum="late".ljust(64, "0"),
        synced_at=NOW + timedelta(seconds=2),
        now=NOW,
    )
    early = enqueue_job(
        db_session,
        broker_id="broker-a",
        broker_source_id="source-a",
        filename="early.json",
        file_path="/data/early.json",
        checksum="early".ljust(64, "0"),
        synced_at=NOW,
        now=NOW,
    )
    early.created_at = NOW + timedelta(seconds=1)
    db_session.commit()

    claimed = claim_next_job(db_session, "worker-a", now=NOW)

    assert claimed.id == early.id
    assert claimed.id != late.id


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
