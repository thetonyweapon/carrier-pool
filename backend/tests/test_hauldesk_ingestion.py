import json
import os
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Optional
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.ingestion.common import upsert_carrier_identity
from app.ingestion.hauldesk import (
    ConflictingHaulDeskFileError,
    InvalidHaulDeskPayloadError,
    OutOfOrderHaulDeskFileError,
    _map_equipment,
    _map_status,
    _parse_central_datetime,
    ingest_contents,
    ingest_file,
)
from app.models import (
    Base,
    Broker,
    BrokerSource,
    Carrier,
    CarrierIdentity,
    Customer,
    EquipmentType,
    IngestionFile,
    Load,
    LoadStatus,
    LoadStop,
    LoadVersion,
    RateLineItem,
    TmsType,
)


def make_sync(
    synced_at: str = "2026-07-06 06:00:00",
    status_code: int = 30,
    carrier_ref: Optional[int] = 66861,
    load_num: str = "HD-2026-004417",
    updated_at: str = "2026-07-06 03:45:33",
    delivery_city: str = "Pasadena",
) -> dict:
    return {
        "synced_at": synced_at,
        "loads": [
            {
                "load_num": load_num,
                "status_code": status_code,
                "customer_code": "C-0031",
                "customer_name": "Alamo Building Supply",
                "carrier_ref": carrier_ref,
                "equip": "V",
                "weight_kg": 10886.2,
                "dist_km": 389.6,
                "pu_city": "New Braunfels",
                "pu_state": "TX",
                "pu_zip": "78130",
                "pu_date": "2026-07-07",
                "pu_departed_at": None,
                "del_city": delivery_city,
                "del_state": "TX",
                "del_zip": "77502",
                "del_date": "2026-07-08",
                "del_arrived_at": None,
                "entered_at": "2026-07-05 14:22:10",
                "updated_at": updated_at,
            }
        ],
        "carriers": [
            {
                "carrier_id": 66861,
                "carrier_name": "DELTA PRIME LLC",
                "mc_no": "884201",
                "dot_no": "2551377",
                "home_city": "Seguin",
                "home_state": "TX",
                "phone": "(830) 555-0144",
            }
        ],
        "rates": [
            {
                "rate_id": 910233,
                "load_num": load_num,
                "side": "pay",
                "code": "LINEHAUL",
                "amount_usd": 1035.00,
                "created_at": "2026-07-06 03:45:33",
            },
            {
                "rate_id": 910234,
                "load_num": load_num,
                "side": "bill",
                "code": "LINEHAUL",
                "amount_usd": 1310.00,
                "created_at": "2026-07-06 03:45:33",
            },
        ],
    }


def contents(payload: dict) -> bytes:
    return json.dumps(payload, separators=(",", ":")).encode()


@pytest.fixture
def db_session():
    engine = create_engine("sqlite+pysqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, connection_record) -> None:
        del connection_record
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Broker(id="broker-a", name="Broker A", created_at=datetime.now(timezone.utc)))
        session.add(
            BrokerSource(
                id="hauldesk-a",
                broker_id="broker-a",
                tms_type=TmsType.HAULDESK,
                source_name="HaulDesk A",
                created_at=datetime.now(timezone.utc),
            )
        )
        session.add(
            BrokerSource(
                id="freightflow-a",
                broker_id="broker-a",
                tms_type=TmsType.FREIGHTFLOW,
                source_name="FreightFlow A",
                created_at=datetime.now(timezone.utc),
            )
        )
        session.commit()
        yield session
    engine.dispose()


