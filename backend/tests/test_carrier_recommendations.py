from datetime import date, datetime, timedelta, timezone
from typing import Generator, Optional

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.carrier_recommendations import (
    RecommendationNotEligible,
    get_carrier_recommendations,
)
from app.database import get_db
from app.main import create_app
from app.models import (
    Base,
    Broker,
    BrokerSource,
    Carrier,
    CarrierIdentity,
    Customer,
    EquipmentType,
    Load,
    LoadStatus,
    LoadStop,
    StopType,
    TmsType,
)
from tests.auth_helpers import auth_headers

NOW = datetime(2026, 7, 16, tzinfo=timezone.utc)


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def add_broker(
    session: Session, broker_id: str, source_ids: tuple[str, ...] = ("source-a",)
) -> None:
    session.add(Broker(id=broker_id, name=f"Broker {broker_id}", created_at=NOW))
    for index, source_id in enumerate(source_ids):
        session.add(
            BrokerSource(
                id=source_id,
                broker_id=broker_id,
                tms_type=(TmsType.FREIGHTFLOW if index == 0 else TmsType.HAULDESK),
                source_name=f"Source {source_id}",
                created_at=NOW,
            )
        )
        session.add(
            Customer(
                id=f"customer-{source_id}",
                broker_id=broker_id,
                broker_source_id=source_id,
                source_customer_id=f"source-customer-{source_id}",
                name=f"Customer {source_id}",
                created_at=NOW,
                updated_at=NOW,
            )
        )
    session.flush()


def add_carrier(
    session: Session,
    broker_id: str,
    source_id: str,
    carrier_id: str,
    name: str,
    identity_id: Optional[str] = None,
) -> Carrier:
    carrier = Carrier(
        id=carrier_id,
        broker_id=broker_id,
        broker_source_id=source_id,
        carrier_identity_id=identity_id,
        source_carrier_id=f"source-{carrier_id}",
        name=name,
        created_at=NOW,
        updated_at=NOW,
    )
    session.add(carrier)
    session.flush()
    return carrier


def add_load(
    session: Session,
    broker_id: str,
    source_id: str,
    load_id: str,
    status: LoadStatus,
    origin: tuple[str, str, str],
    destination: tuple[str, str, str],
    carrier_id: Optional[str] = None,
    equipment: EquipmentType = EquipmentType.DRY_VAN,
    customer_id: Optional[str] = None,
    actual_destination: Optional[datetime] = None,
    last_synced_at: Optional[datetime] = None,
    scheduled_date: Optional[date] = None,
) -> Load:
    load = Load(
        id=load_id,
        broker_id=broker_id,
        broker_source_id=source_id,
        source_load_id=load_id,
        display_number=load_id,
        status=status,
        customer_id=customer_id or f"customer-{source_id}",
        carrier_id=carrier_id,
        equipment_type=equipment,
        first_seen_at=NOW,
        last_synced_at=last_synced_at or NOW,
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
                actual_arrived_at=actual_destination,
                scheduled_date=scheduled_date,
            ),
        ]
    )
    session.flush()
    return load


