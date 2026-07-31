from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.database import get_db
from app.lane_geography import NORMALIZATION_VERSION, normalize_location
from app.lane_intelligence import LaneNotDerivable, derive_primary_lane, get_lane_intelligence
from app.main import create_app
from app.models import (
    Base,
    Broker,
    BrokerSource,
    Customer,
    EquipmentType,
    Load,
    LoadStatus,
    LoadStop,
    StopType,
    TmsType,
)

NOW = datetime(2026, 7, 16, tzinfo=timezone.utc)


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def add_broker(session: Session, broker_id: str) -> str:
    source_id = f"source-{broker_id}"
    session.add(Broker(id=broker_id, name=f"Broker {broker_id}", created_at=NOW))
    session.add(
        BrokerSource(
            id=source_id,
            broker_id=broker_id,
            tms_type=TmsType.FREIGHTFLOW,
            source_name=f"Source {broker_id}",
            created_at=NOW,
        )
    )
    session.add(
        Customer(
            id=f"customer-{broker_id}",
            broker_id=broker_id,
            broker_source_id=source_id,
            source_customer_id=f"source-customer-{broker_id}",
            name="Test Customer",
            created_at=NOW,
            updated_at=NOW,
        )
    )
    session.flush()
    return source_id


def add_load(
    session: Session,
    broker_id: str,
    load_id: str,
    status: LoadStatus,
    origin: tuple[str, str, str],
    destination: tuple[str, str, str],
    equipment: EquipmentType = EquipmentType.DRY_VAN,
) -> Load:
    source_id = f"source-{broker_id}"
    load = Load(
        id=load_id,
        broker_id=broker_id,
        broker_source_id=source_id,
        source_load_id=load_id,
        display_number=load_id,
        status=status,
        customer_id=f"customer-{broker_id}",
        equipment_type=equipment,
        first_seen_at=NOW,
        last_synced_at=NOW,
    )
    session.add(load)
    session.add_all(
        [
            LoadStop(
                broker_id=broker_id,
                load_id=load_id,
                sequence_number=1,
                stop_type=StopType.PICKUP,
                city=origin[0],
                state=origin[1],
                postal_code=origin[2],
            ),
            LoadStop(
                broker_id=broker_id,
                load_id=load_id,
                sequence_number=2,
                stop_type=StopType.DROPOFF,
                city=destination[0],
                state=destination[1],
                postal_code=destination[2],
            ),
        ]
    )
    session.flush()
    return load


def test_normalize_location_prefers_zip_and_corrects_austin_area() -> None:
    location = normalize_location("  Georgetown ", "tx", "78626-1234")

    assert location.exact_key == "US:TX:ZIP:78626"
    assert location.metro_key == "AUSTIN"
    assert location.metro_name == "Austin"
    assert location.match_method == "postal_code"


def test_normalize_unknown_location_never_falls_back_to_state() -> None:
    location = normalize_location("Unknown Place", "TX", "")

    assert location.exact_key == "US:TX:CITY:UNKNOWN_PLACE"
    assert location.metro_key is None
    assert location.match_method == "unmapped"


def test_derive_primary_lane_uses_first_pickup_and_final_dropoff(db_session: Session) -> None:
    add_broker(db_session, "broker-a")
    load = add_load(
        db_session,
        "broker-a",
        "load-1",
        LoadStatus.ACTIVE,
        ("Dallas", "TX", "75201"),
        ("Houston", "TX", "77002"),
    )
    final_stop = db_session.query(LoadStop).filter_by(load_id=load.id, sequence_number=2).one()
    final_stop.sequence_number = 3
    db_session.add(
        LoadStop(
            broker_id="broker-a",
            load_id=load.id,
            sequence_number=2,
            stop_type=StopType.PICKUP_DROPOFF,
            city="Katy",
            state="TX",
            postal_code="77494",
        )
    )
    db_session.flush()

    stops = (
        db_session.query(LoadStop)
        .filter_by(load_id=load.id)
        .order_by(LoadStop.sequence_number)
        .all()
    )
    lane = derive_primary_lane(stops)

    assert lane.origin.location.metro_key == "DFW"
    assert lane.destination.location.metro_key == "HOUSTON"
    assert lane.metro_key == "DFW>HOUSTON"


