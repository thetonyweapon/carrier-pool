from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Optional
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Numeric,
    String,
    TypeDecorator,
    UniqueConstraint,
)
from sqlalchemy import (
    Enum as SqlEnum,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, validates

CENT = Decimal("0.01")
MAX_CURRENCY = Decimal("9999999999.99")


def new_id() -> str:
    return str(uuid4())


def enum_values(enum_class: type[Enum]) -> list[str]:
    return [member.value for member in enum_class]


def validate_currency(value: Optional[Decimal]) -> Optional[Decimal]:
    if value is None:
        return None
    if not isinstance(value, Decimal):
        raise TypeError("Currency values must be Decimal instances")
    if not value.is_finite() or value.copy_abs() > MAX_CURRENCY:
        raise ValueError("Currency value is outside the supported range")
    try:
        quantized_value = value.quantize(CENT)
    except InvalidOperation as exc:
        raise ValueError("Currency value cannot be represented to cents") from exc
    if value != quantized_value:
        raise ValueError("Currency values cannot contain fractions of a cent")
    return value


class Currency(TypeDecorator):
    impl = Numeric(12, 2)
    cache_ok = True

    def process_bind_param(self, value: Optional[Decimal], dialect) -> Optional[Decimal]:
        del dialect
        return validate_currency(value)


CURRENCY = Currency()


class TmsType(str, Enum):
    FREIGHTFLOW = "freightflow"
    HAULDESK = "hauldesk"
    BROKEROS = "brokeros"


class LoadStatus(str, Enum):
    PLANNED = "planned"
    ACTIVE = "active"
    COVERED = "covered"
    IN_TRANSIT = "in_transit"
    DELIVERED = "delivered"
    COMPLETED = "completed"


class EquipmentType(str, Enum):
    DRY_VAN = "dry_van"
    REEFER = "reefer"
    FLATBED = "flatbed"
    UNKNOWN = "unknown"


class StopType(str, Enum):
    PICKUP = "pickup"
    DROPOFF = "dropoff"
    PICKUP_DROPOFF = "pickup_dropoff"


class RateSide(str, Enum):
    BILL = "bill"
    PAY = "pay"


class IngestionStatus(str, Enum):
    PROCESSING = "processing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class IngestionJobStatus(str, Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    SUCCEEDED = "succeeded"
    RETRY_WAIT = "retry_wait"
    DEAD_LETTER = "dead_letter"


TMS_TYPE = SqlEnum(
    TmsType,
    name="tms_type",
    native_enum=False,
    create_constraint=True,
    values_callable=enum_values,
)
LOAD_STATUS = SqlEnum(
    LoadStatus,
    name="load_status",
    native_enum=False,
    create_constraint=True,
    values_callable=enum_values,
)
EQUIPMENT_TYPE = SqlEnum(
    EquipmentType,
    name="equipment_type",
    native_enum=False,
    create_constraint=True,
    values_callable=enum_values,
)
STOP_TYPE = SqlEnum(
    StopType,
    name="stop_type",
    native_enum=False,
    create_constraint=True,
    values_callable=enum_values,
)
RATE_SIDE = SqlEnum(
    RateSide,
    name="rate_side",
    native_enum=False,
    create_constraint=True,
    values_callable=enum_values,
)
INGESTION_STATUS = SqlEnum(
    IngestionStatus,
    name="ingestion_status",
    native_enum=False,
    create_constraint=True,
    values_callable=enum_values,
)
INGESTION_JOB_STATUS = SqlEnum(
    IngestionJobStatus,
    name="ingestion_job_status",
    native_enum=False,
    create_constraint=True,
    values_callable=enum_values,
)


class Base(DeclarativeBase):
    pass


class Broker(Base):
    __tablename__ = "brokers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SharedPoolPolicy(Base):
    """Current broker participation state for the shared carrier pool."""

    __tablename__ = "shared_pool_policies"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    broker_id: Mapped[str] = mapped_column(String(36), nullable=False, unique=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    policy_revision: Mapped[int] = mapped_column(nullable=False, default=1)
    attribute_profile: Mapped[str] = mapped_column(String(64), nullable=False)
    changed_by: Mapped[str] = mapped_column(String(255), nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(String(1000))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["broker_id"], ["brokers.id"], name="fk_shared_pool_policies_broker", ondelete="CASCADE"
        ),
        CheckConstraint("policy_revision > 0", name="ck_shared_pool_policies_revision_positive"),
    )


class SharedPoolPolicyEvent(Base):
    """Append-only record of each broker participation policy change."""

    __tablename__ = "shared_pool_policy_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    broker_id: Mapped[str] = mapped_column(String(36), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    policy_revision: Mapped[int] = mapped_column(nullable=False)
    policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    attribute_profile: Mapped[str] = mapped_column(String(64), nullable=False)
    changed_by: Mapped[str] = mapped_column(String(255), nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["broker_id"],
            ["brokers.id"],
            name="fk_shared_pool_policy_events_broker",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "policy_revision > 0", name="ck_shared_pool_policy_events_revision_positive"
        ),
        Index("ix_shared_pool_policy_events_broker_created", "broker_id", "created_at"),
    )


