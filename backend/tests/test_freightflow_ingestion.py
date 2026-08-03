import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session

from app.ingestion import freightflow
from app.ingestion.freightflow import (
    ConflictingFileError,
    FreightFlowIngestionError,
    IngestionResult,
    InvalidFreightFlowPayloadError,
    OutOfOrderFileError,
    _map_equipment,
    _map_stop_type,
    ingest_contents,
    ingest_file,
)
from app.models import (
    Base,
    Broker,
    BrokerSource,
    Carrier,
    Customer,
    EquipmentType,
    IngestionFile,
    Load,
    LoadStatus,
    LoadStop,
    LoadVersion,
    TmsType,
)


def make_sync(
    synced_at: str,
    status: str = "Booking",
    carrier: Optional[Dict] = None,
    total_buy: Optional[float] = None,
    total_sell: float = 1450.0,
    equipment: Optional[str] = "53 ft Van | Dry",
    delivery_city: str = "Katy",
    shipment_id: int = 127472397,
) -> dict:
    return {
        "syncedAt": synced_at,
        "loads": [
            {
                "shipmentId": shipment_id,
                "status": status,
                "mileage": 242.1,
                "totalSell": total_sell,
                "totalBuy": total_buy,
                "customer": {"customerId": 889264, "name": "Lone Star Beverages"},
                "carrier": carrier,
                "equipment": equipment,
                "weightTotal": 24000.0,
                "stops": [
                    {
                        "stopType": "First Pickup",
                        "city": "Grand Prairie",
                        "state": "TX",
                        "zipCode": "75050",
                        "estimatedReadyDateTime": "2026-07-07T08:00:00-05:00",
                        "estimatedCloseDateTime": "2026-07-07T16:00:00-05:00",
                        "actualDepartureDateTime": None,
                    },
                    {
                        "stopType": "Last Drop",
                        "city": delivery_city,
                        "state": "TX",
                        "zipCode": "77449",
                        "estimatedReadyDateTime": "2026-07-08T08:00:00-05:00",
                        "estimatedCloseDateTime": "2026-07-08T16:00:00-05:00",
                        "actualDepartureDateTime": None,
                    },
                ],
                "createdDate": "2026-07-06T04:12:44-05:00",
                "lastModifiedDate": synced_at,
            }
        ],
    }


def contents(payload: Dict) -> bytes:
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


def test_ingests_a_freightflow_file_and_creates_provenance(
    db_session: Session, tmp_path: Path
) -> None:
    path = tmp_path / "2026-07-06T06-00_sync.json"
    path.write_bytes(contents(make_sync("2026-07-06T06:00:00-05:00")))

    result = ingest_file(db_session, "freightflow-a", path)

    assert result.processed_loads == 1
    assert result.duplicate is False
    load = db_session.scalar(select(Load))
    version = db_session.scalar(select(LoadVersion))
    ingestion_file = db_session.scalar(select(IngestionFile))
    stops = db_session.scalars(select(LoadStop).order_by(LoadStop.sequence_number)).all()
    assert load.status == LoadStatus.ACTIVE
    assert load.carrier_id is None
    assert load.equipment_type == EquipmentType.DRY_VAN
    assert len(stops) == 2
    assert version.ingestion_file_id == ingestion_file.id
    assert version.raw_payload["shipmentId"] == 127472397
    assert version.normalized_snapshot["status"] == "active"


