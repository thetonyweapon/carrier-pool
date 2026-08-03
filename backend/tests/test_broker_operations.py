from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

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
    PlatformAssignmentEvent,
    StopType,
    TmsType,
)
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
def client(db_session: Session):
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
            source_name=f"TMS {broker_id}",
            created_at=NOW,
        )
    )
    session.add(
        Customer(
            id=f"customer-{broker_id}",
            broker_id=broker_id,
            broker_source_id=source_id,
            source_customer_id=f"customer-source-{broker_id}",
            name=f"Customer {broker_id}",
            created_at=NOW,
            updated_at=NOW,
        )
    )
    session.flush()


def add_carrier(
    session: Session,
    broker_id: str,
    carrier_id: str,
    name: str,
    identity_id: Optional[str] = None,
) -> Carrier:
    carrier = Carrier(
        id=carrier_id,
        broker_id=broker_id,
        broker_source_id=f"source-{broker_id}",
        carrier_identity_id=identity_id,
        source_carrier_id=f"source-{carrier_id}",
        name=name,
        mc_number=f"MC-{carrier_id}",
        dot_number=f"DOT-{carrier_id}",
        phone_number="555-0100",
        home_city="Dallas",
        home_state="TX",
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
    status: LoadStatus = LoadStatus.ACTIVE,
    equipment: EquipmentType = EquipmentType.DRY_VAN,
    carrier_id: Optional[str] = None,
    customer_rate: Optional[Decimal] = Decimal("2500.00"),
    carrier_rate: Optional[Decimal] = Decimal("2000.00"),
    pickup_date: Optional[date] = date(2026, 7, 20),
) -> Load:
    load = Load(
        id=load_id,
        broker_id=broker_id,
        broker_source_id=f"source-{broker_id}",
        source_load_id=load_id,
        display_number=f"LOAD-{load_id}",
        status=status,
        customer_id=f"customer-{broker_id}",
        carrier_id=carrier_id,
        equipment_type=equipment,
        weight_lbs=Decimal("42000.0"),
        distance_miles=Decimal("123.4"),
        customer_rate=customer_rate,
        carrier_rate=carrier_rate,
        first_seen_at=NOW,
        last_synced_at=NOW,
    )
    session.add(load)
    session.add_all(
        [
            LoadStop(
                broker_id=broker_id,
                load_id=load_id,
                sequence_number=2,
                stop_type=StopType.DROPOFF,
                city="Houston",
                state="TX",
                postal_code="77002",
                scheduled_date=pickup_date,
            ),
            LoadStop(
                broker_id=broker_id,
                load_id=load_id,
                sequence_number=1,
                stop_type=StopType.PICKUP,
                city="Dallas",
                state="TX",
                postal_code="75201",
                scheduled_date=pickup_date,
                location_name="Origin warehouse",
            ),
        ]
    )
    session.flush()
    return load


def seed_operations(session: Session) -> dict[str, object]:
    add_broker(session, "broker-a")
    add_broker(session, "broker-b")
    identity = CarrierIdentity(
        id="identity-a",
        broker_id="broker-a",
        normalized_mc_number="123",
        normalized_dot_number="456",
        created_at=NOW,
        updated_at=NOW,
    )
    session.add(identity)
    session.flush()
    canonical = add_carrier(session, "broker-a", "canonical-a", "Canonical Carrier")
    identity_carrier = add_carrier(
        session, "broker-a", "identity-carrier-a", "Identity Carrier", "identity-a"
    )
    second_identity_carrier = add_carrier(
        session, "broker-a", "identity-carrier-b", "Identity Carrier", "identity-a"
    )
    foreign_carrier = add_carrier(session, "broker-b", "foreign-carrier", "Foreign Carrier")
    target = add_load(session, "broker-a", "target", customer_rate=Decimal("2500.00"))
    canonical_load = add_load(
        session,
        "broker-a",
        "canonical-load",
        status=LoadStatus.COVERED,
        carrier_id=canonical.id,
    )
    add_load(session, "broker-a", "planned", status=LoadStatus.PLANNED)
    add_load(session, "broker-a", "reefer", equipment=EquipmentType.REEFER)
    add_load(session, "broker-b", "foreign-load")
    session.commit()
    return {
        "target": target,
        "canonical_load": canonical_load,
        "canonical": canonical,
        "identity_carrier": identity_carrier,
        "second_identity_carrier": second_identity_carrier,
        "foreign_carrier": foreign_carrier,
    }


