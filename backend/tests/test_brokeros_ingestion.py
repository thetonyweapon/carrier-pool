import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import List, Optional

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session

from app.ingestion.brokeros import (
    ConflictingBrokerOSFileError,
    InvalidBrokerOSPayloadError,
    OutOfOrderBrokerOSFileError,
    ingest_contents,
)
from app.models import (
    Base,
    Broker,
    BrokerSource,
    Carrier,
    EquipmentType,
    IngestionFile,
    Load,
    LoadRateObservation,
    LoadStatus,
    LoadStop,
    LoadVersion,
    RateLineItem,
    RateSide,
    StopType,
    TmsType,
)


def make_sync(
    *,
    synced_at: str = "2026-07-06T11:00:00.000+0000",
    status: str = "Ready to Book",
    equipment: Optional[str] = "Reefer",
    carrier_ref: Optional[str] = None,
    customer_rate: Optional[float] = 1720.00,
    carrier_rate: Optional[float] = None,
    stops: Optional[List[dict]] = None,
    line_items: Optional[List[dict]] = None,
) -> dict:
    if stops is None:
        stops = [
            {
                "bos__Number__c": 1.0,
                "bos__Is_Pickup__c": True,
                "bos__Is_Dropoff__c": False,
                "bos__Location__c": "LOC-PICKUP",
                "bos__Scheduled_Date__c": "2026-07-07",
                "bos__Arrival_Time__c": None,
            },
            {
                "bos__Number__c": 2.0,
                "bos__Is_Pickup__c": False,
                "bos__Is_Dropoff__c": True,
                "bos__Location__c": "LOC-DROPOFF",
                "bos__Scheduled_Date__c": "2026-07-08",
                "bos__Arrival_Time__c": None,
            },
        ]
    if line_items is None:
        line_items = [
            {
                "bos__Commodity__c": "Packaged foods",
                "bos__Weight__c": 14440.0,
                "bos__Weight_Units__c": "lbs",
                "bos__Pallet_Count__c": 18.0,
            }
        ]
    referenced_records = {
        "LOC-PICKUP": {
            "type": "Location",
            "Name": "Sugar Land Cold Storage",
            "bos__City__c": "Sugar Land",
            "bos__State__c": "TX",
            "bos__Postal_Code__c": "77478",
        },
        "LOC-DROPOFF": {
            "type": "Location",
            "Name": "Schertz Distribution Ctr",
            "bos__City__c": "Schertz",
            "bos__State__c": "TX",
            "bos__Postal_Code__c": "78154",
        },
        "CUSTOMER-1": {
            "type": "Account",
            "record_type": "Customer",
            "Name": "Gulf Coast Foods",
        },
    }
    if carrier_ref is not None:
        referenced_records[carrier_ref] = {
            "type": "Account",
            "record_type": "Carrier",
            "Name": "Delta Prime LLC",
        }
    return {
        "synced_at": synced_at,
        "records": [
            {
                "Id": "BROKEROS-LOAD-1",
                "Name": "SHP6743062",
                "bos__Load_Status__c": status,
                "bos__Distance_Miles__c": 197.4,
                "bos__Customer__c": "CUSTOMER-1",
                "bos__Carrier__c": carrier_ref,
                "bos__Equipment_Type__c": equipment,
                "bos__Customer_Rate__c": customer_rate,
                "bos__Carrier_Rate__c": carrier_rate,
                "bos__Stops__r": stops,
                "bos__Line_Items__r": line_items,
                "CreatedDate": "2026-07-06T09:40:02.000+0000",
                "LastModifiedDate": "2026-07-06T09:40:02.000+0000",
            }
        ],
        "referenced_records": referenced_records,
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
                id="brokeros-a",
                broker_id="broker-a",
                tms_type=TmsType.BROKEROS,
                source_name="BrokerOS A",
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


def test_ingests_crm_record_references_multistop_and_weight(db_session: Session) -> None:
    result = ingest_contents(db_session, "brokeros-a", "first.json", contents(make_sync()))

    load = db_session.scalar(select(Load))
    stops = db_session.scalars(select(LoadStop).order_by(LoadStop.sequence_number)).all()
    version = db_session.scalar(select(LoadVersion))
    observations = db_session.scalars(select(LoadRateObservation)).all()

    assert result.processed_loads == 1
    assert load.source_load_id == "BROKEROS-LOAD-1"
    assert load.display_number == "SHP6743062"
    assert load.status == LoadStatus.ACTIVE
    assert load.equipment_type == EquipmentType.REEFER
    assert load.weight_lbs == Decimal("14440.0")
    assert load.distance_miles == Decimal("197.4")
    assert load.customer_rate == Decimal("1720.00")
    assert load.carrier_rate is None
    assert [stop.stop_type for stop in stops] == [StopType.PICKUP, StopType.DROPOFF]
    assert stops[0].scheduled_date.isoformat() == "2026-07-07"
    assert stops[0].source_location_id == "LOC-PICKUP"
    assert stops[1].location_name == "Schertz Distribution Ctr"
    assert len(observations) == 2
    assert {observation.side for observation in observations} == {RateSide.BILL, RateSide.PAY}
    assert version.raw_payload["referenced_records"]["LOC-PICKUP"]["type"] == "Location"
    assert version.normalized_snapshot["source_status"] == "Ready to Book"
    assert db_session.scalars(select(RateLineItem)).all() == []


def test_status_equipment_and_null_weight_mappings(db_session: Session) -> None:
    payload = make_sync(status="Paid", equipment=None, line_items=[])
    ingest_contents(db_session, "brokeros-a", "first.json", contents(payload))
    load = db_session.scalar(select(Load))
    assert load.status == LoadStatus.COMPLETED
    assert load.equipment_type == EquipmentType.UNKNOWN
    assert load.weight_lbs is None
    assert load.booked_at.replace(tzinfo=timezone.utc) == datetime(
        2026, 7, 6, 9, 40, 2, tzinfo=timezone.utc
    )


def test_kg_weight_and_multiple_stops_are_normalized(db_session: Session) -> None:
    payload = make_sync(
        line_items=[
            {
                "bos__Commodity__c": "Food",
                "bos__Weight__c": 1000.0,
                "bos__Weight_Units__c": "kg",
                "bos__Pallet_Count__c": 1.0,
            },
            {
                "bos__Commodity__c": "Drink",
                "bos__Weight__c": 2204.6226,
                "bos__Weight_Units__c": "pounds",
                "bos__Pallet_Count__c": 2.0,
            },
        ],
        stops=[
            {
                "bos__Number__c": 2.0,
                "bos__Is_Pickup__c": False,
                "bos__Is_Dropoff__c": True,
                "bos__Location__c": "LOC-DROPOFF",
                "bos__Scheduled_Date__c": "2026-07-08",
                "bos__Arrival_Time__c": "2026-07-08T14:30:00-05:00",
            },
            {
                "bos__Number__c": 1.0,
                "bos__Is_Pickup__c": True,
                "bos__Is_Dropoff__c": True,
                "bos__Location__c": "LOC-PICKUP",
                "bos__Scheduled_Date__c": "2026-07-07",
                "bos__Arrival_Time__c": None,
            },
            {
                "bos__Number__c": 3.0,
                "bos__Is_Pickup__c": False,
                "bos__Is_Dropoff__c": True,
                "bos__Location__c": "LOC-DROPOFF",
                "bos__Scheduled_Date__c": "2026-07-09",
                "bos__Arrival_Time__c": None,
            },
        ],
    )
    ingest_contents(db_session, "brokeros-a", "first.json", contents(payload))
    load = db_session.scalar(select(Load))
    stops = db_session.scalars(select(LoadStop).order_by(LoadStop.sequence_number)).all()
    assert load.weight_lbs == Decimal("4409.2")
    assert len(stops) == 3
    assert stops[0].stop_type == StopType.PICKUP_DROPOFF
    assert stops[1].actual_arrived_at.replace(tzinfo=timezone.utc) == datetime(
        2026, 7, 8, 19, 30, tzinfo=timezone.utc
    )
    assert [stop.source_sequence_value for stop in stops] == [
        Decimal("1.000"),
        Decimal("2.000"),
        Decimal("3.000"),
    ]


def test_carrier_identity_is_not_guessed_without_mc_dot(db_session: Session) -> None:
    payload = make_sync(carrier_ref="CARRIER-1", status="Booked", carrier_rate=1200.00)
    ingest_contents(db_session, "brokeros-a", "first.json", contents(payload))
    carrier = db_session.scalar(select(Carrier))
    assert carrier.name == "Delta Prime LLC"
    assert carrier.carrier_identity_id is None


def test_rate_restatement_is_append_only_observation_and_versioned(db_session: Session) -> None:
    ingest_contents(db_session, "brokeros-a", "first.json", contents(make_sync()))
    changed = make_sync(
        synced_at="2026-07-06T17:00:00.000+0000",
        status="Booked",
        carrier_ref="CARRIER-1",
        carrier_rate=1200.00,
    )
    ingest_contents(db_session, "brokeros-a", "second.json", contents(changed))
    load = db_session.scalar(select(Load))
    observations = db_session.scalars(
        select(LoadRateObservation).order_by(
            LoadRateObservation.side, LoadRateObservation.observation_number
        )
    ).all()
    versions = db_session.scalars(select(LoadVersion).order_by(LoadVersion.version_number)).all()
    pay_observations = [item for item in observations if item.side == RateSide.PAY]
    assert load.carrier_rate == Decimal("1200.00")
    assert [item.amount for item in pay_observations] == [None, Decimal("1200.00")]
    assert len(versions) == 2
    assert versions[1].raw_payload["referenced_records"]["CARRIER-1"]["record_type"] == "Carrier"
    assert load.booked_at.replace(tzinfo=timezone.utc) == datetime(
        2026, 7, 6, 9, 40, 2, tzinfo=timezone.utc
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("bos__Load_Status__c", "Unknown"),
        ("bos__Equipment_Type__c", "Tank"),
        ("bos__Distance_Miles__c", -1),
        ("bos__Customer_Rate__c", 1.001),
    ],
)
def test_rejects_invalid_scalar_values(db_session: Session, field: str, value) -> None:
    payload = make_sync()
    payload["records"][0][field] = value
    with pytest.raises(InvalidBrokerOSPayloadError):
        ingest_contents(db_session, "brokeros-a", "invalid.json", contents(payload))
    assert db_session.scalars(select(Load)).all() == []
    assert db_session.scalars(select(IngestionFile)).all() == []


