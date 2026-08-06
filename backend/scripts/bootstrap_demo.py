"""Create the deterministic demo brokers and ingest their read-only sync files."""

import argparse
import hashlib
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import delete, select

from app.database import SessionLocal
from app.ingestion.brokeros import ingest_file as ingest_brokeros
from app.ingestion.freightflow import ingest_file as ingest_freightflow
from app.ingestion.hauldesk import ingest_file as ingest_hauldesk
from app.models import (
    Broker,
    BrokerSource,
    Carrier,
    CarrierIdentity,
    Customer,
    IngestionFile,
    IngestionJob,
    IngestionStatus,
    Load,
    LoadRateObservation,
    LoadStop,
    LoadVersion,
    PlatformAssignment,
    PlatformAssignmentEvent,
    RateLineItem,
    SharedPoolPolicy,
    SharedPoolQueryAudit,
    TmsType,
)
from app.shared_carrier_pool import set_shared_display_name, set_shared_pool_policy

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
LOCAL_BROKER = ("broker-local", "Local Sandbox Brokerage")


def _reset_demo_source(session, source_id: str) -> None:
    """Remove source-derived demo data before re-ingesting a changed seed."""
    session.execute(
        delete(PlatformAssignmentEvent).where(
            PlatformAssignmentEvent.broker_id.in_(
                select(BrokerSource.broker_id).where(BrokerSource.id == source_id)
            )
        )
    )
    session.execute(
        delete(PlatformAssignment).where(
            PlatformAssignment.broker_id.in_(
                select(BrokerSource.broker_id).where(BrokerSource.id == source_id)
            )
        )
    )
    session.execute(
        delete(SharedPoolQueryAudit).where(
            SharedPoolQueryAudit.broker_id.in_(
                select(BrokerSource.broker_id).where(BrokerSource.id == source_id)
            )
        )
    )
    for model in (LoadRateObservation, LoadVersion, RateLineItem):
        session.execute(delete(model).where(model.broker_source_id == source_id))
    session.execute(
        delete(LoadStop).where(
            LoadStop.load_id.in_(select(Load.id).where(Load.broker_source_id == source_id))
        )
    )
    session.execute(delete(Load).where(Load.broker_source_id == source_id))
    session.execute(delete(Carrier).where(Carrier.broker_source_id == source_id))
    session.execute(delete(Customer).where(Customer.broker_source_id == source_id))
    session.execute(delete(IngestionJob).where(IngestionJob.broker_source_id == source_id))
    session.execute(delete(IngestionFile).where(IngestionFile.broker_source_id == source_id))
    session.flush()


def _demo_source_needs_reseed(session, source_id: str, paths: list[Path]) -> bool:
    for path in paths:
        existing = session.scalar(
            select(IngestionFile).where(
                IngestionFile.broker_source_id == source_id,
                IngestionFile.filename == path.name,
            )
        )
        if existing is not None and existing.status == IngestionStatus.SUCCEEDED:
            if existing.checksum != hashlib.sha256(path.read_bytes()).hexdigest():
                return True
    return False


def bootstrap(root: Path) -> int:
    with SessionLocal() as session:
        now = datetime.now(timezone.utc)
        desired_broker_names = {
            broker_name: broker_id for _, broker_id, broker_name, _, _, _ in SOURCE_CONFIG
        }
        if len(desired_broker_names) != len(SOURCE_CONFIG):
            raise ValueError("Demo broker configuration contains duplicate display names")

        existing_brokers = session.scalars(select(Broker)).all()
        broker_names = {**desired_broker_names, LOCAL_BROKER[1]: LOCAL_BROKER[0]}
        for broker_name, broker_id in broker_names.items():
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
                session.add(Broker(id=broker_id, name=broker_name, is_demo=True, created_at=now))
            elif broker.name == broker_id:
                broker.name = broker_name
            broker = session.get(Broker, broker_id)
            if broker is not None:
                broker.is_demo = True

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
        local_broker = session.get(Broker, LOCAL_BROKER[0])
        if local_broker is None:
            session.add(
                Broker(
                    id=LOCAL_BROKER[0],
                    name=LOCAL_BROKER[1],
                    is_demo=False,
                    created_at=now,
                )
            )
        else:
            local_broker.name = LOCAL_BROKER[1]
            local_broker.is_demo = False
        session.commit()

        ingested = 0
        for directory_name, _, _, source_id, _, tms_type in SOURCE_CONFIG:
            directory = root / directory_name
            paths = sorted(directory.glob("*.json"))
            if _demo_source_needs_reseed(session, source_id, paths):
                _reset_demo_source(session, source_id)
            session.commit()
            ingest = {
                TmsType.FREIGHTFLOW: ingest_freightflow,
                TmsType.HAULDESK: ingest_hauldesk,
                TmsType.BROKEROS: ingest_brokeros,
            }[tms_type]
            for path in paths:
                result = ingest(session, source_id, path)
                if not result.duplicate:
                    ingested += 1
        demo_broker_ids = {item[1] for item in SOURCE_CONFIG}
        identities = session.scalars(
            select(CarrierIdentity)
            .join(Broker, Broker.id == CarrierIdentity.broker_id)
            .where(
                CarrierIdentity.broker_id.in_(demo_broker_ids),
                Broker.is_demo.is_(True),
            )
            .order_by(CarrierIdentity.broker_id, CarrierIdentity.id)
        ).all()
        for identity in identities:
            if (
                identity.shared_display_name
                or identity.shared_display_name_bootstrap_owned is False
            ):
                continue
            carrier = session.scalar(
                select(Carrier)
                .where(
                    Carrier.broker_id == identity.broker_id,
                    Carrier.carrier_identity_id == identity.id,
                )
                .order_by(Carrier.updated_at.desc(), Carrier.id)
            )
            if carrier is not None:
                set_shared_display_name(
                    session,
                    identity.broker_id,
                    identity.id,
                    carrier.name,
                    bootstrap_owned=True,
                )
        session.commit()
        return ingested


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("/data"))
    args = parser.parse_args()
    print(f"ingested {bootstrap(args.root)} new demo sync files from {args.root}")


if __name__ == "__main__":
    main()
