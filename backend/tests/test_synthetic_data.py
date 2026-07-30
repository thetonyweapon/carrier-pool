import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.ingestion.brokeros import BrokerOSSync
from app.ingestion.brokeros import ingest_file as ingest_brokeros
from app.ingestion.freightflow import FreightFlowSync
from app.ingestion.freightflow import ingest_file as ingest_freightflow
from app.ingestion.hauldesk import HaulDeskSync
from app.ingestion.hauldesk import ingest_file as ingest_hauldesk
from app.models import (
    Base,
    Broker,
    BrokerSource,
    Carrier,
    Customer,
    IngestionFile,
    Load,
    LoadRateObservation,
    LoadStatus,
    LoadStop,
    LoadVersion,
    RateLineItem,
    RateSide,
    TmsType,
)
from scripts.generate_synthetic_data import DATA_ROOT, generate

ROOT = Path(__file__).resolve().parents[2]
SOURCE_CONFIG = (
    ("tms_a_freightflow", "broker-a", "source-a", TmsType.FREIGHTFLOW),
    ("tms_b_hauldesk", "broker-b", "source-b", TmsType.HAULDESK),
    ("tms_c_brokeros", "broker-c", "source-c", TmsType.BROKEROS),
)


def test_generated_dataset_is_complete_and_schema_valid() -> None:
    for directory_name, _, _, tms_type in SOURCE_CONFIG:
        files = sorted((DATA_ROOT / directory_name).glob("*.json"))
        assert len(files) == 44
        assert [path.name for path in files] == [
            f"2026-07-{day:02d}T{hour:02d}-00_sync.json"
            for day in range(6, 17)
            for hour in (0, 6, 12, 18)
        ]
        previous = None
        for path in files:
            payload = json.loads(path.read_bytes())
            count = len(payload["records"] if tms_type == TmsType.BROKEROS else payload["loads"])
            assert 1 <= count <= 3
            if path.name == "2026-07-16T00-00_sync.json":
                if tms_type == TmsType.FREIGHTFLOW:
                    assert {load["status"] for load in payload["loads"]} == {"Booking"}
                    assert all(load["carrier"] is None for load in payload["loads"])
                elif tms_type == TmsType.HAULDESK:
                    assert {load["status_code"] for load in payload["loads"]} == {20}
                    assert all(load["carrier_ref"] is None for load in payload["loads"])
                else:
                    assert {record["bos__Load_Status__c"] for record in payload["records"]} == {
                        "Ready to Book"
                    }
                    assert all(record["bos__Carrier__c"] is None for record in payload["records"])
            if tms_type == TmsType.FREIGHTFLOW:
                sync = FreightFlowSync.model_validate(payload)
                current = sync.syncedAt
            elif tms_type == TmsType.HAULDESK:
                sync = HaulDeskSync.model_validate(payload)
                current = datetime.strptime(
                    sync.synced_at, "%Y-%m-%d %H:%M:%S"
                ).replace(tzinfo=timezone.utc)
            else:
                sync = BrokerOSSync.model_validate(payload)
                current = sync.synced_at
            assert previous is None or current > previous
            previous = current