def test_lifecycle_updates_preserve_history_and_first_booking_time(db_session: Session) -> None:
    ingest_contents(
        db_session,
        "freightflow-a",
        "2026-07-06T06-00_sync.json",
        contents(make_sync("2026-07-06T06:00:00-05:00")),
    )
    initial_stop_ids = {
        stop.sequence_number: stop.id for stop in db_session.scalars(select(LoadStop)).all()
    }
    customer_created_at = db_session.scalar(select(Customer)).updated_at
    db_session.rollback()
    carrier = {
        "carrierMasterId": 835692,
        "name": "Ibrahim Transport Inc",
        "mcNumber": "1346382",
        "dotNumber": "3771394",
        "phoneNumber": "+15714906959",
    }
    ingest_contents(
        db_session,
        "freightflow-a",
        "2026-07-06T12-00_sync.json",
        contents(
            make_sync(
                "2026-07-06T12:00:00-05:00",
                status="Dispatched",
                carrier=carrier,
                total_buy=1180.0,
            )
        ),
    )
    ingest_contents(
        db_session,
        "freightflow-a",
        "2026-07-06T18-00_sync.json",
        contents(
            make_sync(
                "2026-07-06T18:00:00-05:00",
                status="Completed",
                carrier=carrier,
                total_buy=1205.5,
                total_sell=1510.0,
                delivery_city="Sugar Land",
            )
        ),
    )

    load = db_session.scalar(select(Load))
    versions = db_session.scalars(select(LoadVersion).order_by(LoadVersion.version_number)).all()
    stops = db_session.scalars(select(LoadStop).order_by(LoadStop.sequence_number)).all()
    assert load.status == LoadStatus.COMPLETED
    assert str(load.carrier_rate) == "1205.50"
    assert str(load.customer_rate) == "1510.00"
    assert load.booked_at.replace(tzinfo=timezone.utc) == datetime(
        2026, 7, 6, 17, tzinfo=timezone.utc
    )
    assert db_session.scalar(select(Carrier)).mc_number == "1346382"
    assert db_session.scalar(select(Customer)).updated_at == customer_created_at
    assert db_session.scalar(select(Carrier)).updated_at.replace(tzinfo=timezone.utc) == datetime(
        2026, 7, 6, 17, tzinfo=timezone.utc
    )
    assert stops[-1].city == "Sugar Land"
    assert {stop.sequence_number: stop.id for stop in stops} == initial_stop_ids
    assert [version.version_number for version in versions] == [1, 2, 3]
    assert versions[1].normalized_snapshot["carrier_rate"] == "1180.0"
    assert versions[1].normalized_snapshot["stops"][-1]["city"] == "Katy"
    assert versions[2].normalized_snapshot["carrier_rate"] == "1205.5"


def test_newer_sync_does_not_apply_an_older_freightflow_record(
    db_session: Session,
) -> None:
    ingest_contents(
        db_session,
        "freightflow-a",
        "first.json",
        contents(make_sync("2026-07-06T06:00:00-05:00", status="Booking")),
    )
    stale = make_sync("2026-07-06T12:00:00-05:00", status="Completed")
    stale["loads"][0]["lastModifiedDate"] = "2026-07-06T05:00:00-05:00"
    ingest_contents(db_session, "freightflow-a", "second.json", contents(stale))

    load = db_session.scalar(select(Load))
    assert load.status == LoadStatus.ACTIVE


def test_carrier_identity_replacement_conflicts_and_missing_ids_preserve_link(
    db_session: Session,
) -> None:
    from app.ingestion.common import CarrierIdentityConflictError
    from app.ingestion.freightflow import FreightFlowCarrier, _upsert_carrier

    source = db_session.get(BrokerSource, "freightflow-a")
    observed_at = datetime(2026, 7, 6, tzinfo=timezone.utc)
    carrier = _upsert_carrier(
        db_session,
        source,
        FreightFlowCarrier(
            carrierMasterId="carrier-1", name="Carrier", mcNumber="100", dotNumber="200"
        ),
        observed_at,
    )
    db_session.commit()
    with pytest.raises(CarrierIdentityConflictError):
        _upsert_carrier(
            db_session,
            source,
            FreightFlowCarrier(
                carrierMasterId="carrier-1", name="Carrier", mcNumber="999", dotNumber="200"
            ),
            observed_at,
        )
    db_session.rollback()
    stored = db_session.get(Carrier, carrier.id)
    assert stored.mc_number == "100"
    assert stored.carrier_identity_id is not None

    _upsert_carrier(
        db_session,
        source,
        FreightFlowCarrier(carrierMasterId="carrier-1", name="Carrier"),
        observed_at,
    )
    assert db_session.get(Carrier, carrier.id).carrier_identity_id == stored.carrier_identity_id