def test_derive_primary_lane_rejects_missing_or_unordered_stops(
    db_session: Session,
) -> None:
    with pytest.raises(LaneNotDerivable):
        derive_primary_lane([])

    add_broker(db_session, "broker-a")
    load = add_load(
        db_session,
        "broker-a",
        "invalid",
        LoadStatus.ACTIVE,
        ("Dallas", "TX", "75201"),
        ("Houston", "TX", "77002"),
    )
    destination = db_session.query(LoadStop).filter_by(load_id=load.id, sequence_number=2).one()
    db_session.delete(destination)
    db_session.flush()

    with pytest.raises(LaneNotDerivable):
        derive_primary_lane(db_session.query(LoadStop).filter_by(load_id=load.id).all())


def test_lane_history_is_broker_scoped_and_uses_nearby_fallback(db_session: Session) -> None:
    add_broker(db_session, "broker-a")
    add_broker(db_session, "broker-b")
    add_load(
        db_session,
        "broker-a",
        "target",
        LoadStatus.ACTIVE,
        ("Dallas", "TX", "75201"),
        ("Houston", "TX", "77002"),
    )
    add_load(
        db_session,
        "broker-a",
        "nearby-1",
        LoadStatus.DELIVERED,
        ("Plano", "TX", "75024"),
        ("Katy", "TX", "77494"),
    )
    add_load(
        db_session,
        "broker-a",
        "nearby-2",
        LoadStatus.COMPLETED,
        ("Arlington", "TX", "76011"),
        ("Missouri City", "TX", "77459"),
        EquipmentType.REEFER,
    )
    add_load(
        db_session,
        "broker-b",
        "other-broker",
        LoadStatus.COMPLETED,
        ("Plano", "TX", "75024"),
        ("Katy", "TX", "77494"),
    )
    db_session.commit()

    result = get_lane_intelligence(db_session, "broker-a", "target")

    assert result is not None
    assert result.lane.metro_key == "DFW>HOUSTON"
    assert result.history.exact_count == 0
    assert result.history.nearby_count == 2
    assert result.history.equipment_nearby_count == 1
    assert result.history.selected_scope == "nearby"
    assert result.history.data_sufficiency == "thin"
    assert result.history.fallback_reason == "No exact directional history"


def test_lane_history_is_directional_and_ignores_ineligible_loads(db_session: Session) -> None:
    add_broker(db_session, "broker-a")
    add_load(
        db_session,
        "broker-a",
        "target",
        LoadStatus.ACTIVE,
        ("Dallas", "TX", "75201"),
        ("Houston", "TX", "77002"),
    )
    add_load(
        db_session,
        "broker-a",
        "reverse",
        LoadStatus.COMPLETED,
        ("Houston", "TX", "77002"),
        ("Dallas", "TX", "75201"),
    )
    add_load(
        db_session,
        "broker-a",
        "active-history",
        LoadStatus.ACTIVE,
        ("Plano", "TX", "75024"),
        ("Katy", "TX", "77494"),
    )
    db_session.commit()

    result = get_lane_intelligence(db_session, "broker-a", "target")

    assert result is not None
    assert result.history.exact_count == 0
    assert result.history.nearby_count == 0
    assert result.history.selected_scope == "none"


def test_corrected_destination_changes_exact_lane_without_duplicate_count(
    db_session: Session,
) -> None:
    add_broker(db_session, "broker-a")
    add_load(
        db_session,
        "broker-a",
        "target",
        LoadStatus.ACTIVE,
        ("Dallas", "TX", "75201"),
        ("Houston", "TX", "77002"),
    )
    history = add_load(
        db_session,
        "broker-a",
        "history",
        LoadStatus.COMPLETED,
        ("Dallas", "TX", "75201"),
        ("Houston", "TX", "77002"),
    )
    db_session.commit()

    initial = get_lane_intelligence(db_session, "broker-a", "target")
    assert initial is not None
    assert initial.history.exact_count == 1

    destination = db_session.query(LoadStop).filter_by(load_id=history.id, sequence_number=2).one()
    destination.city = "Sugar Land"
    destination.postal_code = "77478"
    db_session.commit()

    corrected = get_lane_intelligence(db_session, "broker-a", "target")
    assert corrected is not None
    assert corrected.history.exact_count == 0
    assert corrected.history.nearby_count == 1