def test_demo_brokers_are_gated(client: TestClient, db_session: Session, monkeypatch) -> None:
    add_broker(db_session, "broker-a")
    db_session.commit()
    monkeypatch.setattr(settings, "demo_mode", False)
    assert client.get("/demo/brokers").status_code == 404
    monkeypatch.setattr(settings, "demo_mode", True)
    response = client.get("/demo/brokers")
    assert response.status_code == 200
    assert response.json() == [{"id": "broker-a", "name": "Broker broker-a", "is_demo": True}]


def test_local_account_lifecycle_and_admin_broker_switching(
    client: TestClient, db_session: Session
) -> None:
    add_broker(db_session, "broker-a")
    add_broker(db_session, "broker-local")
    local = db_session.get(Broker, "broker-local")
    assert local is not None
    local.is_demo = False
    db_session.commit()

    for invalid_password in ("abcdef", "a!b", "admin!"):
        assert (
            client.post(
                "/demo/accounts",
                json={
                    "broker_id": "broker-local",
                    "name": "Invalid Password",
                    "email": f"{invalid_password.replace('!', '')}@example.test",
                    "password": invalid_password,
                },
            ).status_code
            == 422
        )

    created = client.post(
        "/demo/accounts",
        json={
            "broker_id": "broker-local",
            "name": "Local Operator",
            "email": "operator@example.test",
            "password": "tiger!7",
        },
    )
    assert created.status_code == 201
    assert (
        client.post(
            "/demo/accounts",
            json={
                "broker_id": "broker-local",
                "name": "Duplicate",
                "email": "OPERATOR@example.test",
                "password": "tiger!7",
            },
        ).status_code
        == 409
    )
    assert (
        client.post(
            "/demo/accounts",
            json={
                "broker_id": "broker-a",
                "name": "Locked",
                "email": "locked@example.test",
                "password": "tiger!7",
            },
        ).status_code
        == 403
    )

    login = client.post(
        "/demo/auth",
        json={
            "broker_id": "broker-local",
            "identifier": "OPERATOR@example.test",
            "password": "tiger!7",
        },
    )
    assert login.status_code == 200
    client.headers["Authorization"] = f"Bearer {login.json()['access_token']}"
    assert client.get("/me").json()["profile_locked"] is False
    assert [item["id"] for item in client.get("/demo/brokers").json()] == ["broker-local"]
    assert client.get("/brokers/broker-a/loads").status_code == 403
    updated = client.patch("/me", json={"name": "Renamed Operator"})
    assert updated.status_code == 200
    assert updated.json()["name"] == "Renamed Operator"

    admin = client.post(
        "/demo/auth",
        json={"broker_id": "broker-a", "identifier": "admin", "password": "admin"},
    )
    assert admin.status_code == 200
    client.headers["Authorization"] = f"Bearer {admin.json()['access_token']}"
    assert client.get("/me?broker_id=broker-local").status_code == 200
    assert client.patch("/me", json={"name": "Cannot Change Admin"}).status_code == 403
    assert {item["id"] for item in client.get("/demo/brokers").json()} == {
        "broker-a",
        "broker-local",
    }