def test_exact_same_equipment_ranks_above_nearby_history(db_session: Session) -> None:
    add_broker(db_session, "broker-a")
    exact = add_carrier(db_session, "broker-a", "source-a", "exact", "Exact Carrier")
    nearby = add_carrier(db_session, "broker-a", "source-a", "nearby", "Nearby Carrier")
    add_carrier(db_session, "broker-a", "source-a", "new", "New Carrier")
    add_load(
        db_session,
        "broker-a",
        "source-a",
        "target",
        LoadStatus.ACTIVE,
        ("Dallas", "TX", "75201"),
        ("Houston", "TX", "77002"),
    )
    add_load(
        db_session,
        "broker-a",
        "source-a",
        "exact-load",
        LoadStatus.COMPLETED,
        ("Dallas", "TX", "75201"),
        ("Houston", "TX", "77002"),
        carrier_id=exact.id,
        actual_destination=datetime(2026, 7, 12, tzinfo=timezone.utc),
    )
    add_load(
        db_session,
        "broker-a",
        "source-a",
        "nearby-load",
        LoadStatus.COMPLETED,
        ("Plano", "TX", "75024"),
        ("Katy", "TX", "77494"),
        carrier_id=nearby.id,
        actual_destination=datetime(2026, 7, 12, tzinfo=timezone.utc),
    )
    db_session.commit()

    result = get_carrier_recommendations(db_session, "broker-a", "target")

    assert result is not None
    assert [item.name for item in result.recommendations] == [
        "Exact Carrier",
        "Nearby Carrier",
    ]
    assert result.recommendations[0].score > result.recommendations[1].score
    assert result.unscored_carriers[0].name == "New Carrier"
    assert result.recommendations[0].factors[0].code == "exact_lane_same_equipment"
    assert result.recommendations[0].evidence[0].origin_postal_code == "75201"
    assert result.recommendations[0].evidence[0].destination_postal_code == "77002"
    assert result.recommendations[0].evidence[0].completed_month == "2026-07"
    assert result.recommendations[0].evidence[0].outcome == "completed"


def test_identity_rows_are_aggregated_once_and_unlinked_same_names_stay_separate(
    db_session: Session,
) -> None:
    add_broker(db_session, "broker-a", ("source-a", "source-b"))
    db_session.add(
        CarrierIdentity(
            id="identity-1",
            broker_id="broker-a",
            normalized_mc_number="120001",
            created_at=NOW,
            updated_at=NOW,
        )
    )
    db_session.flush()
    first = add_carrier(
        db_session, "broker-a", "source-a", "carrier-a", "Lone Star Logistics", "identity-1"
    )
    second = add_carrier(
        db_session, "broker-a", "source-b", "carrier-b", "Lone Star Logistics", "identity-1"
    )
    standalone_a = add_carrier(
        db_session, "broker-a", "source-a", "standalone-a", "Same Name Carrier"
    )
    standalone_b = add_carrier(
        db_session, "broker-a", "source-b", "standalone-b", "Same Name Carrier"
    )
    add_load(
        db_session,
        "broker-a",
        "source-a",
        "target",
        LoadStatus.ACTIVE,
        ("Dallas", "TX", "75201"),
        ("Houston", "TX", "77002"),
    )
    add_load(
        db_session,
        "broker-a",
        "source-a",
        "history-a",
        LoadStatus.COMPLETED,
        ("Dallas", "TX", "75201"),
        ("Houston", "TX", "77002"),
        carrier_id=first.id,
    )
    add_load(
        db_session,
        "broker-a",
        "source-a",
        "history-b",
        LoadStatus.COMPLETED,
        ("Dallas", "TX", "75201"),
        ("Houston", "TX", "77002"),
        carrier_id=second.id,
    )
    db_session.commit()

    result = get_carrier_recommendations(db_session, "broker-a", "target")

    assert result is not None
    assert len(result.recommendations) == 1
    assert result.recommendations[0].candidate_id == "identity:identity-1"
    assert result.recommendations[0].carrier_ids == ("carrier-a", "carrier-b")
    assert result.recommendations[0].exact_count == 2
    assert {item.name for item in result.unscored_carriers} == {"Same Name Carrier"}
    assert len(result.unscored_carriers) == 2
    assert {item.candidate_id for item in result.unscored_carriers} == {
        f"carrier:{standalone_a.id}",
        f"carrier:{standalone_b.id}",
    }


