from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.models import Base, Broker, BrokerSource, Carrier, CarrierIdentity, TmsType
from scripts import bootstrap_demo


@pytest.fixture
def bootstrap_db(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'demo.sqlite'}")
    Base.metadata.create_all(engine)
    # Mirror app.database.SessionLocal: autoflush=False so the bootstrap path is
    # exercised exactly as it runs under docker compose (regression for the
    # "broker not found" failure when set_shared_pool_policy could not see
    # freshly-added, unflushed brokers).
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(bootstrap_demo, "SessionLocal", session_factory)
    yield engine
    engine.dispose()


def records(engine):
    with Session(engine) as session:
        brokers = session.scalars(select(Broker).order_by(Broker.id)).all()
        sources = session.scalars(select(BrokerSource).order_by(BrokerSource.id)).all()
        return brokers, sources


def test_bootstrap_creates_display_names_and_preserves_stable_ids(bootstrap_db, tmp_path) -> None:
    assert bootstrap_demo.bootstrap(tmp_path) == 0

    brokers, sources = records(bootstrap_db)
    assert [(broker.id, broker.name) for broker in brokers] == [
        ("broker-a", "Ithaca Freight Partners"),
        ("broker-b", "Aegean Route Logistics"),
        ("broker-c", "Olive Harbor Transport"),
        ("broker-local", "Local Sandbox Brokerage"),
    ]
    assert [
        (source.id, source.broker_id, source.source_name, source.tms_type) for source in sources
    ] == [
        ("source-a", "broker-a", "FreightFlow", TmsType.FREIGHTFLOW),
        ("source-b", "broker-b", "HaulDesk", TmsType.HAULDESK),
        ("source-c", "broker-c", "BrokerOS", TmsType.BROKEROS),
    ]


def test_bootstrap_is_idempotent(bootstrap_db, tmp_path) -> None:
    assert bootstrap_demo.bootstrap(tmp_path) == 0
    before = [(broker.id, broker.name, broker.created_at) for broker in records(bootstrap_db)[0]]
    source_before = [
        (source.id, source.broker_id, source.source_name, source.created_at)
        for source in records(bootstrap_db)[1]
    ]

    assert bootstrap_demo.bootstrap(tmp_path) == 0

    assert [
        (broker.id, broker.name, broker.created_at) for broker in records(bootstrap_db)[0]
    ] == before
    assert [
        (source.id, source.broker_id, source.source_name, source.created_at)
        for source in records(bootstrap_db)[1]
    ] == source_before


def test_bootstrap_approves_names_only_for_configured_demo_brokers(bootstrap_db, tmp_path) -> None:
    assert bootstrap_demo.bootstrap(tmp_path) == 0
    now = datetime.now(timezone.utc)
    with Session(bootstrap_db) as session:
        session.add(Broker(id="outside-demo", name="Outside Demo", is_demo=True, created_at=now))
        session.add(
            BrokerSource(
                id="outside-source",
                broker_id="outside-demo",
                tms_type=TmsType.FREIGHTFLOW,
                source_name="Outside Source",
                created_at=now,
            )
        )
        configured_identity = CarrierIdentity(
            id="configured-identity",
            broker_id="broker-a",
            normalized_mc_number="100",
            created_at=now,
            updated_at=now,
        )
        outside_identity = CarrierIdentity(
            id="outside-identity",
            broker_id="outside-demo",
            normalized_mc_number="200",
            created_at=now,
            updated_at=now,
        )
        session.add_all([configured_identity, outside_identity])
        session.add_all(
            [
                Carrier(
                    broker_id="broker-a",
                    broker_source_id="source-a",
                    carrier_identity_id=configured_identity.id,
                    source_carrier_id="configured-carrier",
                    name="Configured Public Name",
                    created_at=now,
                    updated_at=now,
                ),
                Carrier(
                    broker_id="outside-demo",
                    broker_source_id="outside-source",
                    carrier_identity_id=outside_identity.id,
                    source_carrier_id="outside-carrier",
                    name="Outside Private Name",
                    created_at=now,
                    updated_at=now,
                ),
            ]
        )
        session.commit()

    assert bootstrap_demo.bootstrap(tmp_path) == 0

    with Session(bootstrap_db) as session:
        assert (
            session.get(CarrierIdentity, "configured-identity").shared_display_name
            == "Configured Public Name"
        )
        assert session.get(CarrierIdentity, "outside-identity").shared_display_name is None