def test_ingests_multiple_loads_and_reuses_shared_entities(db_session: Session) -> None:
    carrier = {
        "carrierMasterId": 835692,
        "name": "Ibrahim Transport Inc",
        "mcNumber": "1346382",
        "dotNumber": "3771394",
        "phoneNumber": "+15714906959",
    }
    payload = make_sync("2026-07-06T06:00:00-05:00", carrier=carrier, total_buy=1180.0)
    second_load = make_sync(
        "2026-07-06T06:00:00-05:00",
        carrier=carrier,
        total_buy=1190.0,
        delivery_city="Houston",
        shipment_id=999,
    )["loads"][0]
    payload["loads"].append(second_load)

    result = ingest_contents(
        db_session,
        "freightflow-a",
        "2026-07-06T06-00_sync.json",
        contents(payload),
    )

    assert result.processed_loads == 2
    assert len(db_session.scalars(select(Load)).all()) == 2
    assert len(db_session.scalars(select(LoadVersion)).all()) == 2
    assert {version.version_number for version in db_session.scalars(select(LoadVersion))} == {1}
    assert len(db_session.scalars(select(LoadStop)).all()) == 4
    assert len(db_session.scalars(select(Customer)).all()) == 1
    assert len(db_session.scalars(select(Carrier)).all()) == 1


def test_reprocessing_the_same_file_is_idempotent(db_session: Session) -> None:
    raw_contents = contents(make_sync("2026-07-06T06:00:00-05:00"))

    first_result = ingest_contents(
        db_session, "freightflow-a", "2026-07-06T06-00_sync.json", raw_contents
    )
    second_result = ingest_contents(
        db_session, "freightflow-a", "2026-07-06T06-00_sync.json", raw_contents
    )

    assert first_result.duplicate is False
    assert second_result.duplicate is True
    assert len(db_session.scalars(select(IngestionFile)).all()) == 1
    assert len(db_session.scalars(select(LoadVersion)).all()) == 1


def test_rejects_conflicting_or_out_of_order_files(db_session: Session) -> None:
    initial = contents(make_sync("2026-07-06T12:00:00-05:00"))
    ingest_contents(db_session, "freightflow-a", "2026-07-06T12-00_sync.json", initial)

    with pytest.raises(ConflictingFileError):
        ingest_contents(
            db_session,
            "freightflow-a",
            "2026-07-06T12-00_sync.json",
            contents(make_sync("2026-07-06T12:00:00-05:00", total_sell=1500.0)),
        )

    with pytest.raises(OutOfOrderFileError):
        ingest_contents(
            db_session,
            "freightflow-a",
            "2026-07-06T06-00_sync.json",
            contents(make_sync("2026-07-06T06:00:00-05:00")),
        )


def test_same_source_id_is_isolated_between_brokers(db_session: Session) -> None:
    db_session.add(Broker(id="broker-b", name="Broker B", created_at=datetime.now(timezone.utc)))
    db_session.add(
        BrokerSource(
            id="freightflow-b",
            broker_id="broker-b",
            tms_type=TmsType.FREIGHTFLOW,
            source_name="FreightFlow B",
            created_at=datetime.now(timezone.utc),
        )
    )
    db_session.commit()
    raw_contents = contents(make_sync("2026-07-06T06:00:00-05:00"))

    ingest_contents(db_session, "freightflow-a", "2026-07-06T06-00_sync.json", raw_contents)
    ingest_contents(db_session, "freightflow-b", "2026-07-06T06-00_sync.json", raw_contents)

    loads = db_session.scalars(select(Load).order_by(Load.broker_id)).all()
    assert len(loads) == 2
    assert {load.broker_id for load in loads} == {"broker-a", "broker-b"}
    assert loads[0].id != loads[1].id


def test_handles_unknown_equipment_and_rolls_back_invalid_syncs(db_session: Session) -> None:
    unknown_equipment = make_sync("2026-07-06T06:00:00-05:00", equipment="Conestoga")
    ingest_contents(
        db_session,
        "freightflow-a",
        "2026-07-06T06-00_sync.json",
        contents(unknown_equipment),
    )
    assert db_session.scalar(select(Load)).equipment_type == EquipmentType.UNKNOWN
    db_session.rollback()

    valid_load = make_sync("2026-07-06T12:00:00-05:00")["loads"][0]
    invalid_load = make_sync("2026-07-06T12:00:00-05:00", shipment_id=999)["loads"][0]
    invalid_load["status"] = "Unrecognized Status"
    invalid_payload = {"syncedAt": "2026-07-06T12:00:00-05:00", "loads": [valid_load, invalid_load]}

    with pytest.raises(InvalidFreightFlowPayloadError):
        ingest_contents(
            db_session,
            "freightflow-a",
            "2026-07-06T12-00_sync.json",
            contents(invalid_payload),
        )

    assert len(db_session.scalars(select(IngestionFile)).all()) == 1
    assert len(db_session.scalars(select(Load)).all()) == 1


