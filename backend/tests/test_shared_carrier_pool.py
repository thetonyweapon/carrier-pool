from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import issue_demo_token
from app.config import settings
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
    PlatformAssignment,
    SharedPoolPolicyEvent,
    SharedPoolQueryAudit,
    StopType,
    TmsType,
)
from app.shared_carrier_pool import (
    SharedPoolDisabled,
    SharedPoolNotEligible,
    get_shared_carrier_recommendations,
    set_shared_pool_policy,
)
from app.shared_rate_estimation import get_shared_rate_estimate
from tests.auth_helpers import auth_headers

NOW = datetime(2026, 7, 16, 12, tzinfo=timezone.utc)


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


@pytest.fixture
def client(db_session: Session, monkeypatch):
    monkeypatch.setattr(settings, "shared_pool_read_enabled", True)
    monkeypatch.setattr(settings, "shared_pool_id_secret", "test-shared-pool-secret")
    monkeypatch.setattr(settings, "auth_secret", "test-auth-secret")
    application = create_app()

    def override_db():
        yield db_session

    application.dependency_overrides[get_db] = override_db
    with TestClient(application) as test_client:
        test_client.headers.update(auth_headers())
        yield test_client


def add_broker(session: Session, broker_id: str) -> None:
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
            name=f"Customer {broker_id}",
            created_at=NOW,
            updated_at=NOW,
        )
    )
    session.flush()


def add_shared_carrier(session: Session, broker_id: str) -> Carrier:
    identity = CarrierIdentity(
        id=f"identity-{broker_id}",
        broker_id=broker_id,
        normalized_mc_number="884201",
        created_at=NOW,
        updated_at=NOW,
    )
    carrier = Carrier(
        id=f"carrier-{broker_id}",
        broker_id=broker_id,
        broker_source_id=f"source-{broker_id}",
        carrier_identity_id=identity.id,
        source_carrier_id=f"source-carrier-{broker_id}",
        name="Lone Star Transport",
        mc_number="MC-884201",
        created_at=NOW,
        updated_at=NOW,
    )
    session.add_all([identity, carrier])
    session.flush()
    return carrier


def add_load(
    session: Session,
    broker_id: str,
    load_id: str,
    status: LoadStatus,
    carrier_id: Optional[str] = None,
    origin: tuple[str, str, str] = ("Dallas", "TX", "75201"),
    destination: tuple[str, str, str] = ("Houston", "TX", "77002"),
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
        equipment_type=EquipmentType.DRY_VAN,
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
                scheduled_date=scheduled_date,
            ),
        ]
    )
    session.flush()
    return load


def seed_shared_pool(session: Session) -> None:
    for broker_id in ("broker-a", "broker-b", "broker-c", "broker-d"):
        add_broker(session, broker_id)
        carrier = add_shared_carrier(session, broker_id)
        add_load(session, broker_id, f"history-{broker_id}", LoadStatus.COMPLETED, carrier.id)
        set_shared_pool_policy(session, broker_id, broker_id != "broker-d", "test-admin")
    add_load(session, "broker-a", "target", LoadStatus.ACTIVE)
    session.commit()


def test_shared_recommendation_requires_requester_opt_in(db_session: Session) -> None:
    add_broker(db_session, "broker-a")
    add_load(db_session, "broker-a", "target", LoadStatus.ACTIVE)
    db_session.commit()

    with pytest.raises(SharedPoolDisabled):
        get_shared_carrier_recommendations(
            db_session, "broker-a", "target", "test-shared-pool-secret"
        )


def test_shared_results_require_three_distinct_opted_in_contributors(db_session: Session) -> None:
    seed_shared_pool(db_session)

    result = get_shared_carrier_recommendations(
        db_session, "broker-a", "target", "test-shared-pool-secret"
    )

    assert result is not None
    assert len(result.recommendations) == 1
    recommendation = result.recommendations[0]
    assert recommendation.name == "Lone Star Transport"
    assert recommendation.match_quality == "exact"
    assert recommendation.evidence_count_bucket == "3-5"
    assert recommendation.contributing_broker_count_bucket == "3-5"
    assert recommendation.candidate_id.startswith("shared:")
    assert "identity-" not in recommendation.candidate_id
    assert db_session.scalar(
        select(SharedPoolQueryAudit).where(SharedPoolQueryAudit.load_id == "target")
    )


