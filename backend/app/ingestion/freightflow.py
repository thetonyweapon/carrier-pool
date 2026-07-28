import argparse
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import (
    BrokerSource,
    Carrier,
    Customer,
    EquipmentType,
    IngestionFile,
    IngestionStatus,
    Load,
    LoadStatus,
    LoadStop,
    LoadVersion,
    StopType,
    TmsType,
    validate_currency,
)


class FreightFlowIngestionError(Exception):
    """Base exception for FreightFlow ingestion errors."""


class ConflictingFileError(FreightFlowIngestionError):
    """A filename was already ingested with different content."""


class OutOfOrderFileError(FreightFlowIngestionError):
    """A source file predates the latest successful source sync."""


class InvalidFreightFlowPayloadError(FreightFlowIngestionError):
    """The source payload cannot be normalized safely."""


class FreightFlowModel(BaseModel):
    model_config = ConfigDict(extra="ignore")


class FreightFlowCustomer(FreightFlowModel):
    customerId: Union[int, str]
    name: str


class FreightFlowCarrier(FreightFlowModel):
    carrierMasterId: Union[int, str]
    name: str
    mcNumber: Optional[str] = None
    dotNumber: Optional[str] = None
    phoneNumber: Optional[str] = None


class FreightFlowStop(FreightFlowModel):
    stopType: str
    city: str
    state: str
    zipCode: str
    estimatedReadyDateTime: Optional[datetime] = None
    estimatedCloseDateTime: Optional[datetime] = None
    actualDepartureDateTime: Optional[datetime] = None


class FreightFlowLoad(FreightFlowModel):
    shipmentId: Union[int, str]
    status: str
    mileage: Optional[Decimal] = None
    totalSell: Optional[Decimal] = None
    totalBuy: Optional[Decimal] = None
    customer: FreightFlowCustomer
    carrier: Optional[FreightFlowCarrier] = None
    equipment: Optional[str] = None
    weightTotal: Optional[Decimal] = None
    stops: List[FreightFlowStop] = Field(min_length=1)
    createdDate: datetime
    lastModifiedDate: datetime


class FreightFlowSync(FreightFlowModel):
    syncedAt: datetime
    loads: List[FreightFlowLoad]


@dataclass(frozen=True)
class IngestionResult:
    filename: str
    processed_loads: int
    duplicate: bool


STATUS_MAP = {
    "Quoting": LoadStatus.PLANNED,
    "Booking": LoadStatus.ACTIVE,
    "Dispatched": LoadStatus.COVERED,
    "At Shipper": LoadStatus.COVERED,
    "En Route": LoadStatus.IN_TRANSIT,
    "At Receiver": LoadStatus.IN_TRANSIT,
    "Delivered": LoadStatus.DELIVERED,
    "Completed": LoadStatus.COMPLETED,
}

BOOKED_STATUSES = {
    LoadStatus.COVERED,
    LoadStatus.IN_TRANSIT,
    LoadStatus.DELIVERED,
    LoadStatus.COMPLETED,
}


def ingest_file(session: Session, broker_source_id: str, path: Path) -> IngestionResult:
    raw_contents = path.read_bytes()
    return ingest_contents(session, broker_source_id, path.name, raw_contents)