def test_ingests_flat_hauldesk_snapshot_and_normalizes_units(db_session: Session) -> None:
    result = ingest_contents(
        db_session,
        "hauldesk-a",
        "2026-07-06T06-00_sync.json",
        contents(make_sync()),
    )

    load = db_session.scalar(select(Load))
    carrier = db_session.scalar(select(Carrier))
    customer = db_session.scalar(select(Customer))
    stops = db_session.scalars(select(LoadStop).order_by(LoadStop.sequence_number)).all()
    version = db_session.scalar(select(LoadVersion))
    ingestion_file = db_session.scalar(select(IngestionFile))

    assert result.processed_loads == 1
    assert load.status == LoadStatus.COVERED
    assert load.equipment_type == EquipmentType.DRY_VAN
    assert load.weight_lbs == Decimal("24000.0")
    assert load.distance_miles == Decimal("242.1")
    assert load.customer_rate == Decimal("1310.00")
    assert load.carrier_rate == Decimal("1035.00")
    assert load.booked_at.replace(tzinfo=timezone.utc) == datetime(
        2026, 7, 6, 8, 45, 33, tzinfo=timezone.utc
    )
    assert carrier.home_city == "Seguin"
    identity = db_session.scalar(select(CarrierIdentity))
    assert carrier.carrier_identity_id == identity.id
    assert identity.normalized_mc_number == "884201"
    assert identity.normalized_dot_number == "2551377"
    assert customer.name == "Alamo Building Supply"
    assert [stop.stop_type.value for stop in stops] == ["pickup", "dropoff"]
    assert stops[0].scheduled_start_at.replace(tzinfo=timezone.utc) == datetime(
        2026, 7, 7, 5, tzinfo=timezone.utc
    )
    assert version.ingestion_file_id == ingestion_file.id
    assert version.raw_payload["load"]["load_num"] == "HD-2026-004417"
    assert len(version.raw_payload["rates"]) == 2
    assert version.normalized_snapshot["planned_pickup_date"] == "2026-07-07"
    assert version.normalized_snapshot["stops"][1]["actual_arrived_at"] is None


def test_rate_only_delta_appends_journal_recalculates_and_versions(db_session: Session) -> None:
    ingest_contents(
        db_session,
        "hauldesk-a",
        "2026-07-06T06-00_sync.json",
        contents(make_sync()),
    )
    rate_only = {
        "synced_at": "2026-07-06 12:00:00",
        "loads": [],
        "carriers": [],
        "rates": [
            {
                "rate_id": 910235,
                "load_num": "HD-2026-004417",
                "side": "bill",
                "code": "FUEL",
                "amount_usd": 45.50,
                "created_at": "2026-07-06 11:45:00",
            },
            {
                "rate_id": 910236,
                "load_num": "HD-2026-004417",
                "side": "pay",
                "code": "ADJUSTMENT",
                "amount_usd": -35.00,
                "created_at": "2026-07-06 11:45:01",
            },
        ],
    }

    result = ingest_contents(
        db_session,
        "hauldesk-a",
        "2026-07-06T12-00_sync.json",
        contents(rate_only),
    )

    load = db_session.scalar(select(Load))
    versions = db_session.scalars(select(LoadVersion).order_by(LoadVersion.version_number)).all()
    assert result.processed_loads == 0
    assert load.customer_rate == Decimal("1355.50")
    assert load.carrier_rate == Decimal("1000.00")
    assert load.last_synced_at.replace(tzinfo=timezone.utc) == datetime(
        2026, 7, 6, 17, tzinfo=timezone.utc
    )
    assert len(db_session.scalars(select(RateLineItem)).all()) == 4
    assert len(versions) == 2
    assert versions[1].raw_payload == {"load": None, "rates": rate_only["rates"]}