class SharedPoolQueryAudit(Base):
    """Append-only audit record for each shared-pool query."""

    __tablename__ = "shared_pool_query_audits"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    broker_id: Mapped[str] = mapped_column(String(36), nullable=False)
    load_id: Mapped[str] = mapped_column(String(36), nullable=False)
    query_type: Mapped[str] = mapped_column(String(32), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_revision: Mapped[int] = mapped_column(nullable=False)
    scoring_version: Mapped[str] = mapped_column(String(64), nullable=False)
    normalization_version: Mapped[str] = mapped_column(String(64), nullable=False)
    participant_scope_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    participant_count: Mapped[int] = mapped_column(nullable=False)
    result_count: Mapped[int] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["broker_id"],
            ["brokers.id"],
            name="fk_shared_pool_query_audits_broker",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["broker_id", "load_id"],
            ["loads.broker_id", "loads.id"],
            name="fk_shared_pool_query_audits_load",
        ),
        CheckConstraint(
            "policy_revision > 0", name="ck_shared_pool_query_audits_revision_positive"
        ),
        CheckConstraint(
            "participant_count >= 0", name="ck_shared_pool_query_audits_participants_nonnegative"
        ),
        CheckConstraint(
            "result_count >= 0", name="ck_shared_pool_query_audits_results_nonnegative"
        ),
        Index("ix_shared_pool_query_audits_broker_created", "broker_id", "created_at"),
    )


class BrokerSource(Base):
    __tablename__ = "broker_sources"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    broker_id: Mapped[str] = mapped_column(String(36), nullable=False)
    tms_type: Mapped[TmsType] = mapped_column(TMS_TYPE, nullable=False)
    source_name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["broker_id"], ["brokers.id"], name="fk_broker_sources_broker", ondelete="CASCADE"
        ),
        UniqueConstraint("broker_id", "id", name="uq_broker_sources_broker_id_id"),
        UniqueConstraint("broker_id", "tms_type", name="uq_broker_sources_broker_tms_type"),
    )


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    broker_id: Mapped[str] = mapped_column(String(36), nullable=False)
    broker_source_id: Mapped[str] = mapped_column(String(36), nullable=False)
    source_customer_id: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["broker_id", "broker_source_id"],
            ["broker_sources.broker_id", "broker_sources.id"],
            name="fk_customers_source",
            ondelete="CASCADE",
        ),
        UniqueConstraint("broker_id", "id", name="uq_customers_broker_id_id"),
        UniqueConstraint(
            "broker_id", "broker_source_id", "id", name="uq_customers_broker_source_id_id"
        ),
        UniqueConstraint(
            "broker_source_id", "source_customer_id", name="uq_customers_source_customer_id"
        ),
    )