def test_recommendations_are_broker_scoped_and_cold_starts_are_unscored(
    db_session: Session,
) -> None:
    add_broker(db_session, "broker-a")
    add_broker(db_session, "broker-b", ("source-b",))
    carrier_a = add_carrier(db_session, "broker-a", "source-a", "carrier-a", "Broker A Carrier")
    carrier_b = add_carrier(db_session, "broker-b", "source-b", "carrier-b", "Broker B Carrier")
    add_load(
        db_session,
        "broker-a",
        "source-a",
        "target",
        LoadStatus.ACTIVE,
        ("Dallas", "TX", "75201"),
        ("Houston", "TX", "77002"),
    )
    add_load(
        db_session,
        "broker-b",
        "source-b",
        "other-history",
        LoadStatus.COMPLETED,
        ("Dallas", "TX", "75201"),
        ("Houston", "TX", "77002"),
        carrier_id=carrier_b.id,
    )
    db_session.commit()

    result = get_carrier_recommendations(db_session, "broker-a", "target")

    assert result is not None
    assert result.recommendations == ()
    assert [item.candidate_id for item in result.unscored_carriers] == [f"carrier:{carrier_a.id}"]


def test_unknown_equipment_does_not_create_equipment_fit_evidence(
    db_session: Session,
) -> None:
    add_broker(db_session, "broker-a")
    carrier = add_carrier(db_session, "broker-a", "source-a", "carrier-a", "Carrier A")
    add_load(
        db_session,
        "broker-a",
        "source-a",
        "target",
        LoadStatus.ACTIVE,
        ("Dallas", "TX", "75201"),
        ("Houston", "TX", "77002"),
    )
    add_load(
        db_session,
        "broker-a",
        "source-a",
        "unknown-equipment",
        LoadStatus.COMPLETED,
        ("Dallas", "TX", "75201"),
        ("Houston", "TX", "77002"),
        carrier_id=carrier.id,
        equipment=EquipmentType.UNKNOWN,
    )
    db_session.commit()

    result = get_carrier_recommendations(db_session, "broker-a", "target")

    assert result is not None
    recommendation = result.recommendations[0]
    assert recommendation.exact_same_equipment_count == 0
    assert recommendation.same_equipment_count == 0
    assert recommendation.score == 3


@pytest.mark.parametrize(
    ("age", "expected"),
    ((timedelta(days=7), 5), (timedelta(days=30), 3), (timedelta(days=90), 1)),
)
def test_recency_points_use_inclusive_utc_boundaries(age: timedelta, expected: int) -> None:
    from app.carrier_recommendations import _recency_points

    as_of = NOW
    assert _recency_points(as_of - age, as_of) == expected


def test_recommendations_exclude_operational_evidence_newer_than_target_as_of(
    db_session: Session,
) -> None:
    add_broker(db_session, "broker-a")
    carrier = add_carrier(db_session, "broker-a", "source-a", "carrier-a", "Carrier A")
    add_load(
        db_session,
        "broker-a",
        "source-a",
        "target",
        LoadStatus.ACTIVE,
        ("Dallas", "TX", "75201"),
        ("Houston", "TX", "77002"),
    )
    add_load(
        db_session,
        "broker-a",
        "source-a",
        "future-evidence",
        LoadStatus.COMPLETED,
        ("Dallas", "TX", "75201"),
        ("Houston", "TX", "77002"),
        carrier_id=carrier.id,
        actual_destination=NOW + timedelta(days=1),
        last_synced_at=NOW - timedelta(days=1),
    )
    db_session.commit()

    result = get_carrier_recommendations(db_session, "broker-a", "target")

    assert result is not None
    assert result.recommendations == ()
    assert result.unscored_carriers[0].candidate_id == "carrier:carrier-a"


