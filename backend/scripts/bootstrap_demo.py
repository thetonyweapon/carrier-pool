"""Create the deterministic demo brokers and ingest their read-only sync files."""

import argparse
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from app.database import SessionLocal
from app.ingestion.brokeros import ingest_file as ingest_brokeros
from app.ingestion.freightflow import ingest_file as ingest_freightflow
from app.ingestion.hauldesk import ingest_file as ingest_hauldesk
from app.models import Broker, BrokerSource, SharedPoolPolicy, TmsType
from app.shared_carrier_pool import set_shared_pool_policy

SOURCE_CONFIG = (
    (
        "tms_a_freightflow",
        "broker-a",
        "Ithaca Freight Partners",
        "source-a",
        "FreightFlow",
        TmsType.FREIGHTFLOW,
    ),
    (
        "tms_b_hauldesk",
        "broker-b",
        "Aegean Route Logistics",
        "source-b",
        "HaulDesk",
        TmsType.HAULDESK,
    ),
    (
        "tms_c_brokeros",
        "broker-c",
        "Olive Harbor Transport",
        "source-c",
        "BrokerOS",
        TmsType.BROKEROS,
    ),
)


def bootstrap(root: Path) -> int:
    with SessionLocal() as session:
        now = datetime.now(timezone.utc)
        desired_broker_names = {
            broker_name: broker_id for _, broker_id, broker_name, _, _, _ in SOURCE_CONFIG
        }
        if len(desired_broker_names) != len(SOURCE_CONFIG):
            raise ValueError("Demo broker configuration contains duplicate display names")

        existing_brokers = session.scalars(select(Broker)).all()
        for broker_name, broker_id in desired_broker_names.items():
            collision = next(
                (broker for broker in existing_brokers if broker.name == broker_name), None
            )
            if collision is not None and collision.id != broker_id:
                raise ValueError(
                    f"Demo broker name collision: {broker_name!r} is already used by "
                    f"broker {collision.id!r}, not {broker_id!r}"
                )

        for _, broker_id, _, source_id, _, tms_type in SOURCE_CONFIG:
            source = session.get(BrokerSource, source_id)
            if source is not None:
                if source.broker_id != broker_id:
                    raise ValueError(
                        f"Demo source {source_id!r} belongs to broker {source.broker_id!r}; "
                        f"expected {broker_id!r}"
                    )
                if source.tms_type != tms_type:
                    raise ValueError(
                        f"Demo source {source_id!r} is configured for "
                        f"{source.tms_type.value!r}; expected {tms_type.value!r}"
                    )
            else:
                conflicting_source = session.scalar(
                    select(BrokerSource).where(
                        BrokerSource.broker_id == broker_id,
                        BrokerSource.tms_type == tms_type,
                    )
                )
                if conflicting_source is not None:
                    raise ValueError(
                        f"Broker {broker_id!r} already has TMS source "
                        f"{conflicting_source.id!r} for {tms_type.value!r}; "
                        f"expected source {source_id!r}"
                    )

        for _, broker_id, broker_name, source_id, source_name, tms_type in SOURCE_CONFIG:
            broker = session.get(Broker, broker_id)
            if broker is None:
                session.add(Broker(id=broker_id, name=broker_name, created_at=now))
            elif broker.name == broker_id:
                broker.name = broker_name

            source = session.get(BrokerSource, source_id)
            if source is None:
                session.add(
                    BrokerSource(
                        id=source_id,
                        broker_id=broker_id,
                        tms_type=tms_type,
                        source_name=source_name,
                        created_at=now,
                    )
                )
            elif source.source_name == source_id:
                source.source_name = source_name
            if (
                session.scalar(
                    select(SharedPoolPolicy).where(SharedPoolPolicy.broker_id == broker_id)
                )
                is None
            ):
                set_shared_pool_policy(
                    session,
                    broker_id,
                    enabled=True,
                    changed_by="demo-bootstrap",
                    reason="demo broker opted into shared carrier pool",
                )
        session.commit()

        ingested = 0
        for directory_name, _, _, source_id, _, tms_type in SOURCE_CONFIG:
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