class CarrierIdentity(Base):
    __tablename__ = "carrier_identities"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    broker_id: Mapped[str] = mapped_column(String(36), nullable=False)
    normalized_mc_number: Mapped[Optional[str]] = mapped_column(String(32))
    normalized_dot_number: Mapped[Optional[str]] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["broker_id"], ["brokers.id"], name="fk_carrier_identities_broker", ondelete="CASCADE"
        ),
        CheckConstraint(
            "normalized_mc_number IS NOT NULL OR normalized_dot_number IS NOT NULL",
            name="ck_carrier_identities_has_identifier",
        ),
        UniqueConstraint("broker_id", "id", name="uq_carrier_identities_broker_id"),
        UniqueConstraint("broker_id", "normalized_mc_number", name="uq_carrier_identities_mc"),
        UniqueConstraint("broker_id", "normalized_dot_number", name="uq_carrier_identities_dot"),
    )


class Carrier(Base):
    __tablename__ = "carriers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    broker_id: Mapped[str] = mapped_column(String(36), nullable=False)
    broker_source_id: Mapped[str] = mapped_column(String(36), nullable=False)
    carrier_identity_id: Mapped[Optional[str]] = mapped_column(String(36))
    source_carrier_id: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    mc_number: Mapped[Optional[str]] = mapped_column(String(32))
    dot_number: Mapped[Optional[str]] = mapped_column(String(32))
    phone_number: Mapped[Optional[str]] = mapped_column(String(64))
    home_city: Mapped[Optional[str]] = mapped_column(String(255))
    home_state: Mapped[Optional[str]] = mapped_column(String(2))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["broker_id", "broker_source_id"],
            ["broker_sources.broker_id", "broker_sources.id"],
            name="fk_carriers_source",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["broker_id", "carrier_identity_id"],
            ["carrier_identities.broker_id", "carrier_identities.id"],
            name="fk_carriers_identity",
        ),
        UniqueConstraint("broker_id", "id", name="uq_carriers_broker_id_id"),
        UniqueConstraint(
            "broker_id", "broker_source_id", "id", name="uq_carriers_broker_source_id_id"
        ),
        UniqueConstraint(
            "broker_source_id", "source_carrier_id", name="uq_carriers_source_carrier_id"
        ),
    )


class Load(Base):
    __tablename__ = "loads"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    broker_id: Mapped[str] = mapped_column(String(36), nullable=False)
    broker_source_id: Mapped[str] = mapped_column(String(36), nullable=False)
    source_load_id: Mapped[str] = mapped_column(String(255), nullable=False)
    display_number: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[LoadStatus] = mapped_column(LOAD_STATUS, nullable=False)
    customer_id: Mapped[str] = mapped_column(String(36), nullable=False)
    carrier_id: Mapped[Optional[str]] = mapped_column(String(36))
    equipment_type: Mapped[EquipmentType] = mapped_column(EQUIPMENT_TYPE, nullable=False)
    weight_lbs: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 1))
    distance_miles: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 1))
    customer_rate: Mapped[Optional[Decimal]] = mapped_column(CURRENCY)
    carrier_rate: Mapped[Optional[Decimal]] = mapped_column(CURRENCY)
    source_created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    source_updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    booked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["broker_id", "broker_source_id"],
            ["broker_sources.broker_id", "broker_sources.id"],
            name="fk_loads_source",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["broker_id", "broker_source_id", "customer_id"],
            ["customers.broker_id", "customers.broker_source_id", "customers.id"],
            name="fk_loads_customer",
        ),
        ForeignKeyConstraint(
            ["broker_id", "broker_source_id", "carrier_id"],
            ["carriers.broker_id", "carriers.broker_source_id", "carriers.id"],
            name="fk_loads_carrier",
        ),
        UniqueConstraint("broker_id", "id", name="uq_loads_broker_id_id"),
        UniqueConstraint(
            "broker_id", "broker_source_id", "id", name="uq_loads_broker_source_id_id"
        ),
        UniqueConstraint("broker_source_id", "source_load_id", name="uq_loads_source_load_id"),
        Index(
            "ix_loads_broker_status_synced",
            "broker_id",
            "status",
            "last_synced_at",
            "id",
        ),
    )

    @validates("customer_rate", "carrier_rate")
    def validate_rate(self, key: str, value: Optional[Decimal]) -> Optional[Decimal]:
        del key
        return validate_currency(value)