def test_bootstrap_reconciles_legacy_placeholder_names(bootstrap_db, tmp_path) -> None:
    now = datetime.now(timezone.utc)
    with Session(bootstrap_db) as session:
        for _, broker_id, _, source_id, _, tms_type in bootstrap_demo.SOURCE_CONFIG:
            session.add(Broker(id=broker_id, name=broker_id, created_at=now))
            session.add(
                BrokerSource(
                    id=source_id,
                    broker_id=broker_id,
                    tms_type=tms_type,
                    source_name=source_id,
                    created_at=now,
                )
            )
        session.commit()

    assert bootstrap_demo.bootstrap(tmp_path) == 0
    brokers, sources = records(bootstrap_db)
    assert [broker.name for broker in brokers] == [
        "Ithaca Freight Partners",
        "Aegean Route Logistics",
        "Olive Harbor Transport",
        "Local Sandbox Brokerage",
    ]
    assert [source.source_name for source in sources] == ["FreightFlow", "HaulDesk", "BrokerOS"]


def test_bootstrap_preserves_custom_names(bootstrap_db, tmp_path) -> None:
    now = datetime.now(timezone.utc)
    with Session(bootstrap_db) as session:
        for _, broker_id, _, source_id, _, tms_type in bootstrap_demo.SOURCE_CONFIG:
            session.add(Broker(id=broker_id, name=f"Custom {broker_id}", created_at=now))
            session.add(
                BrokerSource(
                    id=source_id,
                    broker_id=broker_id,
                    tms_type=tms_type,
                    source_name=f"Custom {source_id}",
                    created_at=now,
                )
            )
        session.commit()

    assert bootstrap_demo.bootstrap(tmp_path) == 0
    brokers, sources = records(bootstrap_db)
    assert [broker.name for broker in brokers] == [
        "Custom broker-a",
        "Custom broker-b",
        "Custom broker-c",
        "Local Sandbox Brokerage",
    ]
    assert [source.source_name for source in sources] == [
        "Custom source-a",
        "Custom source-b",
        "Custom source-c",
    ]


def test_bootstrap_rejects_source_owned_by_another_broker(bootstrap_db, tmp_path) -> None:
    with Session(bootstrap_db) as session:
        session.add(Broker(id="other", name="Other Broker", created_at=datetime.now(timezone.utc)))
        session.add(
            BrokerSource(
                id="source-a",
                broker_id="other",
                tms_type=TmsType.FREIGHTFLOW,
                source_name="FreightFlow",
                created_at=datetime.now(timezone.utc),
            )
        )
        session.commit()

    with pytest.raises(ValueError, match="source-a.*belongs to broker.*other.*broker-a"):
        bootstrap_demo.bootstrap(tmp_path)


def test_bootstrap_rejects_source_tms_mismatch(bootstrap_db, tmp_path) -> None:
    with Session(bootstrap_db) as session:
        session.add(
            Broker(
                id="broker-a",
                name="Ithaca Freight Partners",
                created_at=datetime.now(timezone.utc),
            )
        )
        session.add(
            BrokerSource(
                id="source-a",
                broker_id="broker-a",
                tms_type=TmsType.HAULDESK,
                source_name="HaulDesk",
                created_at=datetime.now(timezone.utc),
            )
        )
        session.commit()

    with pytest.raises(ValueError, match="source-a.*hauldesk.*freightflow"):
        bootstrap_demo.bootstrap(tmp_path)


def test_bootstrap_rejects_broker_name_collision_before_commit(bootstrap_db, tmp_path) -> None:
    with Session(bootstrap_db) as session:
        session.add(
            Broker(
                id="other",
                name="Ithaca Freight Partners",
                created_at=datetime.now(timezone.utc),
            )
        )
        session.commit()

    with pytest.raises(ValueError, match="Demo broker name collision.*Ithaca Freight Partners"):
        bootstrap_demo.bootstrap(tmp_path)

    brokers, sources = records(bootstrap_db)
    assert [(broker.id, broker.name) for broker in brokers] == [
        ("other", "Ithaca Freight Partners")
    ]
    assert sources == []
