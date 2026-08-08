from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.database import get_db
from app.main import create_app
from app.models import (
    Base,
    Broker,
    BrokerSource,
    Carrier,
    Customer,
    EquipmentType,
    Load,
    LoadStatus,
    LoadStop,
    StopType,
    TmsType,
)
from app.rate_estimation import estimate_carrier_rate
from tests.auth_helpers import auth_headers

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


def add_broker(session: Session, broker_id: str) -> None:
    session.add(Broker(id=broker_id, name=broker_id, created_at=NOW))
    session.add(
        BrokerSource(
            id=f"source-{broker_id}",
            broker_id=broker_id,
            tms_type=TmsType.FREIGHTFLOW,
            source_name=broker_id,
            created_at=NOW,
        )
    )
    session.add(
        Customer(
            id=f"customer-{broker_id}",
            broker_id=broker_id,
            broker_source_id=f"source-{broker_id}",
            source_customer_id=f"source-customer-{broker_id}",
            name=broker_id,
            created_at=NOW,
            updated_at=NOW,
        )
    )
    session.flush()


def add_carrier(session: Session, broker_id: str, carrier_id: str = "carrier") -> Carrier:
    carrier = Carrier(
        id=carrier_id,
        broker_id=broker_id,
        broker_source_id=f"source-{broker_id}",
        source_carrier_id=carrier_id,
        name=carrier_id,
        created_at=NOW,
        updated_at=NOW,
    )
    session.add(carrier)
    session.flush()
    return carrier


def add_load(
    session: Session,
    broker_id: str,
    load_id: str,
    status: LoadStatus,
    origin: tuple[str, str, str],
    destination: tuple[str, str, str],
    carrier_id: Optional[str] = None,
    equipment: EquipmentType = EquipmentType.DRY_VAN,
    carrier_rate: Optional[Decimal] = None,
    distance_miles: Optional[Decimal] = Decimal("200.0"),
    last_synced_at: datetime = NOW,
    source_updated_at: Optional[datetime] = None,
    booked_at: Optional[datetime] = None,
    scheduled_date: Optional[date] = None,
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
        carrier_id=carrier_id,
        equipment_type=equipment,
        distance_miles=distance_miles,
        carrier_rate=carrier_rate,
        source_updated_at=source_updated_at,
        booked_at=booked_at,
        first_seen_at=NOW,
        last_synced_at=last_synced_at,
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
                scheduled_date=scheduled_date,
            ),
        ]
    )
    session.flush()
    return load


def test_rate_estimation_uses_later_ingestion_and_excludes_future_evidence(
    db_session: Session,
) -> None:
    carrier = setup_broker(db_session)
    add_load(
        db_session,
        "broker-a",
        "target",
        LoadStatus.ACTIVE,
        ("Dallas", "TX", "75201"),
        ("Houston", "TX", "77002"),
        last_synced_at=NOW - timedelta(days=30),
    )
    for index in range(3):
        add_load(
            db_session,
            "broker-a",
            f"valid-{index}",
            LoadStatus.COMPLETED,
            ("Dallas", "TX", "75201"),
            ("Houston", "TX", "77002"),
            carrier_id=carrier.id,
            carrier_rate=Decimal("2000"),
            last_synced_at=NOW,
        )
    future = datetime(2099, 1, 1, tzinfo=timezone.utc)
    for index, future_fields in enumerate(
        (
            {"source_updated_at": future},
            {"booked_at": future},
            {"scheduled_date": future.date()},
        )
    ):
        add_load(
            db_session,
            "broker-a",
            f"future-{index}",
            LoadStatus.COMPLETED,
            ("Dallas", "TX", "75201"),
            ("Houston", "TX", "77002"),
            carrier_id=carrier.id,
            carrier_rate=Decimal("9000"),
            last_synced_at=NOW,
            **future_fields,
        )
    db_session.commit()

    result = estimate_carrier_rate(db_session, "broker-a", "target")

    assert result is not None
    assert result.status == "estimated"
    assert result.sample_size == 3
    assert result.estimate_amount == Decimal("2000.00")


def setup_broker(session: Session, broker_id: str = "broker-a") -> Carrier:
    add_broker(session, broker_id)
    return add_carrier(session, broker_id)