class LoadStop(Base):
    __tablename__ = "load_stops"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    broker_id: Mapped[str] = mapped_column(String(36), nullable=False)
    load_id: Mapped[str] = mapped_column(String(36), nullable=False)
    sequence_number: Mapped[int] = mapped_column(nullable=False)
    stop_type: Mapped[StopType] = mapped_column(STOP_TYPE, nullable=False)
    city: Mapped[str] = mapped_column(String(255), nullable=False)
    state: Mapped[str] = mapped_column(String(2), nullable=False)
    postal_code: Mapped[str] = mapped_column(String(16), nullable=False)
    scheduled_date: Mapped[Optional[date]] = mapped_column()
    source_location_id: Mapped[Optional[str]] = mapped_column(String(255))
    location_name: Mapped[Optional[str]] = mapped_column(String(255))
    source_sequence_value: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 3))
    latitude: Mapped[Optional[Decimal]] = mapped_column(Numeric(9, 6))
    longitude: Mapped[Optional[Decimal]] = mapped_column(Numeric(9, 6))
    scheduled_start_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    scheduled_end_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    actual_arrived_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    actual_departed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        ForeignKeyConstraint(
            ["broker_id", "load_id"],
            ["loads.broker_id", "loads.id"],
            name="fk_load_stops_load",
            ondelete="CASCADE",
        ),
        CheckConstraint("sequence_number > 0", name="ck_load_stops_sequence_positive"),
        UniqueConstraint("broker_id", "id", name="uq_load_stops_broker_id_id"),
        UniqueConstraint("load_id", "sequence_number", name="uq_load_stops_load_sequence"),
    )


class PlatformAssignment(Base):
    """Current platform decision, deliberately separate from TMS ownership."""

    __tablename__ = "platform_assignments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    broker_id: Mapped[str] = mapped_column(String(36), nullable=False)
    load_id: Mapped[str] = mapped_column(String(36), nullable=False)
    carrier_id: Mapped[str] = mapped_column(String(36), nullable=False)
    candidate_id: Mapped[Optional[str]] = mapped_column(String(255))
    assignment_version: Mapped[int] = mapped_column(nullable=False, default=1)
    demo_actor: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["broker_id", "load_id"],
            ["loads.broker_id", "loads.id"],
            name="fk_platform_assignments_load",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["broker_id", "carrier_id"],
            ["carriers.broker_id", "carriers.id"],
            name="fk_platform_assignments_carrier",
        ),
        UniqueConstraint("broker_id", "load_id", name="uq_platform_assignments_broker_load"),
        UniqueConstraint("broker_id", "id", name="uq_platform_assignments_broker_id"),
        CheckConstraint("assignment_version > 0", name="ck_platform_assignments_version_positive"),
        Index("ix_platform_assignments_broker_carrier", "broker_id", "carrier_id"),
    )