def test_load_list_detail_and_filters_are_broker_scoped(
    client: TestClient, db_session: Session
) -> None:
    seeded = seed_operations(db_session)
    response = client.get("/brokers/broker-a/loads", params={"page_size": 2})
    body = response.json()
    assert response.status_code == 200
    assert body["total"] == 4
    assert [item["id"] for item in body["items"]] == ["canonical-load", "planned"]
    item = client.get("/brokers/broker-a/loads/target").json()
    assert item["customer"] == {"id": "customer-broker-a", "name": "Customer broker-a"}
    assert item["source"] == {"id": "source-broker-a", "name": "TMS broker-a"}
    assert item["weight_lbs"] == "42000.0"
    assert item["distance_miles"] == "123.4"
    assert item["customer_rate"] == "2500.00"
    assert item["margin"] == "500.00"
    assert item["next_schedule"] == "2026-07-20"
    detail = client.get(f"/brokers/broker-a/loads/{seeded['canonical_load'].id}")
    detail_body = detail.json()
    assert detail.status_code == 200
    assert [stop["sequence_number"] for stop in detail_body["stops"]] == [1, 2]
    assert detail_body["carrier"]["name"] == "Canonical Carrier"
    assert detail_body["stops"][0]["scheduled_date"] == "2026-07-20"
    assert client.get("/brokers/broker-a/loads", params={"status": "planned"}).json()["total"] == 1
    assert (
        client.get("/brokers/broker-a/loads", params={"equipment": "reefer"}).json()["total"] == 1
    )
    assert client.get("/brokers/broker-a/loads", params={"search": "planned"}).json()["total"] == 1
    assert (
        client.get("/brokers/broker-a/loads", params={"assignment_state": "unassigned"}).json()[
            "total"
        ]
        == 4
    )
    assert client.get("/brokers/broker-a/loads/foreign-load").status_code == 404
    assert client.get("/brokers/broker-b/loads/target").status_code == 403


@pytest.mark.parametrize("field", ["status", "equipment", "assignment_state"])
def test_load_list_rejects_empty_enum_filters_but_omitted_filters_work(
    client: TestClient, db_session: Session, field: str
) -> None:
    seed_operations(db_session)
    assert client.get("/brokers/broker-a/loads").status_code == 200
    assert client.get("/brokers/broker-a/loads", params={field: ""}).status_code == 422


def test_candidate_detail_supports_canonical_and_identity_ids_and_rejects_foreign(
    client: TestClient, db_session: Session
) -> None:
    seeded = seed_operations(db_session)
    add_load(
        db_session,
        "broker-a",
        "recommendation-history",
        status=LoadStatus.COMPLETED,
        carrier_id=seeded["canonical"].id,
    )
    db_session.commit()
    canonical = client.get("/brokers/broker-a/carrier-candidates/carrier:canonical-a")
    assert canonical.status_code == 200
    assert canonical.json()["carriers"][0]["source_id"] == "source-broker-a"
    with_evidence = client.get(
        "/brokers/broker-a/carrier-candidates/carrier:canonical-a",
        params={"load_id": "target"},
    )
    assert with_evidence.status_code == 200
    assert with_evidence.json()["evidence"][0] == {
        "origin": {"city": "Dallas", "state": "TX", "postal_code": "75201"},
        "destination": {"city": "Houston", "state": "TX", "postal_code": "77002"},
        "completed_month": "2026-07",
        "outcome": "completed",
    }
    identity = client.get("/brokers/broker-a/carrier-candidates/identity:identity-a")
    assert identity.status_code == 200
    assert identity.json()["carrier_identity_id"] == "identity-a"
    assert len(identity.json()["carriers"]) == 2
    assert (
        client.get(
            f"/brokers/broker-a/carrier-candidates/carrier:{seeded['foreign_carrier'].id}"
        ).status_code
        == 404
    )