def test_rejects_invalid_references_units_directions_and_sequence(db_session: Session) -> None:
    missing_reference = make_sync()
    missing_reference["records"][0]["bos__Customer__c"] = "MISSING"
    with pytest.raises(InvalidBrokerOSPayloadError):
        ingest_contents(db_session, "brokeros-a", "missing.json", contents(missing_reference))
    unsupported_unit = make_sync(
        line_items=[
            {
                "bos__Commodity__c": "Food",
                "bos__Weight__c": 10,
                "bos__Weight_Units__c": "tons",
                "bos__Pallet_Count__c": 1,
            }
        ]
    )
    with pytest.raises(InvalidBrokerOSPayloadError):
        ingest_contents(db_session, "brokeros-a", "unit.json", contents(unsupported_unit))
    invalid_direction = make_sync()
    invalid_direction["records"][0]["bos__Stops__r"][0]["bos__Is_Pickup__c"] = False
    with pytest.raises(InvalidBrokerOSPayloadError):
        ingest_contents(db_session, "brokeros-a", "direction.json", contents(invalid_direction))
    duplicate_sequence = make_sync()
    duplicate_sequence["records"][0]["bos__Stops__r"][1]["bos__Number__c"] = 1.0
    with pytest.raises(InvalidBrokerOSPayloadError):
        ingest_contents(db_session, "brokeros-a", "sequence.json", contents(duplicate_sequence))
    negative_sequence = make_sync()
    negative_sequence["records"][0]["bos__Stops__r"][0]["bos__Number__c"] = -1.0
    with pytest.raises(InvalidBrokerOSPayloadError):
        ingest_contents(
            db_session,
            "brokeros-a",
            "negative-sequence.json",
            contents(negative_sequence),
        )


def test_file_idempotency_ordering_and_wrong_source(db_session: Session) -> None:
    raw = contents(make_sync())
    first = ingest_contents(db_session, "brokeros-a", "same.json", raw)
    duplicate = ingest_contents(db_session, "brokeros-a", "same.json", raw)
    assert first.duplicate is False
    assert duplicate.duplicate is True
    with pytest.raises(ConflictingBrokerOSFileError):
        ingest_contents(
            db_session,
            "brokeros-a",
            "same.json",
            contents(make_sync(equipment="Dry Van")),
        )
    with pytest.raises(OutOfOrderBrokerOSFileError):
        ingest_contents(
            db_session,
            "brokeros-a",
            "older.json",
            contents(make_sync(synced_at="2026-07-06T10:00:00.000+0000")),
        )
    with pytest.raises(Exception, match="not configured"):
        ingest_contents(db_session, "freightflow-a", "wrong.json", raw)