class PlatformAssignmentEvent(Base):
    """Append-only audit record for each platform assignment decision."""

    __tablename__ = "platform_assignment_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    broker_id: Mapped[str] = mapped_column(String(36), nullable=False)
    assignment_id: Mapped[str] = mapped_column(String(36), nullable=False)
    load_id: Mapped[str] = mapped_column(String(36), nullable=False)
    carrier_id: Mapped[str] = mapped_column(String(36), nullable=False)
    candidate_id: Mapped[Optional[str]] = mapped_column(String(255))
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(128))
    assignment_version: Mapped[int] = mapped_column(nullable=False)
    demo_actor: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["broker_id", "assignment_id"],
            ["platform_assignments.broker_id", "platform_assignments.id"],
            name="fk_platform_assignment_events_assignment",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["broker_id", "load_id"],
            ["loads.broker_id", "loads.id"],
            name="fk_platform_assignment_events_load",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["broker_id", "carrier_id"],
            ["carriers.broker_id", "carriers.id"],
            name="fk_platform_assignment_events_carrier",
        ),
        CheckConstraint(
            "assignment_version > 0", name="ck_platform_assignment_events_version_positive"
        ),
        UniqueConstraint("broker_id", "id", name="uq_platform_assignment_events_broker_id_id"),
        UniqueConstraint(
            "broker_id", "idempotency_key", name="uq_platform_assignment_events_idempotency"
        ),
        Index("ix_platform_assignment_events_assignment_created", "assignment_id", "created_at"),
    )


class LoadVersion(Base):
    __tablename__ = "load_versions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    broker_id: Mapped[str] = mapped_column(String(36), nullable=False)
    broker_source_id: Mapped[str] = mapped_column(String(36), nullable=False)
    load_id: Mapped[str] = mapped_column(String(36), nullable=False)
    ingestion_file_id: Mapped[str] = mapped_column(String(36), nullable=False)
    version_number: Mapped[int] = mapped_column(nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    raw_payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    normalized_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["broker_id", "broker_source_id", "load_id"],
            ["loads.broker_id", "loads.broker_source_id", "loads.id"],
            name="fk_load_versions_load",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["broker_id", "broker_source_id", "ingestion_file_id"],
            [
                "ingestion_files.broker_id",
                "ingestion_files.broker_source_id",
                "ingestion_files.id",
            ],
            name="fk_load_versions_ingestion_file",
        ),
        UniqueConstraint("broker_id", "id", name="uq_load_versions_broker_id_id"),
        UniqueConstraint("load_id", "version_number", name="uq_load_versions_load_version"),
    )


class RateLineItem(Base):
    __tablename__ = "rate_line_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    broker_id: Mapped[str] = mapped_column(String(36), nullable=False)
    broker_source_id: Mapped[str] = mapped_column(String(36), nullable=False)
    load_id: Mapped[str] = mapped_column(String(36), nullable=False)
    source_rate_id: Mapped[str] = mapped_column(String(255), nullable=False)
    side: Mapped[RateSide] = mapped_column(RATE_SIDE, nullable=False)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    amount: Mapped[Decimal] = mapped_column(CURRENCY, nullable=False)
    source_created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["broker_id", "broker_source_id"],
            ["broker_sources.broker_id", "broker_sources.id"],
            name="fk_rate_line_items_source",
        ),
        ForeignKeyConstraint(
            ["broker_id", "broker_source_id", "load_id"],
            ["loads.broker_id", "loads.broker_source_id", "loads.id"],
            name="fk_rate_line_items_load",
        ),
        UniqueConstraint("broker_id", "id", name="uq_rate_line_items_broker_id_id"),
        UniqueConstraint(
            "broker_source_id", "source_rate_id", name="uq_rate_line_items_source_rate_id"
        ),
    )

    @validates("amount")
    def validate_amount(self, key: str, value: Decimal) -> Decimal:
        del key
        return validate_currency(value)


