"""Discover and process source files through the durable ingestion job queue."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import math
import signal
from datetime import datetime, timezone
from pathlib import Path
from threading import Event, Thread
from typing import Callable, Optional
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.database import SessionLocal
from app.ingestion.brokeros import BrokerOSSync
from app.ingestion.brokeros import ingest_contents as ingest_brokeros
from app.ingestion.common import read_verified_file
from app.ingestion.freightflow import FreightFlowSync
from app.ingestion.freightflow import ingest_contents as ingest_freightflow
from app.ingestion.hauldesk import HaulDeskSync
from app.ingestion.hauldesk import ingest_contents as ingest_hauldesk
from app.ingestion.jobs import (
    DEFAULT_LEASE_SECONDS,
    assert_job_lease,
    claim_next_job,
    complete_job,
    enqueue_job,
    fail_job,
    renew_lease,
)
from app.models import BrokerSource, IngestionJobStatus, TmsType

SOURCE_CONFIG = (
    ("tms_a_freightflow", "broker-a", "source-a", TmsType.FREIGHTFLOW),
    ("tms_b_hauldesk", "broker-b", "source-b", TmsType.HAULDESK),
    ("tms_c_brokeros", "broker-c", "source-c", TmsType.BROKEROS),
)
logger = logging.getLogger(__name__)


def discover_jobs(root: Path) -> int:
    root = _validate_source_root(root)
    discovered = 0
    with SessionLocal() as session:
        for directory_name, broker_id, source_id, tms_type in SOURCE_CONFIG:
            source = session.scalar(
                select(BrokerSource).where(
                    BrokerSource.broker_id == broker_id, BrokerSource.id == source_id
                )
            )
            if source is None:
                raise ValueError(f"configured broker source not found: {source_id}")
            for path in sorted((root / directory_name).glob("*.json")):
                raw_contents = read_verified_file(path, root=root / directory_name)
                checksum = hashlib.sha256(raw_contents).hexdigest()
                try:
                    synced_at = _synced_at(json.loads(raw_contents), tms_type)
                except Exception as error:
                    job = enqueue_job(
                        session,
                        broker_id=broker_id,
                        broker_source_id=source_id,
                        filename=path.name,
                        file_path=path,
                        checksum=checksum,
                        synced_at=datetime.fromtimestamp(path.stat().st_mtime, timezone.utc),
                    )
                    job.status = IngestionJobStatus.DEAD_LETTER
                    job.failure_class = error.__class__.__name__
                    job.error_message = f"{error.__class__.__name__}: ingestion failed"
                    job.completed_at = datetime.now(timezone.utc)
                    session.flush()
                else:
                    enqueue_job(
                        session,
                        broker_id=broker_id,
                        broker_source_id=source_id,
                        filename=path.name,
                        file_path=path,
                        checksum=checksum,
                        synced_at=synced_at,
                    )
                discovered += 1
        session.commit()
    return discovered


def _validate_source_root(root: Path) -> Path:
    if root.is_symlink() or not root.is_dir():
        raise ValueError("ingestion root must be a regular directory")
    resolved_root = root.resolve(strict=True)
    for directory_name, _, _, _ in SOURCE_CONFIG:
        directory = root / directory_name
        if directory.is_symlink() or not directory.is_dir():
            raise ValueError(f"configured ingestion directory is missing: {directory_name}")
        if resolved_root not in directory.resolve(strict=True).parents:
            raise ValueError(f"configured ingestion directory escapes root: {directory_name}")
    return resolved_root


def process_next_job(worker_id: str, root: Path) -> bool:
    root = _validate_source_root(root)
    with SessionLocal() as session:
        job = claim_next_job(session, worker_id)
        if job is None:
            return False
        job_id = job.id
        source_id = job.broker_source_id
        path = Path(job.file_path)
        checksum = job.checksum
        lease_token = job.lease_token

    ingest = _ingest_contents_for_source(source_id)
    stop_heartbeat = Event()

    lease_lost = Event()

    source_root = root / _source_directory(source_id)

    def assert_lease(session) -> None:
        assert_job_lease(session, job_id, worker_id, lease_token)

    def heartbeat() -> None:
        while not stop_heartbeat.wait(DEFAULT_LEASE_SECONDS / 3):
            try:
                with SessionLocal() as heartbeat_session:
                    renew_lease(
                        heartbeat_session,
                        job_id,
                        worker_id,
                        lease_token=lease_token,
                    )
            except ValueError:
                lease_lost.set()
                logger.warning("ingestion lease lost", extra={"job_id": job_id})
                return
            except Exception:
                logger.warning("ingestion lease renewal failed", extra={"job_id": job_id})

    heartbeat_thread = Thread(target=heartbeat, name=f"ingestion-lease-{job_id}", daemon=True)
    heartbeat_thread.start()
    try:
        raw_contents = read_verified_file(path, expected_checksum=checksum, root=source_root)
        with SessionLocal() as session:
            ingest(session, source_id, path.name, raw_contents, before_commit=assert_lease)
    except Exception as error:
        stop_heartbeat.set()
        heartbeat_thread.join()
        if not lease_lost.is_set():
            try:
                with SessionLocal() as session:
                    fail_job(session, job_id, worker_id, error, lease_token=lease_token)
            except ValueError:
                logger.warning("ingestion failure could not be recorded", extra={"job_id": job_id})
    else:
        stop_heartbeat.set()
        heartbeat_thread.join()
        if not lease_lost.is_set():
            try:
                with SessionLocal() as session:
                    complete_job(session, job_id, worker_id, lease_token=lease_token)
            except ValueError:
                logger.warning("ingestion completion was fenced", extra={"job_id": job_id})
    return True


def run_once(root: Path, worker_id: str) -> tuple[int, int]:
    discovered = discover_jobs(root)
    processed = 0
    while process_next_job(worker_id, root):
        processed += 1
    return discovered, processed


def run_forever(
    root: Path,
    worker_id: str,
    poll_interval: float,
    *,
    stop_event: Optional[Event] = None,
) -> None:
    if not math.isfinite(poll_interval) or poll_interval <= 0:
        raise ValueError("poll interval must be greater than zero")
    stop_event = stop_event or Event()
    while not stop_event.is_set():
        try:
            discovered, processed = run_once(root, worker_id)
            logger.info(
                "ingestion poll completed",
                extra={"discovered_jobs": discovered, "processed_jobs": processed},
            )
        except Exception:
            logger.exception("ingestion poll failed")
        stop_event.wait(poll_interval)


def _ingest_contents_for_source(source_id: str) -> Callable:
    for _, _, configured_source_id, tms_type in SOURCE_CONFIG:
        if configured_source_id == source_id:
            return {
                TmsType.FREIGHTFLOW: ingest_freightflow,
                TmsType.HAULDESK: ingest_hauldesk,
                TmsType.BROKEROS: ingest_brokeros,
            }[tms_type]
    raise ValueError(f"unknown broker source: {source_id}")


def _source_directory(source_id: str) -> str:
    for directory_name, _, configured_source_id, _ in SOURCE_CONFIG:
        if configured_source_id == source_id:
            return directory_name
    raise ValueError(f"unknown broker source: {source_id}")


def _synced_at(payload: dict, tms_type: TmsType) -> datetime:
    if tms_type == TmsType.FREIGHTFLOW:
        value = FreightFlowSync.model_validate(payload).syncedAt
        return value.astimezone(timezone.utc)
    if tms_type == TmsType.BROKEROS:
        value = BrokerOSSync.model_validate(payload).synced_at
        return value.astimezone(timezone.utc)
    value = HaulDeskSync.model_validate(payload).synced_at
    return (
        datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
        .replace(tzinfo=ZoneInfo("America/Chicago"))
        .astimezone(timezone.utc)
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("/data"))
    parser.add_argument("--worker-id", default=f"worker-{uuid4()}")
    parser.add_argument("--poll-interval", type=_positive_interval, default=60.0)
    parser.add_argument(
        "--one-shot", action="store_true", help="discover and process once, then exit"
    )
    args = parser.parse_args()
    if not args.one_shot:
        stop_event = Event()

        def request_stop(signum, frame) -> None:
            del frame
            logger.info("stopping ingestion worker", extra={"signal": signum})
            stop_event.set()

        signal.signal(signal.SIGINT, request_stop)
        signal.signal(signal.SIGTERM, request_stop)
        run_forever(args.root, args.worker_id, args.poll_interval, stop_event=stop_event)
    else:
        discovered, processed = run_once(args.root, args.worker_id)
        print(f"discovered {discovered} jobs and processed {processed} jobs")


def _positive_interval(value: str) -> float:
    try:
        interval = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "poll interval must be finite and greater than zero"
        ) from exc
    if not math.isfinite(interval) or interval <= 0:
        raise argparse.ArgumentTypeError("poll interval must be finite and greater than zero")
    return interval


if __name__ == "__main__":
    main()
