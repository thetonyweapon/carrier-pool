from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Optional
from uuid import NAMESPACE_URL, uuid5

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, event, insert, inspect, select, text
from sqlalchemy.exc import IntegrityError, StatementError
from sqlalchemy.orm import Session

from alembic import command
from app.config import settings
from app.models import (
    Base,
    Broker,
    BrokerSource,
    Carrier,
    CarrierIdentity,
    Customer,
    EquipmentType,
    IngestionFile,
    IngestionStatus,
    Load,
    LoadRateObservation,
    LoadStatus,
    LoadStop,
    LoadVersion,
    RateLineItem,
    RateSide,
    SharedPoolPolicy,
    SharedPoolPolicyEvent,
    SharedPoolQueryAudit,
    StopType,
    TmsType,
)

NOW = datetime(2026, 7, 1, tzinfo=timezone.utc)


@pytest.fixture
def db_session():
    engine = create_engine("sqlite+pysqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, connection_record) -> None:
        del connection_record
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def add_broker_and_source(session: Session, broker_id: str, source_id: str) -> BrokerSource:
    session.add(Broker(id=broker_id, name=f"Broker {broker_id}", created_at=NOW))
    source = BrokerSource(
        id=source_id,
        broker_id=broker_id,
        tms_type=TmsType.FREIGHTFLOW,
        source_name=f"FreightFlow {broker_id}",
        created_at=NOW,
    )
    session.add(source)
    session.flush()
    return source


def add_customer(session: Session, broker_id: str, source_id: str, customer_id: str) -> Customer:
    customer = Customer(
        id=customer_id,
        broker_id=broker_id,
        broker_source_id=source_id,
        source_customer_id="customer-1",
        name="Acme Shipper",
        created_at=NOW,
        updated_at=NOW,
    )
    session.add(customer)
    session.flush()
    return customer


def add_carrier(session: Session, broker_id: str, source_id: str, carrier_id: str) -> Carrier:
    carrier = Carrier(
        id=carrier_id,
        broker_id=broker_id,
        broker_source_id=source_id,
        source_carrier_id="carrier-1",
        name="Lone Star Transport",
        created_at=NOW,
        updated_at=NOW,
    )
    session.add(carrier)
    session.flush()
    return carrier


def make_load(
    broker_id: str,
    source_id: str,
    customer_id: str,
    carrier_id: Optional[str] = None,
    load_id: str = "load-1",
    source_load_id: str = "source-load-1",
) -> Load:
    return Load(
        id=load_id,
        broker_id=broker_id,
        broker_source_id=source_id,
        source_load_id=source_load_id,
        display_number=source_load_id,
        status=LoadStatus.ACTIVE,
        customer_id=customer_id,
        carrier_id=carrier_id,
        equipment_type=EquipmentType.DRY_VAN,
        first_seen_at=NOW,
        last_synced_at=NOW,
    )


def test_same_external_load_id_is_valid_for_different_brokers(db_session: Session) -> None:
    add_broker_and_source(db_session, "broker-a", "source-a")
    add_broker_and_source(db_session, "broker-b", "source-b")
    add_customer(db_session, "broker-a", "source-a", "customer-a")
    add_customer(db_session, "broker-b", "source-b", "customer-b")

    db_session.add(make_load("broker-a", "source-a", "customer-a", load_id="load-a"))
    db_session.add(make_load("broker-b", "source-b", "customer-b", load_id="load-b"))
    db_session.commit()

    loads = db_session.scalars(select(Load)).all()
    assert {load.source_load_id for load in loads} == {"source-load-1"}
    assert len(loads) == 2


def test_load_rejects_cross_tenant_customer(db_session: Session) -> None:
    add_broker_and_source(db_session, "broker-a", "source-a")
    add_broker_and_source(db_session, "broker-b", "source-b")
    add_customer(db_session, "broker-a", "source-a", "customer-a")
    add_customer(db_session, "broker-b", "source-b", "customer-b")

    db_session.add(make_load("broker-a", "source-a", "customer-b"))

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_load_rejects_cross_tenant_carrier(db_session: Session) -> None:
    add_broker_and_source(db_session, "broker-a", "source-a")
    add_broker_and_source(db_session, "broker-b", "source-b")
    add_customer(db_session, "broker-a", "source-a", "customer-a")
    add_carrier(db_session, "broker-b", "source-b", "carrier-b")

    db_session.add(make_load("broker-a", "source-a", "customer-a", carrier_id="carrier-b"))

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_carrier_identity_is_broker_scoped_and_requires_evidence(db_session: Session) -> None:
    add_broker_and_source(db_session, "broker-a", "source-a")
    add_broker_and_source(db_session, "broker-b", "source-b")
    db_session.add(
        CarrierIdentity(
            id="identity-a",
            broker_id="broker-a",
            normalized_mc_number="884201",
            created_at=NOW,
            updated_at=NOW,
        )
    )
    db_session.flush()
    db_session.add(
        CarrierIdentity(
            id="identity-b",
            broker_id="broker-b",
            normalized_mc_number="884201",
            created_at=NOW,
            updated_at=NOW,
        )
    )
    db_session.flush()
    db_session.add(
        CarrierIdentity(id="missing-evidence", broker_id="broker-a", created_at=NOW, updated_at=NOW)
    )
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_load_rejects_customer_from_another_source_for_the_same_broker(
    db_session: Session,
) -> None:
    add_broker_and_source(db_session, "broker-a", "source-a")
    db_session.add(
        BrokerSource(
            id="source-b",
            broker_id="broker-a",
            tms_type=TmsType.HAULDESK,
            source_name="HaulDesk broker-a",
            created_at=NOW,
        )
    )
    db_session.flush()
    add_customer(db_session, "broker-a", "source-a", "customer-a")
    add_customer(db_session, "broker-a", "source-b", "customer-b")

    db_session.add(make_load("broker-a", "source-a", "customer-b"))

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_load_stops_preserve_order_and_reject_duplicate_sequence(db_session: Session) -> None:
    add_broker_and_source(db_session, "broker-a", "source-a")
    add_customer(db_session, "broker-a", "source-a", "customer-a")
    db_session.add(make_load("broker-a", "source-a", "customer-a"))
    db_session.flush()
    db_session.add_all(
        [
            LoadStop(
                id="stop-1",
                broker_id="broker-a",
                load_id="load-1",
                sequence_number=1,
                stop_type=StopType.PICKUP,
                city="Dallas",
                state="TX",
                postal_code="75201",
            ),
            LoadStop(
                id="stop-2",
                broker_id="broker-a",
                load_id="load-1",
                sequence_number=2,
                stop_type=StopType.DROPOFF,
                city="Houston",
                state="TX",
                postal_code="77002",
            ),
        ]
    )
    db_session.commit()

    stops = db_session.scalars(select(LoadStop).order_by(LoadStop.sequence_number)).all()
    assert [stop.sequence_number for stop in stops] == [1, 2]

    db_session.add(
        LoadStop(
            id="stop-duplicate",
            broker_id="broker-a",
            load_id="load-1",
            sequence_number=2,
            stop_type=StopType.DROPOFF,
            city="Houston",
            state="TX",
            postal_code="77002",
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_rate_line_items_preserve_exact_negative_adjustments(db_session: Session) -> None:
    add_broker_and_source(db_session, "broker-a", "source-a")
    add_customer(db_session, "broker-a", "source-a", "customer-a")
    db_session.add(make_load("broker-a", "source-a", "customer-a"))
    db_session.flush()
    adjustment = RateLineItem(
        id="rate-1",
        broker_id="broker-a",
        broker_source_id="source-a",
        load_id="load-1",
        source_rate_id="rate-source-1",
        side=RateSide.PAY,
        code="ADJUSTMENT",
        amount=Decimal("-25.50"),
        ingested_at=NOW,
    )
    db_session.add(adjustment)
    db_session.commit()

    assert db_session.get(RateLineItem, "rate-1").amount == Decimal("-25.50")

    db_session.add(
        RateLineItem(
            id="rate-duplicate",
            broker_id="broker-a",
            broker_source_id="source-a",
            load_id="load-1",
            source_rate_id="rate-source-1",
            side=RateSide.PAY,
            code="ADJUSTMENT",
            amount=Decimal("-1.00"),
            ingested_at=NOW,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_rate_line_item_rejects_a_load_from_another_source_for_the_same_broker(
    db_session: Session,
) -> None:
    add_broker_and_source(db_session, "broker-a", "source-a")
    db_session.add(
        BrokerSource(
            id="source-b",
            broker_id="broker-a",
            tms_type=TmsType.HAULDESK,
            source_name="HaulDesk broker-a",
            created_at=NOW,
        )
    )
    db_session.flush()
    add_customer(db_session, "broker-a", "source-a", "customer-a")
    db_session.add(make_load("broker-a", "source-a", "customer-a"))
    db_session.commit()

    db_session.add(
        RateLineItem(
            id="rate-1",
            broker_id="broker-a",
            broker_source_id="source-b",
            load_id="load-1",
            source_rate_id="rate-source-1",
            side=RateSide.PAY,
            code="LINEHAUL",
            amount=Decimal("100.00"),
            ingested_at=NOW,
        )
    )

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_currency_rejects_fractions_of_a_cent_and_float_values() -> None:
    with pytest.raises(ValueError, match="fractions of a cent"):
        RateLineItem(
            broker_id="broker-a",
            broker_source_id="source-a",
            load_id="load-1",
            source_rate_id="rate-source-1",
            side=RateSide.PAY,
            code="LINEHAUL",
            amount=Decimal("1.001"),
            ingested_at=NOW,
        )


def test_currency_type_rejects_fractional_cents_for_core_writes(db_session: Session) -> None:
    with pytest.raises(StatementError, match="fractions of a cent"):
        db_session.execute(
            insert(RateLineItem).values(
                id="rate-1",
                broker_id="broker-a",
                broker_source_id="source-a",
                load_id="load-1",
                source_rate_id="rate-source-1",
                side=RateSide.PAY,
                code="LINEHAUL",
                amount=Decimal("1.001"),
                ingested_at=NOW,
            )
        )

    with pytest.raises(TypeError, match="Decimal"):
        RateLineItem(
            broker_id="broker-a",
            broker_source_id="source-a",
            load_id="load-1",
            source_rate_id="rate-source-1",
            side=RateSide.PAY,
            code="LINEHAUL",
            amount=1.00,
            ingested_at=NOW,
        )


def test_load_versions_and_ingestion_files_are_auditable_and_idempotent(
    db_session: Session,
) -> None:
    add_broker_and_source(db_session, "broker-a", "source-a")
    add_customer(db_session, "broker-a", "source-a", "customer-a")
    db_session.add(make_load("broker-a", "source-a", "customer-a"))
    db_session.flush()
    ingestion_file = IngestionFile(
        id="file-1",
        broker_id="broker-a",
        broker_source_id="source-a",
        filename="2026-07-01T00-00_sync.json",
        checksum="a" * 64,
        synced_at=NOW,
        status=IngestionStatus.SUCCEEDED,
        processed_at=NOW,
    )
    db_session.add(ingestion_file)
    db_session.flush()
    db_session.add(
        LoadVersion(
            id="version-1",
            broker_id="broker-a",
            broker_source_id="source-a",
            load_id="load-1",
            ingestion_file_id=ingestion_file.id,
            version_number=1,
            observed_at=NOW,
            raw_payload={"shipmentId": 42},
            normalized_snapshot={"status": "active"},
        )
    )
    db_session.commit()

    assert db_session.get(LoadVersion, "version-1").raw_payload == {"shipmentId": 42}

    db_session.add(
        IngestionFile(
            id="file-duplicate",
            broker_id="broker-a",
            broker_source_id="source-a",
            filename="2026-07-01T00-00_sync.json",
            checksum="b" * 64,
            synced_at=NOW,
            status=IngestionStatus.PROCESSING,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_initial_migration_upgrades_and_downgrades(tmp_path: Path, monkeypatch) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'schema.db'}"
    monkeypatch.setattr(settings, "database_url", database_url)
    alembic_config = Config(str(Path(__file__).parents[1] / "alembic.ini"))

    command.upgrade(alembic_config, "head")
    engine = create_engine(database_url)

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, connection_record) -> None:
        del connection_record
        connection.execute("PRAGMA foreign_keys=ON")

    assert inspect(engine).has_table("loads")
    assert inspect(engine).has_table("load_rate_observations")
    assert inspect(engine).has_table("shared_pool_policies")
    assert inspect(engine).has_table("shared_pool_policy_events")
    assert inspect(engine).has_table("shared_pool_query_audits")
    command.check(alembic_config)

    with Session(engine) as session:
        add_broker_and_source(session, "broker-a", "source-a")
        session.add(
            BrokerSource(
                id="source-b",
                broker_id="broker-a",
                tms_type=TmsType.HAULDESK,
                source_name="HaulDesk broker-a",
                created_at=NOW,
            )
        )
        session.flush()
        add_customer(session, "broker-a", "source-a", "customer-a")
        add_customer(session, "broker-a", "source-b", "customer-b")
        add_carrier(session, "broker-a", "source-b", "carrier-b")
        session.commit()

        session.add(make_load("broker-a", "source-a", "customer-b"))
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()

        session.add(make_load("broker-a", "source-a", "customer-a", carrier_id="carrier-b"))
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()

        session.add(make_load("broker-a", "source-a", "customer-a"))
        session.flush()
        session.add(
            RateLineItem(
                id="rate-invalid",
                broker_id="broker-a",
                broker_source_id="source-b",
                load_id="load-1",
                source_rate_id="rate-source-invalid",
                side=RateSide.PAY,
                code="LINEHAUL",
                amount=Decimal("100.00"),
                ingested_at=NOW,
            )
        )
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()

        session.add(make_load("broker-a", "source-a", "customer-a"))
        session.flush()
        session.add(
            IngestionFile(
                id="file-1",
                broker_id="broker-a",
                broker_source_id="source-a",
                filename="observation.json",
                checksum="c" * 64,
                synced_at=NOW,
                status=IngestionStatus.SUCCEEDED,
                processed_at=NOW,
            )
        )
        session.flush()
        observation = LoadRateObservation(
            id="observation-1",
            broker_id="broker-a",
            broker_source_id="source-a",
            load_id="load-1",
            ingestion_file_id="file-1",
            side=RateSide.PAY,
            amount=None,
            observation_number=1,
            observed_at=NOW,
        )
        session.add(observation)
        session.commit()
        observation.amount = Decimal("100.00")
        with pytest.raises(IntegrityError, match="append-only"):
            session.commit()
        session.rollback()
        session.delete(session.get(LoadRateObservation, "observation-1"))
        with pytest.raises(IntegrityError, match="append-only"):
            session.commit()
        session.rollback()

        rate = RateLineItem(
            id="rate-1",
            broker_id="broker-a",
            broker_source_id="source-a",
            load_id="load-1",
            source_rate_id="rate-source-1",
            side=RateSide.PAY,
            code="LINEHAUL",
            amount=Decimal("100.00"),
            ingested_at=NOW,
        )
        session.add(rate)
        session.commit()

        rate.amount = Decimal("101.00")
        with pytest.raises(IntegrityError, match="append-only"):
            session.commit()
        session.rollback()

        session.delete(session.get(Load, "load-1"))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

        session.delete(session.get(BrokerSource, "source-a"))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

        session.delete(session.get(RateLineItem, "rate-1"))
        with pytest.raises(IntegrityError, match="append-only"):
            session.commit()
        session.rollback()

    engine.dispose()

    command.downgrade(alembic_config, "base")
    assert not inspect(create_engine(database_url)).has_table("loads")


def test_shared_pool_audit_migration_enforces_append_only(tmp_path: Path, monkeypatch) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'shared-pool.db'}"
    monkeypatch.setattr(settings, "database_url", database_url)
    alembic_config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    command.upgrade(alembic_config, "head")
    engine = create_engine(database_url)

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, connection_record) -> None:
        del connection_record
        connection.execute("PRAGMA foreign_keys=ON")

    with Session(engine) as session:
        add_broker_and_source(session, "broker-a", "source-a")
        add_customer(session, "broker-a", "source-a", "customer-a")
        session.add(make_load("broker-a", "source-a", "customer-a", load_id="target"))
        session.flush()
        session.add(
            SharedPoolPolicy(
                broker_id="broker-a",
                enabled=True,
                policy_revision=1,
                attribute_profile="public-carrier-name-v1",
                changed_by="test-admin",
                updated_at=NOW,
            )
        )
        policy_event = SharedPoolPolicyEvent(
            broker_id="broker-a",
            enabled=True,
            policy_revision=1,
            policy_version="shared-carrier-pool-v1",
            attribute_profile="public-carrier-name-v1",
            changed_by="test-admin",
            created_at=NOW,
        )
        query_audit = SharedPoolQueryAudit(
            broker_id="broker-a",
            load_id="target",
            query_type="recommendations",
            policy_version="shared-carrier-pool-v1",
            policy_revision=1,
            scoring_version="shared-carrier-recommendations-v1",
            normalization_version="tx-metro-v1",
            participant_scope_digest="a" * 64,
            participant_count=3,
            result_count=1,
            created_at=NOW,
        )
        session.add_all([policy_event, query_audit])
        session.commit()

        policy_event.policy_revision = 2
        with pytest.raises(IntegrityError, match="append-only"):
            session.commit()
        session.rollback()
        session.delete(session.get(SharedPoolPolicyEvent, policy_event.id))
        with pytest.raises(IntegrityError, match="append-only"):
            session.commit()
        session.rollback()

        query_audit.result_count = 2
        with pytest.raises(IntegrityError, match="append-only"):
            session.commit()
        session.rollback()
        session.delete(session.get(SharedPoolQueryAudit, query_audit.id))
        with pytest.raises(IntegrityError, match="append-only"):
            session.commit()
        session.rollback()

    engine.dispose()
    command.downgrade(alembic_config, "base")


def test_carrier_identity_migration_backfills_deterministically(
    tmp_path: Path, monkeypatch
) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'carrier-identities.db'}"
    monkeypatch.setattr(settings, "database_url", database_url)
    alembic_config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    command.upgrade(alembic_config, "3cd64c705778")
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO brokers (id, name, created_at) VALUES ('broker-a', 'Broker A', :now)"
            ),
            {"now": NOW},
        )
        connection.execute(
            text(
                """
                INSERT INTO broker_sources (id, broker_id, tms_type, source_name, created_at)
                VALUES ('source-a', 'broker-a', 'freightflow', 'FreightFlow A', :now)
                """
            ),
            {"now": NOW},
        )
        connection.execute(
            text(
                """
                INSERT INTO carriers (
                    id, broker_id, broker_source_id, source_carrier_id, name,
                    mc_number, dot_number, created_at, updated_at
                ) VALUES
                    ('carrier-a', 'broker-a', 'source-a', 'ff-1', 'Carrier A',
                     'MC-884201', 'DOT 2551377', :now, :now),
                    ('carrier-b', 'broker-a', 'source-a', 'ff-2', 'Carrier A',
                     '884201', '2551377', :now, :now)
                """
            ),
            {"now": NOW},
        )
    engine.dispose()

    command.upgrade(alembic_config, "head")
    upgraded_engine = create_engine(database_url)
    with upgraded_engine.connect() as connection:
        links = (
            connection.execute(
                text(
                    """
                SELECT carrier_identity_id FROM carriers ORDER BY id
                """
                )
            )
            .scalars()
            .all()
        )
        identity = (
            connection.execute(
                text(
                    """
                SELECT id, normalized_mc_number, normalized_dot_number
                FROM carrier_identities
                """
                )
            )
            .mappings()
            .one()
        )
    assert links == [identity["id"], identity["id"]]
    assert identity["id"] == str(
        uuid5(NAMESPACE_URL, "carrier-pool:carrier-identity:broker-a:884201:2551377")
    )
    assert (identity["normalized_mc_number"], identity["normalized_dot_number"]) == (
        "884201",
        "2551377",
    )
    upgraded_engine.dispose()

    command.downgrade(alembic_config, "3cd64c705778")
    command.upgrade(alembic_config, "head")
    reupgraded_engine = create_engine(database_url)
    with reupgraded_engine.connect() as connection:
        reupgraded_links = (
            connection.execute(text("SELECT carrier_identity_id FROM carriers ORDER BY id"))
            .scalars()
            .all()
        )
    assert reupgraded_links == links
    reupgraded_engine.dispose()