def ingest_contents(
    session: Session,
    broker_source_id: str,
    filename: str,
    raw_contents: bytes,
) -> IngestionResult:
    try:
        raw_payload = json.loads(raw_contents)
        sync = FreightFlowSync.model_validate(raw_payload)
    except (json.JSONDecodeError, ValidationError) as exc:
        raise InvalidFreightFlowPayloadError("Invalid FreightFlow sync payload") from exc

    _require_timezone(sync.syncedAt, "syncedAt")
    synced_at = _to_utc(sync.syncedAt)
    checksum = hashlib.sha256(raw_contents).hexdigest()

    try:
        with session.begin():
            # PostgreSQL uses this row lock to serialize files for one source;
            # SQLite accepts the clause but does not provide row-level locking.
            source = session.scalar(
                select(BrokerSource).where(BrokerSource.id == broker_source_id).with_for_update()
            )
            if source is None:
                raise FreightFlowIngestionError(f"Unknown broker source: {broker_source_id}")
            if source.tms_type != TmsType.FREIGHTFLOW:
                raise FreightFlowIngestionError("Broker source is not configured for FreightFlow")

            existing_file = session.scalar(
                select(IngestionFile).where(
                    IngestionFile.broker_source_id == source.id,
                    IngestionFile.filename == filename,
                )
            )
            if existing_file is not None:
                if (
                    existing_file.checksum == checksum
                    and existing_file.status == IngestionStatus.SUCCEEDED
                ):
                    # The transaction context commits this read-only idempotent path as a no-op.
                    return IngestionResult(filename=filename, processed_loads=0, duplicate=True)
                raise ConflictingFileError(
                    f"Source file {filename} was already recorded with different content or status"
                )

            latest_synced_at = session.scalar(
                select(func.max(IngestionFile.synced_at)).where(
                    IngestionFile.broker_source_id == source.id,
                    IngestionFile.status == IngestionStatus.SUCCEEDED,
                )
            )
            if latest_synced_at is not None and synced_at <= _to_utc(latest_synced_at):
                raise OutOfOrderFileError(
                    f"Sync {synced_at.isoformat()} is not later than {latest_synced_at.isoformat()}"
                )

            ingestion_file = IngestionFile(
                broker_id=source.broker_id,
                broker_source_id=source.id,
                filename=filename,
                checksum=checksum,
                synced_at=synced_at,
                status=IngestionStatus.PROCESSING,
            )
            session.add(ingestion_file)
            session.flush()

            for raw_load, source_load in zip(raw_payload["loads"], sync.loads):
                _ingest_load(session, source, ingestion_file, source_load, raw_load)
            ingestion_file.status = IngestionStatus.SUCCEEDED
            ingestion_file.processed_at = datetime.now(timezone.utc)
    except IntegrityError as exc:
        raise FreightFlowIngestionError(
            "FreightFlow ingestion violated a database constraint; retry if another sync is running"
        ) from exc

    return IngestionResult(filename=filename, processed_loads=len(sync.loads), duplicate=False)


def _ingest_load(
    session: Session,
    source: BrokerSource,
    ingestion_file: IngestionFile,
    source_load: FreightFlowLoad,
    raw_load: Dict[str, Any],
) -> None:
    _require_timezone(source_load.createdDate, "createdDate")
    _require_timezone(source_load.lastModifiedDate, "lastModifiedDate")
    source_created_at = _to_utc(source_load.createdDate)
    source_updated_at = _to_utc(source_load.lastModifiedDate)
    customer_rate = _validate_source_currency(source_load.totalSell, "totalSell")
    carrier_rate = _validate_source_currency(source_load.totalBuy, "totalBuy")
    status = _map_status(source_load.status)
    equipment_type = _map_equipment(source_load.equipment)
    customer = _upsert_customer(session, source, source_load.customer, ingestion_file.synced_at)
    carrier = _upsert_carrier(session, source, source_load.carrier, ingestion_file.synced_at)
    source_load_id = str(source_load.shipmentId)

    load = session.scalar(
        select(Load).where(
            Load.broker_source_id == source.id,
            Load.source_load_id == source_load_id,
        )
    )
    if load is None:
        load = Load(
            broker_id=source.broker_id,
            broker_source_id=source.id,
            source_load_id=source_load_id,
            display_number=source_load_id,
            status=status,
            customer_id=customer.id,
            carrier_id=carrier.id if carrier is not None else None,
            equipment_type=equipment_type,
            weight_lbs=source_load.weightTotal,
            distance_miles=source_load.mileage,
            customer_rate=customer_rate,
            carrier_rate=carrier_rate,
            source_created_at=source_created_at,
            source_updated_at=source_updated_at,
            first_seen_at=ingestion_file.synced_at,
            last_synced_at=ingestion_file.synced_at,
        )
        session.add(load)
    else:
        load.display_number = source_load_id
        load.status = status
        load.customer_id = customer.id
        load.carrier_id = carrier.id if carrier is not None else None
        load.equipment_type = equipment_type
        load.weight_lbs = source_load.weightTotal
        load.distance_miles = source_load.mileage
        load.customer_rate = customer_rate
        load.carrier_rate = carrier_rate
        load.source_created_at = source_created_at
        load.source_updated_at = source_updated_at
        load.last_synced_at = ingestion_file.synced_at

    if load.booked_at is None and (carrier is not None or status in BOOKED_STATUSES):
        load.booked_at = ingestion_file.synced_at

    session.flush()
    stops = _sync_stops(session, source, load, source_load.stops)

    version_number = (
        session.scalar(
            select(func.max(LoadVersion.version_number)).where(LoadVersion.load_id == load.id)
        )
        or 0
    ) + 1
    session.add(
        LoadVersion(
            broker_id=source.broker_id,
            broker_source_id=source.id,
            load_id=load.id,
            ingestion_file_id=ingestion_file.id,
            version_number=version_number,
            observed_at=ingestion_file.synced_at,
            raw_payload=raw_load,
            normalized_snapshot=_normalized_snapshot(load, stops),
        )
    )