def test_shared_recommendations_exclude_future_scheduled_dates(db_session: Session) -> None:
    seed_shared_pool(db_session)
    for broker_id in ("broker-b", "broker-c", "broker-d"):
        pickup = db_session.scalar(
            select(LoadStop).where(
                LoadStop.load_id == f"history-{broker_id}",
                LoadStop.sequence_number == 1,
            )
        )
        assert pickup is not None
        pickup.scheduled_date = NOW.date() + timedelta(days=1)
    db_session.commit()

    result = get_shared_carrier_recommendations(
        db_session, "broker-a", "target", "test-shared-pool-secret"
    )

    assert result is not None
    assert result.recommendations == ()


def test_set_shared_pool_policy_sees_pending_broker_with_autoflush_disabled() -> None:
    """Regression: app.database.SessionLocal uses autoflush=False, so a freshly
    added (uncommitted) broker was invisible to Session.get inside
    set_shared_pool_policy, crashing bootstrap under docker compose with
    "ValueError: broker not found"."""
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    with session_factory() as session:
        session.add(Broker(id="broker-a", name="Ithaca Freight Partners", created_at=NOW))
        policy = set_shared_pool_policy(
            session, "broker-a", enabled=True, changed_by="demo-bootstrap"
        )
        assert policy.enabled is True
        assert session.get(Broker, "broker-a") is not None
        session.commit()
    engine.dispose()


def test_opt_out_revokes_future_shared_results_and_records_policy_event(
    db_session: Session,
) -> None:
    seed_shared_pool(db_session)
    set_shared_pool_policy(db_session, "broker-c", False, "test-admin", "revoked")
    db_session.commit()

    result = get_shared_carrier_recommendations(
        db_session, "broker-a", "target", "test-shared-pool-secret"
    )

    assert result is not None
    assert result.recommendations == ()
    events = db_session.scalars(
        select(SharedPoolPolicyEvent)
        .where(SharedPoolPolicyEvent.broker_id == "broker-c")
        .order_by(SharedPoolPolicyEvent.policy_revision)
    ).all()
    assert [(event.enabled, event.policy_revision) for event in events] == [(True, 1), (False, 2)]


def test_shared_rate_estimate_requires_three_brokers_and_returns_redacted_market_range(
    db_session: Session,
) -> None:
    seed_shared_pool(db_session)
    target = db_session.get(Load, "target")
    target.distance_miles = 100
    for broker_id, amount in (
        ("broker-a", "1000.00"),
        ("broker-b", "1100.00"),
        ("broker-c", "1200.00"),
    ):
        history = db_session.get(Load, f"history-{broker_id}")
        history.distance_miles = 100
        history.carrier_rate = Decimal(amount)
    db_session.commit()

    result = get_shared_rate_estimate(db_session, "broker-a", "target")

    assert result is not None
    assert result.status == "estimated"
    assert result.amount == 1100
    assert result.low == 1050
    assert result.high == 1150
    assert result.sample_count_bucket == "3-5"
    assert result.contributing_broker_count_bucket == "3-5"
    assert result.match_scope == "exact"


def test_shared_analytics_rejects_a_platform_assigned_target(db_session: Session) -> None:
    seed_shared_pool(db_session)
    carrier = db_session.get(Load, "history-broker-a").carrier_id
    db_session.add(
        PlatformAssignment(
            broker_id="broker-a",
            load_id="target",
            carrier_id=carrier,
            demo_actor="test-user",
            assignment_version=1,
            created_at=NOW,
            updated_at=NOW,
        )
    )
    db_session.commit()

    with pytest.raises(SharedPoolNotEligible):
        get_shared_rate_estimate(db_session, "broker-a", "target")


def test_shared_rate_estimate_rejects_load_without_derivable_lane(db_session: Session) -> None:
    seed_shared_pool(db_session)
    for stop in db_session.scalars(
        select(LoadStop).where(LoadStop.broker_id == "broker-a", LoadStop.load_id == "target")
    ).all():
        db_session.delete(stop)
    db_session.commit()

    with pytest.raises(SharedPoolNotEligible):
        get_shared_rate_estimate(db_session, "broker-a", "target")