def test_lane_history_uses_sufficient_exact_history(db_session: Session) -> None:
    add_broker(db_session, "broker-a")
    add_load(
        db_session,
        "broker-a",
        "target",
        LoadStatus.ACTIVE,
        ("Dallas", "TX", "75201"),
        ("Houston", "TX", "77002"),
    )
    for index in range(1, 4):
        add_load(
            db_session,
            "broker-a",
            f"exact-{index}",
            LoadStatus.COMPLETED,
            ("Dallas", "TX", "75201"),
            ("Houston", "TX", "77002"),
        )
    db_session.commit()

    result = get_lane_intelligence(db_session, "broker-a", "target")

    assert result is not None
    assert result.history.exact_count == 3
    assert result.history.selected_scope == "exact"
    assert result.history.data_sufficiency == "sufficient"
    assert result.history.fallback_reason is None


def test_lane_history_returns_empty_scope_without_history(db_session: Session) -> None:
    add_broker(db_session, "broker-a")
    add_load(
        db_session,
        "broker-a",
        "target",
        LoadStatus.ACTIVE,
        ("Dallas", "TX", "75201"),
        ("Houston", "TX", "77002"),
    )
    db_session.commit()

    result = get_lane_intelligence(db_session, "broker-a", "target")

    assert result is not None
    assert result.history.exact_count == 0
    assert result.history.nearby_count == 0
    assert result.history.equipment_exact_count == 0
    assert result.history.equipment_nearby_count == 0
    assert result.history.selected_scope == "none"
    assert result.history.data_sufficiency == "none"


def test_lane_api_returns_metadata_and_enforces_errors(db_session: Session) -> None:
    add_broker(db_session, "broker-a")
    add_load(
        db_session,
        "broker-a",
        "target",
        LoadStatus.ACTIVE,
        ("Dallas", "TX", "75201"),
        ("Houston", "TX", "77002"),
    )
    db_session.commit()

    application = create_app()

    def override_db():
        yield db_session

    application.dependency_overrides[get_db] = override_db
    with TestClient(application) as client:
        response = client.get("/brokers/broker-a/loads/target/lane-intelligence")
        missing = client.get("/brokers/broker-a/loads/missing/lane-intelligence")
        unsupported = client.get(
            "/brokers/broker-a/loads/target/lane-intelligence",
            params={"normalization_version": "tx-metro-v0"},
        )

    assert response.status_code == 200
    assert response.json()["normalization_version"] == NORMALIZATION_VERSION
    assert response.json()["lane"]["metro_key"] == "DFW>HOUSTON"
    assert response.json()["history"]["eligible_statuses"] == ["delivered", "completed"]
    assert missing.status_code == 404
    assert unsupported.status_code == 422


def test_lane_api_returns_422_for_non_derivable_load(db_session: Session) -> None:
    add_broker(db_session, "broker-a")
    load = add_load(
        db_session,
        "broker-a",
        "invalid",
        LoadStatus.ACTIVE,
        ("Dallas", "TX", "75201"),
        ("Houston", "TX", "77002"),
    )
    destination = db_session.query(LoadStop).filter_by(load_id=load.id, sequence_number=2).one()
    db_session.delete(destination)
    db_session.commit()

    application = create_app()

    def override_db():
        yield db_session

    application.dependency_overrides[get_db] = override_db
    with TestClient(application) as client:
        response = client.get("/brokers/broker-a/loads/invalid/lane-intelligence")

    assert response.status_code == 422
    assert response.json()["detail"] == "load must have pickup and delivery stops"