def test_load_correction_preserves_stop_ids_and_updates_actual_events(db_session: Session) -> None:
    ingest_contents(
        db_session,
        "hauldesk-a",
        "2026-07-06T06-00_sync.json",
        contents(make_sync(status_code=20, carrier_ref=None)),
    )
    original_ids = {
        stop.sequence_number: stop.id for stop in db_session.scalars(select(LoadStop)).all()
    }
    db_session.rollback()
    corrected = make_sync(
        synced_at="2026-07-06 12:00:00",
        status_code=40,
        updated_at="2026-07-06 11:45:00",
        delivery_city="Houston",
    )
    corrected["loads"][0]["pu_departed_at"] = "2026-07-07 10:15:00"
    corrected["loads"][0]["del_arrived_at"] = "2026-07-08 15:30:00"
    corrected["rates"] = []
    ingest_contents(
        db_session,
        "hauldesk-a",
        "2026-07-06T12-00_sync.json",
        contents(corrected),
    )

    stops = db_session.scalars(select(LoadStop).order_by(LoadStop.sequence_number)).all()
    load = db_session.scalar(select(Load))
    assert {stop.sequence_number: stop.id for stop in stops} == original_ids
    assert stops[0].actual_departed_at.replace(tzinfo=timezone.utc) == datetime(
        2026, 7, 7, 15, 15, tzinfo=timezone.utc
    )
    assert stops[1].actual_arrived_at.replace(tzinfo=timezone.utc) == datetime(
        2026, 7, 8, 20, 30, tzinfo=timezone.utc
    )
    assert stops[1].city == "Houston"
    assert load.booked_at.replace(tzinfo=timezone.utc) == datetime(
        2026, 7, 6, 16, 45, tzinfo=timezone.utc
    )
    later = make_sync(
        synced_at="2026-07-06 18:00:00",
        status_code=50,
        updated_at="2026-07-06 17:45:00",
    )
    later["rates"] = []
    db_session.rollback()
    ingest_contents(db_session, "hauldesk-a", "2026-07-06T18-00_sync.json", contents(later))
    assert db_session.scalar(select(Load)).booked_at.replace(tzinfo=timezone.utc) == datetime(
        2026, 7, 6, 16, 45, tzinfo=timezone.utc
    )


def test_rejects_unknown_carrier_and_duplicate_rate_without_partial_writes(
    db_session: Session,
) -> None:
    unknown_carrier = make_sync(carrier_ref=99999)
    unknown_carrier["carriers"] = []
    with pytest.raises(InvalidHaulDeskPayloadError, match="unknown carrier"):
        ingest_contents(
            db_session,
            "hauldesk-a",
            "unknown.json",
            contents(unknown_carrier),
        )
    assert db_session.scalars(select(Load)).all() == []
    assert db_session.scalars(select(Carrier)).all() == []
    db_session.rollback()

    first = make_sync()
    first["rates"] = [first["rates"][0]]
    ingest_contents(db_session, "hauldesk-a", "first.json", contents(first))
    duplicate = make_sync(synced_at="2026-07-06 12:00:00")
    with pytest.raises(InvalidHaulDeskPayloadError, match="already ingested"):
        ingest_contents(
            db_session,
            "hauldesk-a",
            "duplicate.json",
            contents(duplicate),
        )
    assert len(db_session.scalars(select(RateLineItem)).all()) == 1
    assert len(db_session.scalars(select(IngestionFile)).all()) == 1


def test_file_idempotency_ordering_and_source_type_validation(db_session: Session) -> None:
    raw = contents(make_sync())
    first = ingest_contents(db_session, "hauldesk-a", "same.json", raw)
    duplicate = ingest_contents(db_session, "hauldesk-a", "same.json", raw)
    assert first.duplicate is False
    assert duplicate.duplicate is True

    with pytest.raises(ConflictingHaulDeskFileError):
        ingest_contents(
            db_session,
            "hauldesk-a",
            "same.json",
            contents(make_sync(delivery_city="Austin")),
        )
    with pytest.raises(OutOfOrderHaulDeskFileError):
        ingest_contents(
            db_session,
            "hauldesk-a",
            "older.json",
            contents(make_sync(synced_at="2026-07-06 05:00:00")),
        )


def test_mapping_and_central_dst_validation() -> None:
    assert _map_status(10) == LoadStatus.PLANNED
    assert _map_status(90) == LoadStatus.COMPLETED
    assert _map_equipment("V") == EquipmentType.DRY_VAN
    assert _map_equipment("R") == EquipmentType.REEFER
    assert _map_equipment("F") == EquipmentType.FLATBED
    assert _map_equipment("X") == EquipmentType.UNKNOWN
    assert _parse_central_datetime("2026-01-15 06:00:00", "timestamp") == datetime(
        2026, 1, 15, 12, tzinfo=timezone.utc
    )
    with pytest.raises(InvalidHaulDeskPayloadError, match="ambiguous"):
        _parse_central_datetime("2026-11-01 01:30:00", "timestamp")
    with pytest.raises(InvalidHaulDeskPayloadError, match="nonexistent|ambiguous"):
        _parse_central_datetime("2026-03-08 02:30:00", "timestamp")