def _upsert_customer(
    session: Session,
    source: BrokerSource,
    source_customer: FreightFlowCustomer,
    observed_at: datetime,
) -> Customer:
    source_customer_id = str(source_customer.customerId)
    customer = session.scalar(
        select(Customer).where(
            Customer.broker_source_id == source.id,
            Customer.source_customer_id == source_customer_id,
        )
    )
    if customer is None:
        customer = Customer(
            broker_id=source.broker_id,
            broker_source_id=source.id,
            source_customer_id=source_customer_id,
            name=source_customer.name,
            created_at=observed_at,
            updated_at=observed_at,
        )
        session.add(customer)
    else:
        if customer.name != source_customer.name:
            customer.name = source_customer.name
            customer.updated_at = observed_at
    session.flush()
    return customer


def _upsert_carrier(
    session: Session,
    source: BrokerSource,
    source_carrier: Optional[FreightFlowCarrier],
    observed_at: datetime,
) -> Optional[Carrier]:
    if source_carrier is None:
        return None

    source_carrier_id = str(source_carrier.carrierMasterId)
    carrier = session.scalar(
        select(Carrier).where(
            Carrier.broker_source_id == source.id,
            Carrier.source_carrier_id == source_carrier_id,
        )
    )
    if carrier is None:
        carrier = Carrier(
            broker_id=source.broker_id,
            broker_source_id=source.id,
            source_carrier_id=source_carrier_id,
            name=source_carrier.name,
            mc_number=source_carrier.mcNumber,
            dot_number=source_carrier.dotNumber,
            phone_number=source_carrier.phoneNumber,
            created_at=observed_at,
            updated_at=observed_at,
        )
        session.add(carrier)
    else:
        changed = (
            carrier.name != source_carrier.name
            or carrier.mc_number != source_carrier.mcNumber
            or carrier.dot_number != source_carrier.dotNumber
            or carrier.phone_number != source_carrier.phoneNumber
        )
        if changed:
            carrier.name = source_carrier.name
            carrier.mc_number = source_carrier.mcNumber
            carrier.dot_number = source_carrier.dotNumber
            carrier.phone_number = source_carrier.phoneNumber
            carrier.updated_at = observed_at
    session.flush()
    return carrier


def _build_stops(
    source: BrokerSource,
    load: Load,
    source_stops: List[FreightFlowStop],
) -> List[LoadStop]:
    stops = []
    for sequence_number, source_stop in enumerate(source_stops, start=1):
        _require_optional_timezone(source_stop.estimatedReadyDateTime, "estimatedReadyDateTime")
        _require_optional_timezone(source_stop.estimatedCloseDateTime, "estimatedCloseDateTime")
        _require_optional_timezone(source_stop.actualDepartureDateTime, "actualDepartureDateTime")
        stops.append(
            LoadStop(
                broker_id=source.broker_id,
                load_id=load.id,
                sequence_number=sequence_number,
                stop_type=_map_stop_type(source_stop.stopType),
                city=source_stop.city,
                state=source_stop.state,
                postal_code=source_stop.zipCode,
                scheduled_start_at=_to_optional_utc(source_stop.estimatedReadyDateTime),
                scheduled_end_at=_to_optional_utc(source_stop.estimatedCloseDateTime),
                actual_departed_at=_to_optional_utc(source_stop.actualDepartureDateTime),
            )
        )
    return stops


def _sync_stops(
    session: Session,
    source: BrokerSource,
    load: Load,
    source_stops: List[FreightFlowStop],
) -> List[LoadStop]:
    existing_stops = {
        stop.sequence_number: stop
        for stop in session.scalars(
            select(LoadStop)
            .where(LoadStop.broker_id == source.broker_id, LoadStop.load_id == load.id)
            .order_by(LoadStop.sequence_number)
        )
    }
    desired_stops = _build_stops(source, load, source_stops)
    synchronized_stops = []

    for desired_stop in desired_stops:
        existing_stop = existing_stops.pop(desired_stop.sequence_number, None)
        if existing_stop is None:
            session.add(desired_stop)
            synchronized_stops.append(desired_stop)
            continue
        existing_stop.stop_type = desired_stop.stop_type
        existing_stop.city = desired_stop.city
        existing_stop.state = desired_stop.state
        existing_stop.postal_code = desired_stop.postal_code
        existing_stop.scheduled_start_at = desired_stop.scheduled_start_at
        existing_stop.scheduled_end_at = desired_stop.scheduled_end_at
        existing_stop.actual_departed_at = desired_stop.actual_departed_at
        synchronized_stops.append(existing_stop)

    for removed_stop in existing_stops.values():
        session.delete(removed_stop)
    session.flush()
    return synchronized_stops