def test_exact_lane_equipment_uses_median_rpm_and_decimal_range(db_session: Session) -> None:
    carrier = setup_broker(db_session)
    add_load(
        db_session,
        "broker-a",
        "target",
        LoadStatus.ACTIVE,
        ("Dallas", "TX", "75201"),
        ("Houston", "TX", "77002"),
        distance_miles=Decimal("200.0"),
    )
    for index, rate in enumerate((Decimal("1800"), Decimal("2000"), Decimal("2200"))):
        add_load(
            db_session,
            "broker-a",
            f"history-{index}",
            LoadStatus.COMPLETED,
            ("Dallas", "TX", "75201"),
            ("Houston", "TX", "77002"),
            carrier_id=carrier.id,
            carrier_rate=rate,
            distance_miles=Decimal("200.0"),
            last_synced_at=NOW - timedelta(days=index),
        )
    db_session.commit()

    result = estimate_carrier_rate(db_session, "broker-a", "target")

    assert result is not None
    assert result.status == "estimated"
    assert result.selected_tier == "exact_lane_equipment"
    assert result.calculation_mode == "median_rate_per_mile"
    assert result.estimate_amount == Decimal("2000.00")
    assert result.low_amount == Decimal("1900.00")
    assert result.high_amount == Decimal("2100.00")
    assert result.sample_size == 3


def test_estimation_batches_target_and_history_reads(db_session: Session) -> None:
    carrier = setup_broker(db_session)
    add_load(
        db_session,
        "broker-a",
        "target",
        LoadStatus.ACTIVE,
        ("Dallas", "TX", "75201"),
        ("Houston", "TX", "77002"),
    )
    for index in range(3):
        add_load(
            db_session,
            "broker-a",
            f"history-{index}",
            LoadStatus.COMPLETED,
            ("Dallas", "TX", "75201"),
            ("Houston", "TX", "77002"),
            carrier_id=carrier.id,
            carrier_rate=Decimal("2000"),
            last_synced_at=NOW - timedelta(days=index),
        )
    db_session.commit()

    statements: list[str] = []

    def record_select(connection, cursor, statement, parameters, context, executemany):
        del connection, cursor, parameters, context, executemany
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    event.listen(db_session.bind, "before_cursor_execute", record_select)
    try:
        result = estimate_carrier_rate(db_session, "broker-a", "target")
    finally:
        event.remove(db_session.bind, "before_cursor_execute", record_select)

    assert result is not None
    assert len(statements) == 3


def test_thin_exact_history_falls_back_to_metro_equipment(db_session: Session) -> None:
    carrier = setup_broker(db_session)
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
        "exact",
        LoadStatus.COMPLETED,
        ("Dallas", "TX", "75201"),
        ("Houston", "TX", "77002"),
        carrier_id=carrier.id,
        carrier_rate=Decimal("1900"),
    )
    for index in range(3):
        add_load(
            db_session,
            "broker-a",
            f"metro-{index}",
            LoadStatus.COMPLETED,
            ("Plano", "TX", "75024"),
            ("Katy", "TX", "77494"),
            carrier_id=carrier.id,
            carrier_rate=Decimal("2000"),
        )
    db_session.commit()

    result = estimate_carrier_rate(db_session, "broker-a", "target")

    assert result is not None
    assert result.selected_tier == "metro_lane_equipment"
    assert result.sample_size == 4
    assert result.attempted_tiers[0].tier == "exact_lane_equipment"


def test_estimation_is_directional_and_broker_scoped(db_session: Session) -> None:
    carrier = setup_broker(db_session)
    add_broker(db_session, "broker-b")
    other_carrier = add_carrier(db_session, "broker-b", "other-carrier")
    add_load(
        db_session,
        "broker-a",
        "target",
        LoadStatus.ACTIVE,
        ("Dallas", "TX", "75201"),
        ("Houston", "TX", "77002"),
    )
    for index in range(3):
        add_load(
            db_session,
            "broker-b",
            f"reverse-{index}",
            LoadStatus.COMPLETED,
            ("Houston", "TX", "77002"),
            ("Dallas", "TX", "75201"),
            carrier_id=other_carrier.id,
            carrier_rate=Decimal("9000"),
        )
    add_load(
        db_session,
        "broker-a",
        "thin",
        LoadStatus.COMPLETED,
        ("Dallas", "TX", "75201"),
        ("Houston", "TX", "77002"),
        carrier_id=carrier.id,
        carrier_rate=Decimal("1900"),
    )
    db_session.commit()

    result = estimate_carrier_rate(db_session, "broker-a", "target")

    assert result is not None
    assert result.status == "unavailable"
    assert result.source_types == ()


def test_completed_only_and_rate_quality_exclusions_are_explained(db_session: Session) -> None:
    carrier = setup_broker(db_session)
    add_load(
        db_session,
        "broker-a",
        "target",
        LoadStatus.ACTIVE,
        ("Dallas", "TX", "75201"),
        ("Houston", "TX", "77002"),
    )
    for index, status in enumerate(
        (LoadStatus.ACTIVE, LoadStatus.COMPLETED, LoadStatus.COMPLETED, LoadStatus.COMPLETED)
    ):
        add_load(
            db_session,
            "broker-a",
            f"quality-{index}",
            status,
            ("Dallas", "TX", "75201"),
            ("Houston", "TX", "77002"),
            carrier_id=carrier.id,
            carrier_rate=(None if index == 0 else Decimal("0" if index == 1 else "1900")),
        )
    add_load(
        db_session,
        "broker-a",
        "negative",
        LoadStatus.COMPLETED,
        ("Dallas", "TX", "75201"),
        ("Houston", "TX", "77002"),
        carrier_id=carrier.id,
        carrier_rate=Decimal("-10"),
    )
    db_session.commit()

    result = estimate_carrier_rate(db_session, "broker-a", "target")

    assert result is not None
    assert result.status == "unavailable"
    assert result.excluded_counts == {
        "null_rate": 0,
        "nonpositive_rate": 2,
        "unresolved_lane": 0,
        "missing_distance_from_rpm": 0,
    }