class LoadRateObservation(Base):
    """Append-only snapshot of a TMS's mutable total rate value."""

    __tablename__ = "load_rate_observations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    broker_id: Mapped[str] = mapped_column(String(36), nullable=False)
    broker_source_id: Mapped[str] = mapped_column(String(36), nullable=False)
    load_id: Mapped[str] = mapped_column(String(36), nullable=False)
    ingestion_file_id: Mapped[str] = mapped_column(String(36), nullable=False)
    side: Mapped[RateSide] = mapped_column(RATE_SIDE, nullable=False)
    amount: Mapped[Optional[Decimal]] = mapped_column(CURRENCY)
    observation_number: Mapped[int] = mapped_column(nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        ForeignKeyConstraint(
            ["broker_id", "broker_source_id"],
            ["broker_sources.broker_id", "broker_sources.id"],
            name="fk_load_rate_observations_source",
        ),
        ForeignKeyConstraint(
            ["broker_id", "broker_source_id", "load_id"],
            ["loads.broker_id", "loads.broker_source_id", "loads.id"],
            name="fk_load_rate_observations_load",
        ),
        ForeignKeyConstraint(
            ["broker_id", "broker_source_id", "ingestion_file_id"],
            [
                "ingestion_files.broker_id",
                "ingestion_files.broker_source_id",
                "ingestion_files.id",
            ],
            name="fk_load_rate_observations_ingestion_file",
        ),
        UniqueConstraint("broker_id", "id", name="uq_load_rate_observations_broker_id_id"),
        UniqueConstraint(
            "load_id", "side", "observation_number", name="uq_load_rate_observations_sequence"
        ),
        UniqueConstraint(
            "ingestion_file_id",
            "load_id",
            "side",
            name="uq_load_rate_observations_file_load_side",
        ),
    )

    @validates("amount")
    def validate_amount(self, key: str, value: Optional[Decimal]) -> Optional[Decimal]:
        del key
        return validate_currency(value)


class IngestionFile(Base):
    __tablename__ = "ingestion_files"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    broker_id: Mapped[str] = mapped_column(String(36), nullable=False)
    broker_source_id: Mapped[str] = mapped_column(String(36), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[IngestionStatus] = mapped_column(INGESTION_STATUS, nullable=False)
    processed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[Optional[str]] = mapped_column(String(2000))

    __table_args__ = (
        ForeignKeyConstraint(
            ["broker_id", "broker_source_id"],
            ["broker_sources.broker_id", "broker_sources.id"],
            name="fk_ingestion_files_source",
            ondelete="CASCADE",
        ),
        UniqueConstraint("broker_id", "id", name="uq_ingestion_files_broker_id_id"),
        UniqueConstraint(
            "broker_id", "broker_source_id", "id", name="uq_ingestion_files_broker_source_id_id"
        ),
        UniqueConstraint("broker_source_id", "filename", name="uq_ingestion_files_source_filename"),
    )


class IngestionJob(Base):
    """Durable scheduling and failure state around one source file."""

    __tablename__ = "ingestion_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    broker_id: Mapped[str] = mapped_column(String(36), nullable=False)
    broker_source_id: Mapped[str] = mapped_column(String(36), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_path: Mapped[str] = mapped_column(String(2048), nullable=False)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[IngestionJobStatus] = mapped_column(
        INGESTION_JOB_STATUS, nullable=False, default=IngestionJobStatus.QUEUED
    )
    attempt_count: Mapped[int] = mapped_column(nullable=False, default=0)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    lease_owner: Mapped[Optional[str]] = mapped_column(String(255))
    lease_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    failure_class: Mapped[Optional[str]] = mapped_column(String(255))
    error_message: Mapped[Optional[str]] = mapped_column(String(2000))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        ForeignKeyConstraint(
            ["broker_id", "broker_source_id"],
            ["broker_sources.broker_id", "broker_sources.id"],
            name="fk_ingestion_jobs_source",
            ondelete="CASCADE",
        ),
        CheckConstraint("attempt_count >= 0", name="ck_ingestion_jobs_attempt_nonnegative"),
        UniqueConstraint("broker_source_id", "filename", name="uq_ingestion_jobs_source_filename"),
        Index("ix_ingestion_jobs_status_available", "status", "available_at", "id"),
    )
