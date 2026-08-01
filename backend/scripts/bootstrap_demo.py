"""Create the deterministic demo brokers and ingest their read-only sync files."""

import argparse
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from app.database import SessionLocal
from app.ingestion.brokeros import ingest_file as ingest_brokeros
from app.ingestion.freightflow import ingest_file as ingest_freightflow
from app.ingestion.hauldesk import ingest_file as ingest_hauldesk
from app.models import Broker, BrokerSource, TmsType

SOURCE_CONFIG = (
    ("tms_a_freightflow", "broker-a", "source-a", TmsType.FREIGHTFLOW),
    ("tms_b_hauldesk", "broker-b", "source-b", TmsType.HAULDESK),
    ("tms_c_brokeros", "broker-c", "source-c", TmsType.BROKEROS),
)


def bootstrap(root: Path) -> int:
    with SessionLocal() as session:
        now = datetime.now(timezone.utc)
        for directory_name, broker_id, source_id, tms_type in SOURCE_CONFIG:
            broker = session.get(Broker, broker_id)
            if broker is None:
                session.add(Broker(id=broker_id, name=broker_id, created_at=now))
            source = session.scalar(
                select(BrokerSource).where(
                    BrokerSource.broker_id == broker_id, BrokerSource.id == source_id
                )
            )
            if source is None:
                session.add(
                    BrokerSource(
                        id=source_id,
                        broker_id=broker_id,
                        tms_type=tms_type,
                        source_name=source_id,
                        created_at=now,
                    )
                )
        session.commit()

        ingested = 0
        for directory_name, _, source_id, tms_type in SOURCE_CONFIG:
            directory = root / directory_name
            paths = sorted(directory.glob("*.json"))
            ingest = {
                TmsType.FREIGHTFLOW: ingest_freightflow,
                TmsType.HAULDESK: ingest_hauldesk,
                TmsType.BROKEROS: ingest_brokeros,
            }[tms_type]
            for path in paths:
                result = ingest(session, source_id, path)
                if not result.duplicate:
                    ingested += 1
        return ingested


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("/data"))
    args = parser.parse_args()
    print(f"ingested {bootstrap(args.root)} new demo sync files from {args.root}")


if __name__ == "__main__":
    main()