def _map_status(source_status: str) -> LoadStatus:
    try:
        return STATUS_MAP[source_status]
    except KeyError as exc:
        raise InvalidFreightFlowPayloadError(
            f"Unsupported FreightFlow status: {source_status}"
        ) from exc


def _map_equipment(equipment: Optional[str]) -> EquipmentType:
    if equipment is None:
        return EquipmentType.UNKNOWN
    normalized_equipment = " ".join(equipment.casefold().split())
    exact_matches = {
        "reefer": EquipmentType.REEFER,
        "refrigerated": EquipmentType.REEFER,
        "flatbed": EquipmentType.FLATBED,
        "dry van": EquipmentType.DRY_VAN,
        "van": EquipmentType.DRY_VAN,
    }
    if normalized_equipment in exact_matches:
        return exact_matches[normalized_equipment]

    matches = set()
    if "reefer" in normalized_equipment or "refrigerat" in normalized_equipment:
        matches.add(EquipmentType.REEFER)
    if "flatbed" in normalized_equipment:
        matches.add(EquipmentType.FLATBED)
    if "dry" in normalized_equipment or "van" in normalized_equipment:
        matches.add(EquipmentType.DRY_VAN)
    return next(iter(matches)) if len(matches) == 1 else EquipmentType.UNKNOWN


def _map_stop_type(source_stop_type: str) -> StopType:
    normalized_stop_type = source_stop_type.lower()
    if "pickup" in normalized_stop_type:
        return StopType.PICKUP
    if "drop" in normalized_stop_type:
        return StopType.DROPOFF
    raise InvalidFreightFlowPayloadError(f"Unsupported FreightFlow stop type: {source_stop_type}")


def _validate_source_currency(value: Optional[Decimal], field_name: str) -> Optional[Decimal]:
    try:
        return validate_currency(value)
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise InvalidFreightFlowPayloadError(
            f"{field_name} must be a Decimal value with no fractions of a cent"
        ) from exc


def _normalized_snapshot(load: Load, stops: List[LoadStop]) -> Dict[str, Any]:
    return {
        "source_load_id": load.source_load_id,
        "display_number": load.display_number,
        "status": load.status.value,
        "customer_id": load.customer_id,
        "carrier_id": load.carrier_id,
        "equipment_type": load.equipment_type.value,
        "weight_lbs": _serialize_decimal(load.weight_lbs),
        "distance_miles": _serialize_decimal(load.distance_miles),
        "customer_rate": _serialize_decimal(load.customer_rate),
        "carrier_rate": _serialize_decimal(load.carrier_rate),
        "source_created_at": _serialize_datetime(load.source_created_at),
        "source_updated_at": _serialize_datetime(load.source_updated_at),
        "stops": [
            {
                "sequence_number": stop.sequence_number,
                "stop_type": stop.stop_type.value,
                "city": stop.city,
                "state": stop.state,
                "postal_code": stop.postal_code,
                "scheduled_start_at": _serialize_datetime(stop.scheduled_start_at),
                "scheduled_end_at": _serialize_datetime(stop.scheduled_end_at),
                "actual_departed_at": _serialize_datetime(stop.actual_departed_at),
            }
            for stop in stops
        ],
    }


def _serialize_decimal(value: Optional[Decimal]) -> Optional[str]:
    return None if value is None else str(value)


def _serialize_datetime(value: Optional[datetime]) -> Optional[str]:
    return None if value is None else value.isoformat()


def _to_utc(value: datetime) -> datetime:
    """Convert a validated datetime to UTC, treating naive database values as UTC."""
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _to_optional_utc(value: Optional[datetime]) -> Optional[datetime]:
    return None if value is None else _to_utc(value)


def _require_timezone(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise InvalidFreightFlowPayloadError(f"{field_name} must include a timezone offset")


def _require_optional_timezone(value: Optional[datetime], field_name: str) -> None:
    if value is not None:
        _require_timezone(value, field_name)


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest one FreightFlow sync file")
    parser.add_argument("path", type=Path, help="Path to a plain FreightFlow sync JSON file")
    parser.add_argument(
        "--broker-source-id", required=True, help="Canonical FreightFlow broker source ID"
    )
    arguments = parser.parse_args()

    try:
        with SessionLocal() as session:
            result = ingest_file(session, arguments.broker_source_id, arguments.path)
    except (FreightFlowIngestionError, OSError, SQLAlchemyError) as exc:
        parser.exit(1, f"FreightFlow ingestion failed: {exc}\n")

    print(
        json.dumps(
            {
                "filename": result.filename,
                "processed_loads": result.processed_loads,
                "duplicate": result.duplicate,
            }
        )
    )


if __name__ == "__main__":
    main()