def test_ambiguous_equipment_is_not_misclassified() -> None:
    assert _map_equipment("dry van reefer combo") == EquipmentType.UNKNOWN


def test_rejects_unknown_stop_type() -> None:
    with pytest.raises(InvalidFreightFlowPayloadError, match="Transfer"):
        _map_stop_type("Transfer")


def test_rejects_malformed_payload_without_recording_a_file(db_session: Session) -> None:
    with pytest.raises(InvalidFreightFlowPayloadError):
        ingest_contents(db_session, "freightflow-a", "broken.json", b"{not-json")

    assert db_session.scalars(select(IngestionFile)).all() == []


def test_rejects_fractional_cent_rates_without_recording_a_file(db_session: Session) -> None:
    with pytest.raises(InvalidFreightFlowPayloadError, match="totalSell"):
        ingest_contents(
            db_session,
            "freightflow-a",
            "fractional-cents.json",
            contents(make_sync("2026-07-06T06:00:00-05:00", total_sell=1450.001)),
        )

    assert db_session.scalars(select(IngestionFile)).all() == []
    assert db_session.scalars(select(Load)).all() == []


def test_rejects_out_of_range_rates_without_recording_a_file(db_session: Session) -> None:
    payload = make_sync("2026-07-06T06:00:00-05:00")
    payload["loads"][0]["totalSell"] = "999999999999999999999999999.001"

    with pytest.raises(InvalidFreightFlowPayloadError, match="totalSell"):
        ingest_contents(
            db_session,
            "freightflow-a",
            "out-of-range.json",
            contents(payload),
        )

    assert db_session.scalars(select(IngestionFile)).all() == []
    assert db_session.scalars(select(Load)).all() == []


def test_cli_ingests_file_and_prints_result(monkeypatch, capsys, tmp_path: Path) -> None:
    path = tmp_path / "sync.json"
    path.write_text("{}")
    fake_session = object()
    calls = {}

    class SessionContext:
        def __enter__(self):
            return fake_session

        def __exit__(self, exc_type, exc_value, traceback):
            return False

    def fake_ingest_file(session, broker_source_id, received_path):
        calls.update(
            session=session,
            broker_source_id=broker_source_id,
            path=received_path,
        )
        return IngestionResult(filename=received_path.name, processed_loads=2, duplicate=False)

    monkeypatch.setattr(freightflow, "SessionLocal", lambda: SessionContext())
    monkeypatch.setattr(freightflow, "ingest_file", fake_ingest_file)
    monkeypatch.setattr(
        sys,
        "argv",
        ["freightflow", "--broker-source-id", "freightflow-a", str(path)],
    )

    freightflow.main()

    assert calls == {
        "session": fake_session,
        "broker_source_id": "freightflow-a",
        "path": path,
    }
    assert json.loads(capsys.readouterr().out) == {
        "filename": "sync.json",
        "processed_loads": 2,
        "duplicate": False,
    }


def test_cli_reports_ingestion_errors(monkeypatch, capsys, tmp_path: Path) -> None:
    path = tmp_path / "sync.json"

    class SessionContext:
        def __enter__(self):
            return object()

        def __exit__(self, exc_type, exc_value, traceback):
            return False

    def failing_ingest_file(session, broker_source_id, received_path):
        raise FreightFlowIngestionError("database unavailable")

    monkeypatch.setattr(freightflow, "SessionLocal", lambda: SessionContext())
    monkeypatch.setattr(freightflow, "ingest_file", failing_ingest_file)
    monkeypatch.setattr(sys, "argv", ["freightflow", "--broker-source-id", "source-a", str(path)])

    with pytest.raises(SystemExit) as error:
        freightflow.main()

    assert error.value.code == 1
    assert "FreightFlow ingestion failed: database unavailable" in capsys.readouterr().err


def test_ingest_file_reports_missing_input_file(db_session: Session, tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        ingest_file(db_session, "freightflow-a", tmp_path / "missing.json")
