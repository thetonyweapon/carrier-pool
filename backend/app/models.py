from datetime import datetime
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Optional
from uuid import uuid4

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
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


class Base(DeclarativeBase):
    pass


class Broker(Base):
    __tablename__ = "brokers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


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


class Carrier(Base):
    __tablename__ = "carriers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    broker_id: Mapped[str] = mapped_column(String(36), nullable=False)
    broker_source_id: Mapped[str] = mapped_column(String(36), nullable=False)
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