def test_assignment_overlay_lifecycle_and_downstream_gating(
    client: TestClient, db_session: Session, monkeypatch
) -> None:
    seeded = seed_operations(db_session)
    target_id = seeded["target"].id
    monkeypatch.setattr(settings, "demo_mode", False)
    assert (
        client.post(
            f"/brokers/broker-a/loads/{target_id}/assignments",
            json={"carrier_id": seeded["canonical"].id},
        ).status_code
        == 503
    )
    monkeypatch.setattr(settings, "demo_mode", True)
    assert (
        client.post(
            f"/brokers/broker-a/loads/{seeded['canonical_load'].id}/assignments",
            json={"carrier_id": seeded["identity_carrier"].id},
        ).status_code
        == 409
    )
    assert (
        client.post(
            f"/brokers/broker-a/loads/{target_id}/assignments",
            json={"carrier_id": seeded["identity_carrier"].id},
        ).status_code
        == 200
    )
    assigned = client.post(
        f"/brokers/broker-a/loads/{target_id}/assignments",
        json={"carrier_id": seeded["canonical"].id, "expected_assignment_version": 1},
    )
    assert assigned.status_code == 200
    assert assigned.json()["assignment_version"] == 2
    stale = client.post(
        f"/brokers/broker-a/loads/{target_id}/assignments",
        json={"carrier_id": seeded["canonical"].id, "expected_assignment_version": 1},
    )
    assert stale.status_code == 409
    foreign = client.post(
        f"/brokers/broker-a/loads/{target_id}/assignments",
        json={"carrier_id": seeded["foreign_carrier"].id, "expected_assignment_version": 2},
    )
    assert foreign.status_code == 422
    assigned_load = client.get(f"/brokers/broker-a/loads/{target_id}").json()
    assert assigned_load["assignment"]["state"] == "assigned"
    assert assigned_load["assignment"]["assignment_version"] == 2
    assert assigned_load["assignment"]["carrier"]["name"] == "Canonical Carrier"
    assert (
        client.get("/brokers/broker-a/loads", params={"assignment_state": "assigned"}).json()[
            "total"
        ]
        == 1
    )
    assert client.get("/brokers/broker-a/loads/target/carrier-recommendations").status_code == 409
    assert client.get("/brokers/broker-a/loads/target/carrier-rate-estimate").status_code == 409
    assert (
        db_session.scalar(
            select(PlatformAssignment).where(PlatformAssignment.load_id == target_id)
        ).assignment_version
        == 2
    )
    assert (
        db_session.scalar(
            select(PlatformAssignmentEvent.assignment_version)
            .where(PlatformAssignmentEvent.load_id == target_id)
            .order_by(PlatformAssignmentEvent.assignment_version.desc())
        )
        == 2
    )
    latest_event = db_session.scalars(
        select(PlatformAssignmentEvent)
        .where(PlatformAssignmentEvent.load_id == target_id)
        .order_by(PlatformAssignmentEvent.assignment_version.desc())
    ).first()
    assert latest_event.demo_actor == "test-user"


def test_assignment_request_schema_does_not_expose_client_actor() -> None:
    schema = create_app().openapi()
    request_schema = schema["components"]["schemas"]["AssignmentRequest"]

    assert "demo_actor" not in request_schema.get("properties", {})


def test_assignment_rejects_noncanonical_candidate_resolution(
    client: TestClient, db_session: Session, monkeypatch
) -> None:
    seeded = seed_operations(db_session)
    monkeypatch.setattr(settings, "demo_mode", True)
    response = client.post(
        f"/brokers/broker-a/loads/{seeded['target'].id}/assignments",
        json={"candidate_id": "identity:missing"},
    )
    assert response.status_code == 422


def test_assignment_idempotency_replays_original_event(
    client: TestClient, db_session: Session, monkeypatch
) -> None:
    seeded = seed_operations(db_session)
    monkeypatch.setattr(settings, "demo_mode", True)
    first = client.post(
        f"/brokers/broker-a/loads/{seeded['target'].id}/assignments",
        json={"carrier_id": seeded["canonical"].id, "idempotency_key": "assign-001"},
    )
    replay = client.post(
        f"/brokers/broker-a/loads/{seeded['target'].id}/assignments",
        json={
            "carrier_id": seeded["canonical"].id,
            "idempotency_key": "assign-001",
            "expected_assignment_version": 99,
            "demo_actor": "spoofed-actor",
        },
    )

    assert first.status_code == 200
    assert replay.status_code == 200
    assert replay.json() == first.json()
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(PlatformAssignmentEvent)
            .where(PlatformAssignmentEvent.load_id == seeded["target"].id)
        )
        == 1
    )