def test_365_day_fallback_and_unavailable_result(db_session: Session) -> None:
    carrier = setup_broker(db_session)
    add_load(
        db_session,
        "broker-a",
        "target",
        LoadStatus.ACTIVE,
        ("Dallas", "TX", "75201"),
        ("Houston", "TX", "77002"),
    )
    for index in range(3):
        add_load(
            db_session,
            "broker-a",
            f"old-{index}",
            LoadStatus.COMPLETED,
            ("Dallas", "TX", "75201"),
            ("Houston", "TX", "77002"),
            carrier_id=carrier.id,
            carrier_rate=Decimal("2000"),
            last_synced_at=NOW - timedelta(days=200 + index),
        )
    db_session.commit()

    result = estimate_carrier_rate(db_session, "broker-a", "target")

    assert result is not None
    assert result.status == "estimated"
    assert result.lookback_days == 365
    assert result.confidence_level == "low"


@pytest.mark.parametrize(
    ("sample_count", "confidence"),
    ((8, "medium"), (10, "high")),
)
def test_exact_lane_confidence_levels_use_sample_thresholds(
    db_session: Session, sample_count: int, confidence: str
) -> None:
    carrier = setup_broker(db_session)
    add_load(
        db_session,
        "broker-a",
        "target",
        LoadStatus.ACTIVE,
        ("Dallas", "TX", "75201"),
        ("Houston", "TX", "77002"),
    )
    for index in range(sample_count):
        add_load(
            db_session,
            "broker-a",
            f"confidence-{index}",
            LoadStatus.COMPLETED,
            ("Dallas", "TX", "75201"),
            ("Houston", "TX", "77002"),
            carrier_id=carrier.id,
            carrier_rate=Decimal("2000"),
            last_synced_at=NOW - timedelta(days=index),
        )
    db_session.commit()

    result = estimate_carrier_rate(db_session, "broker-a", "target")

    assert result is not None
    assert result.selected_tier == "exact_lane_equipment"
    assert result.sample_size == sample_count
    assert result.confidence_level == confidence


def test_metro_lane_any_equipment_is_selected_before_broker_fallback(
    db_session: Session,
) -> None:
    carrier = setup_broker(db_session)
    add_load(
        db_session,
        "broker-a",
        "target",
        LoadStatus.ACTIVE,
        ("Dallas", "TX", "75201"),
        ("Houston", "TX", "77002"),
    )
    for index, equipment in enumerate(
        (EquipmentType.DRY_VAN, EquipmentType.DRY_VAN, EquipmentType.REEFER)
    ):
        add_load(
            db_session,
            "broker-a",
            f"metro-any-{index}",
            LoadStatus.COMPLETED,
            ("Plano", "TX", "75024"),
            ("Katy", "TX", "77494"),
            carrier_id=carrier.id,
            carrier_rate=Decimal("2000"),
            equipment=equipment,
        )
    db_session.commit()

    result = estimate_carrier_rate(db_session, "broker-a", "target")

    assert result is not None
    assert result.selected_tier == "metro_lane_any_equipment"
    assert result.sample_size == 3


def test_missing_distance_is_reported_when_it_makes_a_tier_unusable(
    db_session: Session,
) -> None:
    carrier = setup_broker(db_session)
    add_load(
        db_session,
        "broker-a",
        "target",
        LoadStatus.ACTIVE,
        ("Dallas", "TX", "75201"),
        ("Houston", "TX", "77002"),
    )
    for index, distance in enumerate((None, None, Decimal("200"))):
        add_load(
            db_session,
            "broker-a",
            f"missing-distance-{index}",
            LoadStatus.COMPLETED,
            ("Dallas", "TX", "75201"),
            ("Houston", "TX", "77002"),
            carrier_id=carrier.id,
            carrier_rate=Decimal("2000"),
            distance_miles=distance,
        )
    db_session.commit()

    result = estimate_carrier_rate(db_session, "broker-a", "target")

    assert result is not None
    assert result.status == "unavailable"
    assert result.excluded_counts["missing_distance_from_rpm"] == 2
    assert result.attempted_tiers[0].reason == "insufficient usable observations"