def test_recommendations_exclude_future_snapshot_without_operational_evidence(
    db_session: Session,
) -> None:
    add_broker(db_session, "broker-a")
    carrier = add_carrier(db_session, "broker-a", "source-a", "carrier-a", "Carrier A")
    add_load(
        db_session,
        "broker-a",
        "source-a",
        "target",
        LoadStatus.ACTIVE,
        ("Dallas", "TX", "75201"),
        ("Houston", "TX", "77002"),
    )
    add_load(
        db_session,
        "broker-a",
        "source-a",
        "future-snapshot",
        LoadStatus.COMPLETED,
        ("Dallas", "TX", "75201"),
        ("Houston", "TX", "77002"),
        carrier_id=carrier.id,
        actual_destination=None,
        last_synced_at=NOW + timedelta(days=1),
    )
    db_session.commit()

    result = get_carrier_recommendations(db_session, "broker-a", "target")

    assert result is not None
    assert result.recommendations == ()
    assert result.unscored_carriers[0].candidate_id == "carrier:carrier-a"


def test_recommendations_exclude_future_scheduled_date(db_session: Session) -> None:
    add_broker(db_session, "broker-a")
    carrier = add_carrier(db_session, "broker-a", "source-a", "carrier-a", "Carrier A")
    add_load(
        db_session,
        "broker-a",
        "source-a",
        "target",
        LoadStatus.ACTIVE,
        ("Dallas", "TX", "75201"),
        ("Houston", "TX", "77002"),
    )
    add_load(
        db_session,
        "broker-a",
        "source-a",
        "future-scheduled",
        LoadStatus.COMPLETED,
        ("Dallas", "TX", "75201"),
        ("Houston", "TX", "77002"),
        carrier_id=carrier.id,
        scheduled_date=NOW.date() + timedelta(days=1),
    )
    db_session.commit()

    result = get_carrier_recommendations(db_session, "broker-a", "target")

    assert result is not None
    assert result.recommendations == ()


def test_datetime_normalization_is_utc() -> None:
    from app.carrier_recommendations import _as_utc

    naive = datetime(2026, 7, 16, 12, 0)
    converted = _as_utc(naive)

    assert converted.tzinfo == timezone.utc
    assert converted.hour == 12


def test_history_window_uses_most_recent_500_loads(db_session: Session) -> None:
    add_broker(db_session, "broker-a")
    carrier = add_carrier(db_session, "broker-a", "source-a", "carrier-a", "Carrier A")
    add_load(
        db_session,
        "broker-a",
        "source-a",
        "target",
        LoadStatus.ACTIVE,
        ("Dallas", "TX", "75201"),
        ("Houston", "TX", "77002"),
    )
    for index in range(501):
        add_load(
            db_session,
            "broker-a",
            "source-a",
            f"history-{index}",
            LoadStatus.COMPLETED,
            ("Dallas", "TX", "75201"),
            ("Houston", "TX", "77002"),
            carrier_id=carrier.id,
            last_synced_at=NOW - timedelta(minutes=index),
        )
    db_session.commit()

    result = get_carrier_recommendations(db_session, "broker-a", "target")

    assert result is not None
    recommendation = result.recommendations[0]
    assert recommendation.exact_count == 500
    assert (
        next(
            factor for factor in recommendation.factors if factor.code == "overall_history"
        ).evidence_count
        == 500
    )


def test_target_must_be_active_and_uncovered(db_session: Session) -> None:
    add_broker(db_session, "broker-a")
    carrier = add_carrier(db_session, "broker-a", "source-a", "carrier-a", "Carrier A")
    add_load(
        db_session,
        "broker-a",
        "source-a",
        "covered",
        LoadStatus.COVERED,
        ("Dallas", "TX", "75201"),
        ("Houston", "TX", "77002"),
        carrier_id=carrier.id,
    )
    db_session.commit()

    with pytest.raises(RecommendationNotEligible, match="active and uncovered"):
        get_carrier_recommendations(db_session, "broker-a", "covered")


