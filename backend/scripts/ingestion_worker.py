"""Discover and process source files through the durable ingestion job queue."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.database import SessionLocal
from app.ingestion.brokeros import BrokerOSSync
from app.ingestion.brokeros import ingest_file as ingest_brokeros
from app.ingestion.freightflow import FreightFlowSync
from app.ingestion.freightflow import ingest_file as ingest_freightflow
from app.ingestion.hauldesk import HaulDeskSync
from app.ingestion.hauldesk import ingest_file as ingest_hauldesk
from app.ingestion.jobs import claim_next_job, complete_job, enqueue_job, fail_job
from app.models import BrokerSource, IngestionJobStatus, TmsType

SOURCE_CONFIG = (
    ("tms_a_freightflow", "broker-a", "source-a", TmsType.FREIGHTFLOW),
    ("tms_b_hauldesk", "broker-b", "source-b", TmsType.HAULDESK),
    ("tms_c_brokeros", "broker-c", "source-c", TmsType.BROKEROS),
)


def discover_jobs(root: Path) -> int:
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
                raw_contents = path.read_bytes()
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
                    job.error_message = str(error)[:2000]
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


def process_next_job(worker_id: str) -> bool:
    with SessionLocal() as session:
        job = claim_next_job(session, worker_id)
        if job is None:
            return False
        job_id = job.id
        source_id = job.broker_source_id
        path = Path(job.file_path)

    ingest = _ingest_for_source(source_id)
    try:
        with SessionLocal() as session:
            ingest(session, source_id, path)
    except Exception as error:
        with SessionLocal() as session:
            fail_job(session, job_id, worker_id, error)
    else:
        with SessionLocal() as session:
            complete_job(session, job_id, worker_id)
    return True


def run_once(root: Path, worker_id: str) -> tuple[int, int]:
    discovered = discover_jobs(root)
    processed = 0
    while process_next_job(worker_id):
        processed += 1
    return discovered, processed


def _ingest_for_source(source_id: str) -> Callable:
    for _, _, configured_source_id, tms_type in SOURCE_CONFIG:
        if configured_source_id == source_id:
            return {
                TmsType.FREIGHTFLOW: ingest_freightflow,
                TmsType.HAULDESK: ingest_hauldesk,
                TmsType.BROKEROS: ingest_brokeros,
            }[tms_type]
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
    args = parser.parse_args()
    discovered, processed = run_once(args.root, args.worker_id)
    print(f"discovered {discovered} jobs and processed {processed} jobs")


if __name__ == "__main__":
    main()