def test_exact_lane_without_target_distance_uses_raw_total_mode(db_session: Session) -> None:
    carrier = setup_broker(db_session)
    add_load(
        db_session,
        "broker-a",
        "target",
        LoadStatus.ACTIVE,
        ("Dallas", "TX", "75201"),
        ("Houston", "TX", "77002"),
        distance_miles=None,
    )
    for index, rate in enumerate((Decimal("1800"), Decimal("2000"), Decimal("2200"))):
        add_load(
            db_session,
            "broker-a",
            f"raw-{index}",
            LoadStatus.COMPLETED,
            ("Dallas", "TX", "75201"),
            ("Houston", "TX", "77002"),
            carrier_id=carrier.id,
            carrier_rate=rate,
            distance_miles=None,
        )
    db_session.commit()

    result = estimate_carrier_rate(db_session, "broker-a", "target")

    assert result is not None
    assert result.status == "estimated"
    assert result.calculation_mode == "median_all_in_total"
    assert result.estimate_amount == Decimal("2000.00")


def test_unknown_target_equipment_uses_known_exact_lane_history(
    db_session: Session,
) -> None:
    carrier = setup_broker(db_session)
    add_load(
        db_session,
        "broker-a",
        "target",
        LoadStatus.ACTIVE,
        ("Dallas", "TX", "75201"),
        ("Houston", "TX", "77002"),
        equipment=EquipmentType.UNKNOWN,
    )
    for index in range(3):
        add_load(
            db_session,
            "broker-a",
            f"known-{index}",
            LoadStatus.COMPLETED,
            ("Dallas", "TX", "75201"),
            ("Houston", "TX", "77002"),
            carrier_id=carrier.id,
            carrier_rate=Decimal("2000"),
            equipment=EquipmentType.DRY_VAN,
        )
    db_session.commit()

    result = estimate_carrier_rate(db_session, "broker-a", "target")

    assert result is not None
    assert result.selected_tier == "exact_lane_any_equipment"
    assert "Target equipment is unknown" in result.confidence_reasons


def test_api_returns_estimated_unavailable_and_version_errors(db_session: Session) -> None:
    carrier = setup_broker(db_session)
    add_load(
        db_session,
        "broker-a",
        "target",
        LoadStatus.ACTIVE,
        ("Dallas", "TX", "75201"),
        ("Houston", "TX", "77002"),
    )
    for index in range(3):
        add_load(
            db_session,
            "broker-a",
            f"history-{index}",
            LoadStatus.COMPLETED,
            ("Dallas", "TX", "75201"),
            ("Houston", "TX", "77002"),
            carrier_id=carrier.id,
            carrier_rate=Decimal("2000"),
        )
    covered = add_load(
        db_session,
        "broker-a",
        "covered",
        LoadStatus.COVERED,
        ("Dallas", "TX", "75201"),
        ("Houston", "TX", "77002"),
        carrier_id=carrier.id,
    )
    add_load(
        db_session,
        "broker-a",
        "unavailable",
        LoadStatus.ACTIVE,
        ("Austin", "TX", "78701"),
        ("San Antonio", "TX", "78205"),
        equipment=EquipmentType.UNKNOWN,
    )
    db_session.commit()

    application = create_app()

    def override_db():
        yield db_session

    application.dependency_overrides[get_db] = override_db
    with TestClient(application) as client:
        client.headers.update(auth_headers())
        response = client.get("/brokers/broker-a/loads/target/carrier-rate-estimate")
        unsupported = client.get(
            "/brokers/broker-a/loads/target/carrier-rate-estimate",
            params={"estimation_version": "carrier-rate-v0"},
        )
        unsupported_normalization = client.get(
            "/brokers/broker-a/loads/target/carrier-rate-estimate",
            params={"normalization_version": "tx-metro-v2"},
        )
        unavailable = client.get("/brokers/broker-a/loads/unavailable/carrier-rate-estimate")
        ineligible = client.get(f"/brokers/broker-a/loads/{covered.id}/carrier-rate-estimate")
        missing = client.get("/brokers/broker-a/loads/missing/carrier-rate-estimate")

    assert response.status_code == 200
    assert response.json()["status"] == "estimated"
    assert response.json()["estimate"]["amount"] == "2000.00"
    assert response.json()["method"]["currency"] == "USD"
    assert response.json()["method"]["correction_policy"] == "one_current_effective_total_per_load"
    assert unsupported.status_code == 422
    assert unsupported_normalization.status_code == 422
    assert unavailable.status_code == 200
    assert unavailable.json()["status"] == "unavailable"
    assert unavailable.json()["estimate"]["amount"] is None
    assert unavailable.json()["confidence"]["level"] == "none"
    assert ineligible.status_code == 409
    assert missing.status_code == 404