def test_shared_rate_api_returns_only_aggregate_fields(
    db_session: Session, client: TestClient
) -> None:
    seed_shared_pool(db_session)
    target = db_session.get(Load, "target")
    target.distance_miles = 100
    for broker_id, amount in (
        ("broker-a", "1000.00"),
        ("broker-b", "1100.00"),
        ("broker-c", "1200.00"),
    ):
        history = db_session.get(Load, f"history-{broker_id}")
        history.distance_miles = 100
        history.carrier_rate = Decimal(amount)
    db_session.commit()

    response = client.get(
        "/brokers/broker-a/loads/target/shared-carrier-rate-estimate",
        headers={"Authorization": f"Bearer {issue_demo_token('broker-a')}"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["scope"] == "shared"
    assert body["estimate"]["amount"] == "1100.00"
    assert body["sample_count_bucket"] == "3-5"
    assert "source_types" not in body
    assert "oldest_rate_date" not in body


def test_shared_recommendations_require_identifier_secret(
    db_session: Session, client: TestClient, monkeypatch
) -> None:
    seed_shared_pool(db_session)
    monkeypatch.setattr(settings, "shared_pool_id_secret", None)

    response = client.get(
        "/brokers/broker-a/loads/target/shared-carrier-recommendations",
        headers={"Authorization": f"Bearer {issue_demo_token('broker-a')}"},
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "shared pool identifier secret is not configured"


def test_api_returns_redacted_shared_contract_and_audits_query(
    db_session: Session, client: TestClient
) -> None:
    seed_shared_pool(db_session)

    response = client.get(
        "/brokers/broker-a/loads/target/shared-carrier-recommendations",
        headers={"Authorization": f"Bearer {issue_demo_token('broker-a')}"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["recommendations"][0] == {
        "scope": "shared",
        "rank": 1,
        "candidate_id": body["recommendations"][0]["candidate_id"],
        "name": "Lone Star Transport",
        "match_quality": "exact",
        "equipment_type": "dry_van",
        "evidence_count_bucket": "3-5",
        "contributing_broker_count_bucket": "3-5",
    }
    assert "mc_number" not in body["recommendations"][0]
    assert "dot_number" not in body["recommendations"][0]
    assert "broker_id" not in body["recommendations"][0]
    assert db_session.scalar(select(func.count()).select_from(SharedPoolQueryAudit)) == 1


def test_authenticated_policy_api_supports_opt_out(db_session: Session, client: TestClient) -> None:
    seed_shared_pool(db_session)
    headers = {"Authorization": f"Bearer {issue_demo_token('broker-a')}"}

    response = client.get("/brokers/broker-a/shared-pool-policy", headers=headers)
    assert response.status_code == 200
    assert response.json()["enabled"] is True

    response = client.put(
        "/brokers/broker-a/shared-pool-policy",
        headers=headers,
        json={"enabled": False, "reason": "test opt out"},
    )
    assert response.status_code == 200
    assert response.json()["policy_revision"] == 2

    response = client.get("/brokers/broker-a/shared-pool-policy", headers=headers)
    assert response.json()["enabled"] is False


def test_shared_api_rejects_a_token_for_another_broker(
    db_session: Session, client: TestClient
) -> None:
    add_broker(db_session, "broker-a")
    db_session.commit()
    response = client.get(
        "/brokers/broker-a/shared-pool-policy",
        headers={"Authorization": f"Bearer {issue_demo_token('broker-b')}"},
    )
    assert response.status_code == 403


def test_shared_candidate_cannot_be_assigned_as_local_carrier(
    db_session: Session, client: TestClient, monkeypatch
) -> None:
    seed_shared_pool(db_session)
    monkeypatch.setattr(settings, "demo_mode", True)
    result = get_shared_carrier_recommendations(
        db_session, "broker-a", "target", "test-shared-pool-secret"
    )
    candidate_id = result.recommendations[0].candidate_id

    response = client.post(
        "/brokers/broker-a/loads/target/assignments",
        json={"candidate_id": candidate_id, "expected_assignment_version": 0},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "candidate must resolve to one broker carrier"