def test_generated_dataset_ingests_in_chronological_order() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        for _, broker_id, source_id, tms_type in SOURCE_CONFIG:
            session.add(Broker(id=broker_id, name=broker_id, created_at=datetime.now(timezone.utc)))
            session.add(
                BrokerSource(
                    id=source_id,
                    broker_id=broker_id,
                    tms_type=tms_type,
                    source_name=source_id,
                    created_at=datetime.now(timezone.utc),
                )
            )
        session.commit()

        first_files = []
        for directory_name, _, source_id, tms_type in SOURCE_CONFIG:
            for path in sorted((DATA_ROOT / directory_name).glob("*.json")):
                if tms_type == TmsType.FREIGHTFLOW:
                    result = ingest_freightflow(session, source_id, path)
                elif tms_type == TmsType.HAULDESK:
                    result = ingest_hauldesk(session, source_id, path)
                else:
                    result = ingest_brokeros(session, source_id, path)
                assert result.duplicate is False
            first = sorted((DATA_ROOT / directory_name).glob("*.json"))[0]
            first_files.append((first, source_id, tms_type))

        def counts() -> dict:
            models = (
                IngestionFile,
                Load,
                LoadVersion,
                RateLineItem,
                LoadRateObservation,
            )
            return {model.__name__: len(session.scalars(select(model)).all()) for model in models}

        after_full_ingestion = counts()
        session.rollback()
        for first, source_id, tms_type in first_files:
            if tms_type == TmsType.FREIGHTFLOW:
                duplicate = ingest_freightflow(session, source_id, first)
            elif tms_type == TmsType.HAULDESK:
                duplicate = ingest_hauldesk(session, source_id, first)
            else:
                duplicate = ingest_brokeros(session, source_id, first)
            assert duplicate.duplicate is True
        assert counts() == after_full_ingestion

        assert session.scalar(
            select(IngestionFile).where(IngestionFile.filename.like("2026-07-16%"))
        )
        freightflow_load = session.scalar(
            select(Load).where(Load.broker_source_id == "source-a", Load.source_load_id == "FF-001")
        )
        hauldesk_load = session.scalar(
            select(Load).where(Load.broker_source_id == "source-b", Load.source_load_id == "HD-001")
        )
        brokeros_load = session.scalar(
            select(Load).where(
                Load.broker_source_id == "source-c", Load.source_load_id == "BROKEROS-001"
            )
        )
        assert freightflow_load.status == LoadStatus.COMPLETED
        assert freightflow_load.distance_miles == 246
        assert freightflow_load.customer_rate == 2925
        assert freightflow_load.booked_at is not None
        assert hauldesk_load.status == LoadStatus.COMPLETED
        assert hauldesk_load.distance_miles == 244
        assert hauldesk_load.weight_lbs == 42000
        assert hauldesk_load.customer_rate == 2925
        assert brokeros_load.status == LoadStatus.COMPLETED
        assert brokeros_load.customer_rate == 2925
        assert brokeros_load.weight_lbs == 42000

        hauldesk_rates = session.scalars(
            select(RateLineItem).where(RateLineItem.load_id == hauldesk_load.id)
        ).all()
        assert {(rate.side, rate.code, rate.amount) for rate in hauldesk_rates} >= {
            (RateSide.BILL, "LINEHAUL", 2850),
            (RateSide.PAY, "LINEHAUL", 2200),
            (RateSide.BILL, "ADJUSTMENT", 75),
        }
        brokeros_bill = session.scalars(
            select(LoadRateObservation)
            .where(
                LoadRateObservation.load_id == brokeros_load.id,
                LoadRateObservation.side == RateSide.BILL,
            )
            .order_by(LoadRateObservation.observation_number)
        ).all()
        assert [item.amount for item in brokeros_bill] == [2850, 2925]

        for load in session.scalars(select(Load)).all():
            stops = session.scalars(
                select(LoadStop)
                .where(LoadStop.load_id == load.id)
                .order_by(LoadStop.sequence_number)
            ).all()
            for stop in stops:
                if stop.scheduled_start_at is not None and stop.actual_departed_at is not None:
                    assert stop.actual_departed_at >= stop.scheduled_start_at
                if stop.scheduled_start_at is not None and stop.actual_arrived_at is not None:
                    assert stop.actual_arrived_at >= stop.scheduled_start_at
                if stop.scheduled_date is not None and stop.actual_arrived_at is not None:
                    assert stop.actual_arrived_at.date() >= stop.scheduled_date
            actuals = [stop.actual_arrived_at or stop.actual_departed_at for stop in stops]
            actuals = [value for value in actuals if value is not None]
            assert actuals == sorted(actuals)

        day11_targets = (
            ("source-a", "FF-101", "broker-a"),
            ("source-a", "FF-102", "broker-a"),
            ("source-b", "HD-101", "broker-b"),
            ("source-b", "HD-102", "broker-b"),
            ("source-c", "BROKEROS-101", "broker-c"),
            ("source-c", "BROKEROS-102", "broker-c"),
        )
        for source_id, source_load_id, broker_id in day11_targets:
            target = session.scalar(
                select(Load).where(
                    Load.broker_source_id == source_id, Load.source_load_id == source_load_id
                )
            )
            assert target.broker_id == broker_id
            assert target.status == LoadStatus.ACTIVE
            assert target.carrier_id is None

        source_brokers = {"source-a": "broker-a", "source-b": "broker-b", "source-c": "broker-c"}
        for model in (Customer, Carrier, Load, LoadVersion, RateLineItem, LoadRateObservation):
            for row in session.scalars(select(model)).all():
                assert row.broker_id == source_brokers[row.broker_source_id]
        for stop in session.scalars(select(LoadStop)).all():
            assert stop.broker_id == session.get(Load, stop.load_id).broker_id


def test_generator_is_reproducible(tmp_path: Path) -> None:
    first = generate(tmp_path / "first")
    second = generate(tmp_path / "second")
    first_hashes = {
        path.relative_to(tmp_path / "first"): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in first
    }
    second_hashes = {
        path.relative_to(tmp_path / "second"): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in second
    }
    checked_hashes = {
        path.relative_to(DATA_ROOT): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in DATA_ROOT.glob("tms_*/*.json")
    }
    assert first_hashes == second_hashes == checked_hashes

    sentinel = tmp_path / "first" / "tms_a_freightflow" / "unrelated.json"
    sentinel.write_text("keep me", encoding="utf-8")
    generate(tmp_path / "first")
    assert sentinel.exists()