def test_provenance_migration_backfills_legacy_load_versions(tmp_path: Path, monkeypatch) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'legacy.db'}"
    monkeypatch.setattr(settings, "database_url", database_url)
    alembic_config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    legacy_file_id = str(uuid5(NAMESPACE_URL, "carrier-pool:legacy:version-a:1"))
    command.upgrade(alembic_config, "3cd64c705778")
    engine = create_engine(database_url)

    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO brokers (id, name, created_at) VALUES ('broker-a', 'Broker A', :now)"
            ),
            {"now": NOW},
        )
        connection.execute(
            text(
                """
                INSERT INTO broker_sources (id, broker_id, tms_type, source_name, created_at)
                VALUES ('source-a', 'broker-a', 'freightflow', 'FreightFlow A', :now)
                """
            ),
            {"now": NOW},
        )
        connection.execute(
            text(
                """
                INSERT INTO customers (
                    id, broker_id, broker_source_id, source_customer_id,
                    name, created_at, updated_at
                ) VALUES (
                    'customer-a', 'broker-a', 'source-a', 'customer-a',
                    'Customer A', :now, :now
                )
                """
            ),
            {"now": NOW},
        )
        connection.execute(
            text(
                """
                INSERT INTO loads (
                    id, broker_id, broker_source_id, source_load_id, display_number, status,
                    customer_id, equipment_type, first_seen_at, last_synced_at
                ) VALUES (
                    'load-a', 'broker-a', 'source-a', 'source-load-a', 'source-load-a', 'active',
                    'customer-a', 'dry_van', :now, :now
                )
                """
            ),
            {"now": NOW},
        )
        connection.execute(
            text(
                """
                INSERT INTO ingestion_files (
                    id, broker_id, broker_source_id, filename, checksum,
                    synced_at, status, processed_at
                ) VALUES (
                    'existing-file', 'broker-a', 'source-a',
                    '__carrier_pool_legacy_load_version__version-a.json',
                    :checksum, :now, 'succeeded', :now
                )
                """
            ),
            {"checksum": "a" * 64, "now": NOW},
        )
        connection.execute(
            text(
                """
                INSERT INTO ingestion_files (
                    id, broker_id, broker_source_id, filename, checksum,
                    synced_at, status, processed_at
                ) VALUES (
                    :id, 'broker-a', 'source-a', 'unrelated.json',
                    :checksum, :now, 'succeeded', :now
                )
                """
            ),
            {"id": legacy_file_id, "checksum": "b" * 64, "now": NOW},
        )
        connection.execute(
            text(
                """
                INSERT INTO load_versions (
                    id, broker_id, load_id, version_number,
                    observed_at, raw_payload, normalized_snapshot
                ) VALUES ('version-a', 'broker-a', 'load-a', 1, :now, '{}', '{}')
                """
            ),
            {"now": NOW},
        )
    engine.dispose()

    command.upgrade(alembic_config, "head")
    upgraded_engine = create_engine(database_url)
    with upgraded_engine.connect() as connection:
        version = (
            connection.execute(
                text(
                    """
                    SELECT broker_source_id, ingestion_file_id
                    FROM load_versions
                    WHERE id = 'version-a'
                    """
                )
            )
            .mappings()
            .one()
        )
        ingestion_file = (
            connection.execute(
                text("SELECT filename, status, error_message FROM ingestion_files WHERE id = :id"),
                {"id": version["ingestion_file_id"]},
            )
            .mappings()
            .one()
        )

    assert version["broker_source_id"] == "source-a"
    assert ingestion_file == {
        "filename": "__carrier_pool_legacy_load_version__version-a-2.json",
        "status": "succeeded",
        "error_message": "carrier-pool migration 8b3e1e01e7a2 legacy provenance",
    }
    upgraded_engine.dispose()

    command.downgrade(alembic_config, "3cd64c705778")
    downgraded_engine = create_engine(database_url)
    with downgraded_engine.connect() as connection:
        filenames = (
            connection.execute(text("SELECT filename FROM ingestion_files ORDER BY filename"))
            .scalars()
            .all()
        )

    assert filenames == [
        "__carrier_pool_legacy_load_version__version-a.json",
        "unrelated.json",
    ]
    downgraded_engine.dispose()

    command.upgrade(alembic_config, "head")
    reupgraded_engine = create_engine(database_url)
    with reupgraded_engine.connect() as connection:
        reupgraded_version = connection.execute(
            text("SELECT ingestion_file_id FROM load_versions WHERE id = 'version-a'")
        ).scalar_one()

    assert reupgraded_version == version["ingestion_file_id"]