def test_recommendation_api_returns_metadata_and_errors(db_session: Session) -> None:
    add_broker(db_session, "broker-a")
    carrier = add_carrier(db_session, "broker-a", "source-a", "carrier-a", "Carrier A")
    second_carrier = add_carrier(db_session, "broker-a", "source-a", "carrier-b", "Carrier B")
    add_carrier(db_session, "broker-a", "source-a", "carrier-c", "Cold Start Carrier")
    add_load(
        db_session,
        "broker-a",
        "source-a",
        "target",
        LoadStatus.ACTIVE,
        ("Dallas", "TX", "75201"),
        ("Houston", "TX", "77002"),
    )
    add_load(
        db_session,
        "broker-a",
        "source-a",
        "history",
        LoadStatus.COMPLETED,
        ("Dallas", "TX", "75201"),
        ("Houston", "TX", "77002"),
        carrier_id=carrier.id,
    )
    add_load(
        db_session,
        "broker-a",
        "source-a",
        "history-second",
        LoadStatus.COMPLETED,
        ("Dallas", "TX", "75201"),
        ("Houston", "TX", "77002"),
        carrier_id=second_carrier.id,
    )
    covered = add_load(
        db_session,
        "broker-a",
        "source-a",
        "covered",
        LoadStatus.COVERED,
        ("Dallas", "TX", "75201"),
        ("Houston", "TX", "77002"),
        carrier_id=carrier.id,
    )
    db_session.commit()

    application = create_app()

    def override_db() -> Generator[Session, None, None]:
        yield db_session

    application.dependency_overrides[get_db] = override_db
    with TestClient(application) as client:
        client.headers.update(auth_headers())
        response = client.get("/brokers/broker-a/loads/target/carrier-recommendations")
        missing = client.get("/brokers/broker-a/loads/missing/carrier-recommendations")
        unsupported = client.get(
            "/brokers/broker-a/loads/target/carrier-recommendations",
            params={"scoring_version": "carrier-recommendations-v0"},
        )
        invalid_limit = client.get(
            "/brokers/broker-a/loads/target/carrier-recommendations",
            params={"limit": 0},
        )
        limited = client.get(
            "/brokers/broker-a/loads/target/carrier-recommendations",
            params={"limit": 1},
        )
        unsupported_normalization = client.get(
            "/brokers/broker-a/loads/target/carrier-recommendations",
            params={"normalization_version": "tx-metro-v2"},
        )
        ineligible = client.get(f"/brokers/broker-a/loads/{covered.id}/carrier-recommendations")

    assert response.status_code == 200
    assert response.json()["scoring_version"] == "carrier-recommendations-v1"
    assert response.json()["history_limit"] == 500
    assert response.json()["recommendations"][0]["rank"] == 1
    assert len(response.json()["recommendations"]) == 2
    assert len(response.json()["unscored_carriers"]) == 1
    assert missing.status_code == 404
    assert unsupported.status_code == 422
    assert invalid_limit.status_code == 422
    assert limited.status_code == 200
    assert len(limited.json()["recommendations"]) == 1
    assert limited.json()["recommendations"][0]["rank"] == 1
    assert len(limited.json()["unscored_carriers"]) == 1
    assert unsupported_normalization.status_code == 422
    assert ineligible.status_code == 409


def test_recommendation_api_returns_422_for_non_derivable_target(db_session: Session) -> None:
    add_broker(db_session, "broker-a")
    load = add_load(
        db_session,
        "broker-a",
        "source-a",
        "invalid",
        LoadStatus.ACTIVE,
        ("Dallas", "TX", "75201"),
        ("Houston", "TX", "77002"),
    )
    destination = db_session.query(LoadStop).filter_by(load_id=load.id, sequence_number=2).one()
    db_session.delete(destination)
    db_session.commit()

    application = create_app()

    def override_db() -> Generator[Session, None, None]:
        yield db_session

    application.dependency_overrides[get_db] = override_db
    with TestClient(application) as client:
        client.headers.update(auth_headers())
        response = client.get("/brokers/broker-a/loads/invalid/carrier-recommendations")

    assert response.status_code == 422
    assert response.json()["detail"] == "load must have pickup and delivery stops"
