import os
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from urllib.parse import quote
from uuid import uuid4

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from alembic import command
from app.config import settings
from app.models import (
    Broker,
    BrokerSource,
    Customer,
    IngestionFile,
    IngestionStatus,
    Load,
    LoadRateObservation,
    LoadStatus,
    RateLineItem,
    RateSide,
    SharedPoolPolicyEvent,
    SharedPoolQueryAudit,
    TmsType,
)


@pytest.fixture
def migrated_postgres():
    database_url = os.getenv("HAULDESK_POSTGRES_TEST_URL")
    if not database_url:
        pytest.skip("set HAULDESK_POSTGRES_TEST_URL to run PostgreSQL hardening coverage")

    schema = f"hardening_test_{uuid4().hex}"
    admin_engine = create_engine(database_url)
    previous_database_url = settings.database_url
    test_engine = None
    try:
        with admin_engine.begin() as connection:
            connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
        schema_url = database_url + "?options=" + quote(f"-c search_path={schema}")
        settings.database_url = schema_url
        command.upgrade(Config(str(Path(__file__).parents[1] / "alembic.ini")), "head")
        settings.database_url = previous_database_url
        test_engine = create_engine(
            database_url,
            connect_args={"options": f"-c search_path={schema}"},
        )
        yield test_engine, schema_url
    finally:
        settings.database_url = previous_database_url
        if test_engine is not None:
            test_engine.dispose()
        with admin_engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        admin_engine.dispose()


def seed_append_only_rows(session: Session) -> dict[str, str]:
    now = datetime.now(timezone.utc)
    session.add(Broker(id="pg-broker", name="PostgreSQL Broker", created_at=now))
    session.add(
        BrokerSource(
            id="pg-source",
            broker_id="pg-broker",
            tms_type=TmsType.FREIGHTFLOW,
            source_name="PostgreSQL Source",
            created_at=now,
        )
    )
    session.add(
        Customer(
            id="pg-customer",
            broker_id="pg-broker",
            broker_source_id="pg-source",
            source_customer_id="PG-CUSTOMER",
            name="PostgreSQL Customer",
            created_at=now,
            updated_at=now,
        )
    )
    session.add(
        Load(
            id="pg-load",
            broker_id="pg-broker",
            broker_source_id="pg-source",
            source_load_id="PG-LOAD",
            display_number="PG-LOAD",
            status=LoadStatus.COMPLETED,
            customer_id="pg-customer",
            equipment_type="dry_van",
            weight_lbs=Decimal("1000.0"),
            distance_miles=Decimal("100.0"),
            customer_rate=Decimal("1200.00"),
            carrier_rate=Decimal("900.00"),
            source_created_at=now,
            source_updated_at=now,
            first_seen_at=now,
            last_synced_at=now,
        )
    )
    session.add(
        IngestionFile(
            id="pg-file",
            broker_id="pg-broker",
            broker_source_id="pg-source",
            filename="pg.json",
            checksum="a" * 64,
            synced_at=now,
            status=IngestionStatus.SUCCEEDED,
            processed_at=now,
        )
    )
    session.flush()
    rows = {
        "rate_line_item": RateLineItem(
            id="pg-rate",
            broker_id="pg-broker",
            broker_source_id="pg-source",
            load_id="pg-load",
            source_rate_id="PG-RATE",
            side=RateSide.BILL,
            code="LINEHAUL",
            amount=Decimal("1200.00"),
            source_created_at=now,
            ingested_at=now,
        ),
        "rate_observation": LoadRateObservation(
            id="pg-observation",
            broker_id="pg-broker",
            broker_source_id="pg-source",
            load_id="pg-load",
            ingestion_file_id="pg-file",
            side=RateSide.PAY,
            amount=Decimal("900.00"),
            observation_number=1,
            observed_at=now,
            source_updated_at=now,
        ),
        "policy_event": SharedPoolPolicyEvent(
            id="pg-policy-event",
            broker_id="pg-broker",
            enabled=True,
            policy_revision=1,
            policy_version="test",
            attribute_profile="test",
            changed_by="test",
            created_at=now,
        ),
        "query_audit": SharedPoolQueryAudit(
            id="pg-query-audit",
            broker_id="pg-broker",
            load_id="pg-load",
            query_type="test",
            policy_version="test",
            policy_revision=1,
            scoring_version="test",
            normalization_version="test",
            participant_scope_digest="a" * 64,
            participant_count=1,
            result_count=0,
            created_at=now,
        ),
    }
    session.add_all(rows.values())
    session.commit()
    return {name: row.id for name, row in rows.items()}


def test_postgres_schema_is_migrated_and_append_only_triggers_are_live(migrated_postgres) -> None:
    engine, _ = migrated_postgres
    with Session(engine) as session:
        assert session.scalar(text("SELECT version_num FROM alembic_version")) == "b7c4e2d9f601"
        row_ids = seed_append_only_rows(session)
        mutation_targets = (
            (RateLineItem, row_ids["rate_line_item"], {"amount": Decimal("1.00")}),
            (
                LoadRateObservation,
                row_ids["rate_observation"],
                {"amount": Decimal("1.00")},
            ),
            (
                SharedPoolPolicyEvent,
                row_ids["policy_event"],
                {"reason": "mutated"},
            ),
            (
                SharedPoolQueryAudit,
                row_ids["query_audit"],
                {"result_count": 1},
            ),
        )
        for model, row_id, values in mutation_targets:
            with pytest.raises(DBAPIError):
                session.execute(update(model).where(model.id == row_id).values(**values))
                session.flush()
            session.rollback()


def test_postgres_migration_rollback_isolation_leaves_no_partial_rows(migrated_postgres) -> None:
    engine, _ = migrated_postgres
    with Session(engine) as session:
        now = datetime.now(timezone.utc)
        session.add(Broker(id="rollback-broker", name="Rollback Broker", created_at=now))
        session.flush()
        session.rollback()
        assert session.get(Broker, "rollback-broker") is None


def test_postgres_migration_downgrade_and_reupgrade_round_trip(migrated_postgres) -> None:
    _, schema_url = migrated_postgres
    previous_database_url = settings.database_url
    try:
        settings.database_url = schema_url
        alembic_config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
        command.downgrade(alembic_config, "base")
        command.upgrade(alembic_config, "head")
        settings.database_url = previous_database_url
        with Session(migrated_postgres[0]) as session:
            assert session.scalar(text("SELECT version_num FROM alembic_version")) == "b7c4e2d9f601"
    finally:
        settings.database_url = previous_database_url