def test_ingest_file_reports_missing_file(db_session: Session, tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        ingest_file(db_session, "hauldesk-a", tmp_path / "missing.json")


def test_ingests_multiple_loads_with_isolated_rates_and_shared_entities(
    db_session: Session,
) -> None:
    payload = make_sync()
    second = make_sync(load_num="HD-2026-004418", delivery_city="Houston")
    second["rates"][0]["rate_id"] = 920233
    second["rates"][1]["rate_id"] = 920234
    payload["loads"].append(second["loads"][0])
    payload["rates"].extend(second["rates"])

    result = ingest_contents(
        db_session,
        "hauldesk-a",
        "multi-load.json",
        contents(payload),
    )

    loads = db_session.scalars(select(Load).order_by(Load.source_load_id)).all()
    versions = db_session.scalars(select(LoadVersion)).all()
    assert result.processed_loads == 2
    assert len(loads) == 2
    assert [load.carrier_rate for load in loads] == [Decimal("1035.00"), Decimal("1035.00")]
    assert [load.customer_rate for load in loads] == [Decimal("1310.00"), Decimal("1310.00")]
    assert len(versions) == 2
    assert len(db_session.scalars(select(LoadStop)).all()) == 4
    assert len(db_session.scalars(select(Customer)).all()) == 1
    assert len(db_session.scalars(select(Carrier)).all()) == 1


def test_zero_sum_rate_correction_is_stored_as_zero_not_null(db_session: Session) -> None:
    initial = make_sync()
    initial["rates"] = [initial["rates"][0]]
    ingest_contents(db_session, "hauldesk-a", "zero-start.json", contents(initial))

    correction = {
        "synced_at": "2026-07-06 12:00:00",
        "loads": [],
        "carriers": [],
        "rates": [
            {
                "rate_id": 910237,
                "load_num": "HD-2026-004417",
                "side": "pay",
                "code": "ADJUSTMENT",
                "amount_usd": -1035.00,
                "created_at": "2026-07-06 11:45:00",
            }
        ],
    }
    ingest_contents(db_session, "hauldesk-a", "zero-correction.json", contents(correction))

    load = db_session.scalar(select(Load))
    versions = db_session.scalars(select(LoadVersion).order_by(LoadVersion.version_number)).all()
    assert load.carrier_rate == Decimal("0.00")
    assert versions[-1].normalized_snapshot["carrier_rate"] == "0.00"


def test_carrier_identity_normalizes_mc_and_dot_across_sources(db_session: Session) -> None:
    first = upsert_carrier_identity(
        db_session,
        "broker-a",
        "MC-884201",
        "DOT 2551377",
        datetime(2026, 7, 6, tzinfo=timezone.utc),
    )
    second = upsert_carrier_identity(
        db_session,
        "broker-a",
        "884201",
        "2551377",
        datetime(2026, 7, 7, tzinfo=timezone.utc),
    )

    assert first.id == second.id
    assert len(db_session.scalars(select(CarrierIdentity)).all()) == 1


def test_freightflow_and_hauldesk_carriers_share_broker_identity(db_session: Session) -> None:
    from app.ingestion.freightflow import ingest_contents as ingest_freightflow

    freightflow_payload = {
        "syncedAt": "2026-07-06T06:00:00-05:00",
        "loads": [
            {
                "shipmentId": "FF-1",
                "status": "Dispatched",
                "mileage": 100.0,
                "totalSell": 1000.00,
                "totalBuy": 800.00,
                "customer": {"customerId": "FF-C", "name": "Customer"},
                "carrier": {
                    "carrierMasterId": "FF-CARRIER",
                    "name": "Delta Prime",
                    "mcNumber": "MC-884201",
                    "dotNumber": "DOT 2551377",
                },
                "equipment": "Van",
                "weightTotal": 1000.0,
                "stops": [
                    {
                        "stopType": "First Pickup",
                        "city": "Austin",
                        "state": "TX",
                        "zipCode": "78701",
                    },
                    {"stopType": "Last Drop", "city": "Houston", "state": "TX", "zipCode": "77001"},
                ],
                "createdDate": "2026-07-06T05:00:00-05:00",
                "lastModifiedDate": "2026-07-06T05:30:00-05:00",
            }
        ],
    }
    ingest_freightflow(
        db_session, "freightflow-a", "freightflow.json", json.dumps(freightflow_payload).encode()
    )
    ingest_contents(db_session, "hauldesk-a", "hauldesk.json", contents(make_sync()))
    carriers = db_session.scalars(select(Carrier).order_by(Carrier.broker_source_id)).all()
    assert len(carriers) == 2
    assert carriers[0].carrier_identity_id == carriers[1].carrier_identity_id
    assert len(db_session.scalars(select(CarrierIdentity)).all()) == 1


def test_carrier_identity_normalization_rejects_malformed_values() -> None:
    from app.ingestion.common import normalize_carrier_identifier

    assert normalize_carrier_identifier(" MC-000884201 ") == "884201"
    assert normalize_carrier_identifier("DOT 002551377") == "2551377"
    assert normalize_carrier_identifier("unknown") is None
    assert normalize_carrier_identifier("MC-12A") is None
    assert normalize_carrier_identifier("DOT-0000") is None
    assert normalize_carrier_identifier(None) is None


def test_complementary_identities_merge_and_repoint_carriers(db_session: Session) -> None:
    from app.ingestion.common import upsert_carrier_identity

    mc_only = upsert_carrier_identity(
        db_session, "broker-a", "MC-884201", None, datetime(2026, 7, 6, tzinfo=timezone.utc)
    )
    dot_only = upsert_carrier_identity(
        db_session, "broker-a", None, "DOT-2551377", datetime(2026, 7, 6, tzinfo=timezone.utc)
    )
    db_session.add(
        Carrier(
            broker_id="broker-a",
            broker_source_id="hauldesk-a",
            carrier_identity_id=dot_only.id,
            source_carrier_id="carrier-dot",
            name="Delta Prime",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
    )
    db_session.flush()

    merged = upsert_carrier_identity(
        db_session,
        "broker-a",
        "884201",
        "2551377",
        datetime(2026, 7, 7, tzinfo=timezone.utc),
    )
    db_session.expire_all()
    assert merged.id == mc_only.id
    assert db_session.get(CarrierIdentity, dot_only.id) is None
    assert (
        db_session.scalar(
            select(Carrier).where(Carrier.source_carrier_id == "carrier-dot")
        ).carrier_identity_id
        == mc_only.id
    )
    assert merged.normalized_mc_number == "884201"
    assert merged.normalized_dot_number == "2551377"


def test_conflicting_identity_pair_rejects_without_partial_writes(db_session: Session) -> None:
    from app.ingestion.common import CarrierIdentityConflictError, upsert_carrier_identity

    upsert_carrier_identity(
        db_session, "broker-a", "884201", "2551377", datetime(2026, 7, 6, tzinfo=timezone.utc)
    )
    db_session.commit()
    with pytest.raises(CarrierIdentityConflictError):
        upsert_carrier_identity(
            db_session, "broker-a", "884201", "9999999", datetime(2026, 7, 7, tzinfo=timezone.utc)
        )
    db_session.rollback()
    identity = db_session.scalar(select(CarrierIdentity))
    assert (identity.normalized_mc_number, identity.normalized_dot_number) == ("884201", "2551377")


def test_empty_delta_does_not_create_versions_or_change_loads(db_session: Session) -> None:
    ingest_contents(
        db_session,
        "hauldesk-a",
        "first.json",
        contents(make_sync(status_code=20, carrier_ref=None)),
    )
    load = db_session.scalar(select(Load))
    original_last_synced = load.last_synced_at
    db_session.rollback()
    result = ingest_contents(
        db_session,
        "hauldesk-a",
        "empty.json",
        contents({"synced_at": "2026-07-06 12:00:00", "loads": [], "carriers": [], "rates": []}),
    )
    db_session.expire_all()
    assert result.processed_loads == 0
    assert db_session.scalar(select(Load)).last_synced_at == original_last_synced
    assert len(db_session.scalars(select(LoadVersion)).all()) == 1


def test_new_rate_event_with_same_amount_is_not_deduplicated(db_session: Session) -> None:
    initial = make_sync()
    initial["rates"] = [initial["rates"][0]]
    ingest_contents(db_session, "hauldesk-a", "first.json", contents(initial))
    follow_up = {
        "synced_at": "2026-07-06 12:00:00",
        "loads": [],
        "carriers": [],
        "rates": [
            {
                "rate_id": 910999,
                "load_num": "HD-2026-004417",
                "side": "pay",
                "code": "ADJUSTMENT",
                "amount_usd": 1035.00,
                "created_at": "2026-07-06 11:45:00",
            }
        ],
    }
    ingest_contents(db_session, "hauldesk-a", "second.json", contents(follow_up))
    assert len(db_session.scalars(select(RateLineItem)).all()) == 2
    assert db_session.scalar(select(Load)).carrier_rate == Decimal("2070.00")


def test_hauldesk_rejects_unknown_source_fields(db_session: Session) -> None:
    payload = make_sync()
    payload["loads"][0]["unexpected_field"] = "schema drift"
    with pytest.raises(InvalidHaulDeskPayloadError, match="Invalid HaulDesk"):
        ingest_contents(db_session, "hauldesk-a", "schema-drift.json", contents(payload))
    assert db_session.scalars(select(Load)).all() == []


@pytest.mark.skipif(
    not os.getenv("HAULDESK_POSTGRES_TEST_URL"),
    reason="set HAULDESK_POSTGRES_TEST_URL to run PostgreSQL locking coverage",
)
def test_postgres_source_lock_serializes_ingestion() -> None:
    database_url = os.environ["HAULDESK_POSTGRES_TEST_URL"]
    schema = f"hauldesk_test_{uuid4().hex}"
    admin_engine = create_engine(database_url)
    test_engine = None
    locked_engine = None
    locker = None
    lock_transaction = None
    try:
        with admin_engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        connect_args = {"options": f"-c search_path={schema}"}
        test_engine = create_engine(database_url, connect_args=connect_args)
        locked_engine = create_engine(
            database_url,
            connect_args={"options": f"-c search_path={schema} -c lock_timeout=500ms"},
        )
        Base.metadata.create_all(test_engine)
        with Session(test_engine) as session:
            session.add(
                Broker(
                    id="broker-pg", name="Broker PostgreSQL", created_at=datetime.now(timezone.utc)
                )
            )
            session.add(
                BrokerSource(
                    id="hauldesk-pg",
                    broker_id="broker-pg",
                    tms_type=TmsType.HAULDESK,
                    source_name="HaulDesk PostgreSQL",
                    created_at=datetime.now(timezone.utc),
                )
            )
            session.add(
                BrokerSource(
                    id="freightflow-pg-second",
                    broker_id="broker-pg",
                    tms_type=TmsType.FREIGHTFLOW,
                    source_name="FreightFlow PostgreSQL second source",
                    created_at=datetime.now(timezone.utc),
                )
            )
            session.commit()

        locker = test_engine.connect()
        lock_transaction = locker.begin()
        locker.execute(
            select(BrokerSource).where(BrokerSource.id == "hauldesk-pg").with_for_update()
        ).one()
        with Session(locked_engine) as blocked_session:
            with pytest.raises(OperationalError):
                ingest_contents(
                    blocked_session,
                    "hauldesk-pg",
                    "blocked.json",
                    contents(make_sync()),
                )

        lock_transaction.rollback()
        lock_transaction = None
        with Session(test_engine) as session:
            result = ingest_contents(
                session,
                "hauldesk-pg",
                "after-lock.json",
                contents(make_sync()),
            )
            assert result.processed_loads == 1

        lock_transaction = locker.begin()
        locker.execute(select(Broker).where(Broker.id == "broker-pg").with_for_update()).one()
        from app.ingestion.freightflow import ingest_contents as ingest_freightflow

        freightflow_payload = {
            "syncedAt": "2026-07-06T06:00:00-05:00",
            "loads": [
                {
                    "shipmentId": "FF-LOCK",
                    "status": "Dispatched",
                    "mileage": 100.0,
                    "totalSell": 1000.00,
                    "totalBuy": 800.00,
                    "customer": {"customerId": "FF-LOCK-C", "name": "Lock Customer"},
                    "carrier": {
                        "carrierMasterId": "FF-LOCK-CARRIER",
                        "name": "Lock Carrier",
                        "mcNumber": "MC-884201",
                        "dotNumber": "DOT-2551377",
                    },
                    "equipment": "Van",
                    "weightTotal": 1000.0,
                    "stops": [
                        {
                            "stopType": "First Pickup",
                            "city": "Austin",
                            "state": "TX",
                            "zipCode": "78701",
                        },
                        {
                            "stopType": "Last Drop",
                            "city": "Houston",
                            "state": "TX",
                            "zipCode": "77001",
                        },
                    ],
                    "createdDate": "2026-07-06T05:00:00-05:00",
                    "lastModifiedDate": "2026-07-06T05:30:00-05:00",
                }
            ],
        }
        with Session(locked_engine) as blocked_session:
            with pytest.raises(OperationalError):
                ingest_freightflow(
                    blocked_session,
                    "freightflow-pg-second",
                    "blocked-cross-source.json",
                    json.dumps(freightflow_payload).encode(),
                )
        lock_transaction.rollback()
        lock_transaction = None
        with Session(test_engine) as session:
            result = ingest_freightflow(
                session,
                "freightflow-pg-second",
                "after-cross-source-lock.json",
                json.dumps(freightflow_payload).encode(),
            )
            assert result.processed_loads == 1
    finally:
        if lock_transaction is not None:
            lock_transaction.rollback()
        if locker is not None:
            locker.close()
        if locked_engine is not None:
            locked_engine.dispose()
        if test_engine is not None:
            test_engine.dispose()
        with admin_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        admin_engine.dispose()


def test_rejects_fractional_cents_unknown_codes_and_source_type_mismatch(
    db_session: Session,
) -> None:
    bad_amount = make_sync()
    bad_amount["rates"][0]["amount_usd"] = 1035.001
    with pytest.raises(InvalidHaulDeskPayloadError, match="amount_usd"):
        ingest_contents(db_session, "hauldesk-a", "bad-amount.json", contents(bad_amount))

    bad_code = make_sync()
    bad_code["rates"][0]["code"] = "BOGUS"
    with pytest.raises(InvalidHaulDeskPayloadError, match="rate code"):
        ingest_contents(db_session, "hauldesk-a", "bad-code.json", contents(bad_code))

    bad_side = make_sync()
    bad_side["rates"][0]["side"] = "both"
    with pytest.raises(InvalidHaulDeskPayloadError, match="rate side"):
        ingest_contents(db_session, "hauldesk-a", "bad-side.json", contents(bad_side))

    bad_status = make_sync()
    bad_status["loads"][0]["status_code"] = 77
    with pytest.raises(InvalidHaulDeskPayloadError, match="status_code"):
        ingest_contents(db_session, "hauldesk-a", "bad-status.json", contents(bad_status))


def test_rejects_freightflow_source_and_allows_load_only_correction(
    db_session: Session,
) -> None:
    from app.ingestion.hauldesk import HaulDeskIngestionError

    with pytest.raises(HaulDeskIngestionError, match="not configured for HaulDesk"):
        ingest_contents(db_session, "freightflow-a", "wrong.json", contents(make_sync()))

    ingest_contents(
        db_session,
        "hauldesk-a",
        "first.json",
        contents(make_sync(status_code=20, carrier_ref=None)),
    )
    corrected = make_sync(
        synced_at="2026-07-06 12:00:00",
        status_code=40,
        updated_at="2026-07-06 11:45:00",
        delivery_city="Houston",
    )
    corrected["rates"] = []
    result = ingest_contents(
        db_session,
        "hauldesk-a",
        "second.json",
        contents(corrected),
    )
    load = db_session.scalar(select(Load))
    versions = db_session.scalars(select(LoadVersion).order_by(LoadVersion.version_number)).all()
    assert result.processed_loads == 1
    assert load.status == LoadStatus.IN_TRANSIT
    assert len(versions) == 2
    assert versions[1].raw_payload["load"]["load_num"] == "HD-2026-004417"
