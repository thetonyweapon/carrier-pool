import argparse
import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.ingestion.common import (
    IngestionLimitError,
    enforce_ingestion_file_size,
    enforce_ingestion_limits,
    ingestion_transaction,
    read_verified_file,
)
from app.models import (
    BrokerSource,
    Carrier,
    Customer,
    EquipmentType,
    IngestionFile,
    IngestionStatus,
    Load,
    LoadRateObservation,
    LoadStatus,
    LoadStop,
    LoadVersion,
    RateSide,
    StopType,
    TmsType,
    validate_currency,
)

KG_TO_LB = Decimal("2.2046226218487757")
WEIGHT_SCALE = Decimal("0.1")
MAX_WEIGHT_LBS = Decimal("99999999999.9")
MAX_DISTANCE_MILES = Decimal("999999999.9")
STATUS_MAP = {
    "Quotes Requested": LoadStatus.PLANNED,
    "Ready to Book": LoadStatus.ACTIVE,
    "Booked": LoadStatus.COVERED,
    "In Transit": LoadStatus.IN_TRANSIT,
    "Delivered": LoadStatus.DELIVERED,
    "Invoiced": LoadStatus.COMPLETED,
    "Paid": LoadStatus.COMPLETED,
}
BOOKED_STATUSES = {
    LoadStatus.COVERED,
    LoadStatus.IN_TRANSIT,
    LoadStatus.DELIVERED,
    LoadStatus.COMPLETED,
}
EQUIPMENT_MAP = {
    "Dry Van": EquipmentType.DRY_VAN,
    "Reefer": EquipmentType.REEFER,
    "Flatbed": EquipmentType.FLATBED,
}
ACCOUNT_KEYS = {"type", "record_type", "Name"}
LOCATION_KEYS = {"type", "Name", "bos__City__c", "bos__State__c", "bos__Postal_Code__c"}


class BrokerOSIngestionError(Exception):
    """Base exception for BrokerOS ingestion errors."""


class ConflictingBrokerOSFileError(BrokerOSIngestionError):
    """A filename was already ingested with different content."""


class OutOfOrderBrokerOSFileError(BrokerOSIngestionError):
    """A source file is not later than the latest successful sync."""


class InvalidBrokerOSPayloadError(BrokerOSIngestionError):
    """The source payload cannot be normalized safely."""


class BrokerOSModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class BrokerOSStop(BrokerOSModel):
    source_sequence: Decimal = Field(alias="bos__Number__c")
    is_pickup: bool = Field(alias="bos__Is_Pickup__c")
    is_dropoff: bool = Field(alias="bos__Is_Dropoff__c")
    location_ref: str = Field(alias="bos__Location__c")
    scheduled_date: date = Field(alias="bos__Scheduled_Date__c")
    arrival_time: Optional[datetime] = Field(default=None, alias="bos__Arrival_Time__c")


class BrokerOSLineItem(BrokerOSModel):
    commodity: Optional[str] = Field(default=None, alias="bos__Commodity__c")
    weight: Optional[Decimal] = Field(default=None, alias="bos__Weight__c")
    weight_units: Optional[str] = Field(default=None, alias="bos__Weight_Units__c")
    pallet_count: Optional[Decimal] = Field(default=None, alias="bos__Pallet_Count__c")


class BrokerOSLoad(BrokerOSModel):
    source_load_id: str = Field(alias="Id")
    display_number: str = Field(alias="Name")
    source_status: str = Field(alias="bos__Load_Status__c")
    distance_miles: Optional[Decimal] = Field(default=None, alias="bos__Distance_Miles__c")
    customer_ref: str = Field(alias="bos__Customer__c")
    carrier_ref: Optional[str] = Field(default=None, alias="bos__Carrier__c")
    equipment: Optional[str] = Field(default=None, alias="bos__Equipment_Type__c")
    customer_rate: Optional[Decimal] = Field(default=None, alias="bos__Customer_Rate__c")
    carrier_rate: Optional[Decimal] = Field(default=None, alias="bos__Carrier_Rate__c")
    stops: List[BrokerOSStop] = Field(alias="bos__Stops__r", min_length=1)
    line_items: List[BrokerOSLineItem] = Field(alias="bos__Line_Items__r")
    source_created_at: datetime = Field(alias="CreatedDate")
    source_updated_at: datetime = Field(alias="LastModifiedDate")


class BrokerOSSync(BrokerOSModel):
    synced_at: datetime = Field(alias="synced_at")
    records: List[BrokerOSLoad]
    referenced_records: Dict[str, dict]


@dataclass(frozen=True)
class IngestionResult:
    filename: str
    processed_loads: int
    duplicate: bool


def ingest_file(session: Session, broker_source_id: str, path: Path) -> IngestionResult:
    try:
        enforce_ingestion_file_size(path)
    except IngestionLimitError as exc:
        raise InvalidBrokerOSPayloadError("Invalid BrokerOS sync payload") from exc
    return ingest_contents(session, broker_source_id, path.name, read_verified_file(path))


def ingest_contents(
    session: Session,
    broker_source_id: str,
    filename: str,
    raw_contents: bytes,
    before_commit: Optional[Callable[[Session], None]] = None,
) -> IngestionResult:
    raw_payload, sync = _parse_payload(raw_contents)
    synced_at = _require_aware_utc(sync.synced_at, "synced_at")
    checksum = hashlib.sha256(raw_contents).hexdigest()
    try:
        with ingestion_transaction(session, "brokeros"):
            source = session.scalar(
                select(BrokerSource).where(BrokerSource.id == broker_source_id).with_for_update()
            )
            if source is None:
                raise BrokerOSIngestionError(f"Unknown broker source: {broker_source_id}")
            if source.tms_type != TmsType.BROKEROS:
                raise BrokerOSIngestionError("Broker source is not configured for BrokerOS")

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
                    return IngestionResult(filename=filename, processed_loads=0, duplicate=True)
                raise ConflictingBrokerOSFileError(
                    f"Source file {filename} was already recorded with different content or status"
                )

            latest_synced_at = session.scalar(
                select(func.max(IngestionFile.synced_at)).where(
                    IngestionFile.broker_source_id == source.id,
                    IngestionFile.status == IngestionStatus.SUCCEEDED,
                )
            )
            if latest_synced_at is not None and synced_at <= _as_utc(latest_synced_at):
                raise OutOfOrderBrokerOSFileError(
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

            raw_records = raw_payload["records"]
            seen_ids = set()
            for source_load, raw_load in zip(sync.records, raw_records):
                if source_load.source_load_id in seen_ids:
                    raise InvalidBrokerOSPayloadError(
                        f"Duplicate BrokerOS load Id: {source_load.source_load_id}"
                    )
                seen_ids.add(source_load.source_load_id)
                _ingest_load(
                    session,
                    source,
                    ingestion_file,
                    source_load,
                    raw_load,
                    sync.referenced_records,
                )
            if before_commit is not None:
                before_commit(session)
            ingestion_file.status = IngestionStatus.SUCCEEDED
            ingestion_file.processed_at = datetime.now(timezone.utc)
    except IntegrityError as exc:
        raise BrokerOSIngestionError(
            "BrokerOS ingestion violated a database constraint; retry if another sync is running"
        ) from exc
    return IngestionResult(filename=filename, processed_loads=len(sync.records), duplicate=False)


def _parse_payload(raw_contents: bytes) -> Tuple[dict, BrokerOSSync]:
    try:
        raw_payload = json.loads(raw_contents)
        enforce_ingestion_limits(raw_contents, raw_payload)
        validation_payload = json.loads(raw_contents, parse_float=Decimal)
        return raw_payload, BrokerOSSync.model_validate(validation_payload)
    except (UnicodeDecodeError, json.JSONDecodeError, ValidationError, IngestionLimitError) as exc:
        raise InvalidBrokerOSPayloadError("Invalid BrokerOS sync payload") from exc


def _ingest_load(
    session: Session,
    source: BrokerSource,
    ingestion_file: IngestionFile,
    source_load: BrokerOSLoad,
    raw_load: dict,
    references: Dict[str, dict],
) -> None:
    source_created_at = _require_aware_utc(source_load.source_created_at, "CreatedDate")
    source_updated_at = _require_aware_utc(source_load.source_updated_at, "LastModifiedDate")
    load = session.scalar(
        select(Load).where(
            Load.broker_source_id == source.id,
            Load.source_load_id == source_load.source_load_id,
        )
    )
    customer_reference = _resolve_account(
        references, source_load.customer_ref, "Customer", "customer reference"
    )
    carrier_reference = (
        _resolve_account(references, source_load.carrier_ref, "Carrier", "carrier reference")
        if source_load.carrier_ref is not None
        else None
    )
    status = _map_status(source_load.source_status)
    equipment_type = _map_equipment(source_load.equipment)
    customer_rate = _validate_currency(source_load.customer_rate, "bos__Customer_Rate__c")
    carrier_rate = _validate_currency(source_load.carrier_rate, "bos__Carrier_Rate__c")
    distance_miles = _validate_distance(source_load.distance_miles)
    weight_lbs = _aggregate_weight(source_load.line_items)
    if (
        load is not None
        and load.source_updated_at is not None
        and source_updated_at < _as_utc(load.source_updated_at)
    ):
        return

    customer = _upsert_customer(
        session, source, source_load.customer_ref, customer_reference, ingestion_file.synced_at
    )
    carrier = (
        _upsert_carrier(
            session, source, source_load.carrier_ref, carrier_reference, ingestion_file.synced_at
        )
        if carrier_reference is not None
        else None
    )

    if load is None:
        load = Load(
            broker_id=source.broker_id,
            broker_source_id=source.id,
            source_load_id=source_load.source_load_id,
            display_number=source_load.display_number,
            status=status,
            customer_id=customer.id,
            carrier_id=carrier.id if carrier else None,
            equipment_type=equipment_type,
            weight_lbs=weight_lbs,
            distance_miles=distance_miles,
            customer_rate=customer_rate,
            carrier_rate=carrier_rate,
            source_created_at=source_created_at,
            source_updated_at=source_updated_at,
            first_seen_at=ingestion_file.synced_at,
            last_synced_at=ingestion_file.synced_at,
        )
        session.add(load)
    else:
        load.display_number = source_load.display_number
        load.status = status
        load.customer_id = customer.id
        load.carrier_id = carrier.id if carrier else None
        load.equipment_type = equipment_type
        load.weight_lbs = weight_lbs
        load.distance_miles = distance_miles
        load.customer_rate = customer_rate
        load.carrier_rate = carrier_rate
        load.source_created_at = source_created_at
        load.source_updated_at = source_updated_at
        load.last_synced_at = ingestion_file.synced_at

    if load.booked_at is None and (carrier is not None or status in BOOKED_STATUSES):
        load.booked_at = source_updated_at
    session.flush()
    stops, used_location_ids = _sync_stops(session, source, load, source_load.stops, references)
    _record_rate_observations(
        session,
        source,
        ingestion_file,
        load,
        customer_rate,
        carrier_rate,
        source_updated_at,
    )
    session.flush()
    used_references = {
        reference_id: references[reference_id]
        for reference_id in {source_load.customer_ref, source_load.carrier_ref, *used_location_ids}
        if reference_id is not None
    }
    session.add(
        LoadVersion(
            broker_id=source.broker_id,
            broker_source_id=source.id,
            load_id=load.id,
            ingestion_file_id=ingestion_file.id,
            version_number=_next_version_number(session, load.id),
            observed_at=ingestion_file.synced_at,
            raw_payload={"record": raw_load, "referenced_records": used_references},
            normalized_snapshot=_normalized_snapshot(load, stops, source_load.source_status),
        )
    )


def _resolve_reference(references: Dict[str, dict], reference_id: str, label: str) -> dict:
    reference = references.get(reference_id)
    if not isinstance(reference, dict):
        raise InvalidBrokerOSPayloadError(f"Missing BrokerOS {label}: {reference_id}")
    return reference


def _resolve_account(
    references: Dict[str, dict], reference_id: str, expected_record_type: str, label: str
) -> dict:
    reference = _resolve_reference(references, reference_id, label)
    if set(reference) - ACCOUNT_KEYS:
        raise InvalidBrokerOSPayloadError(f"Unexpected fields in BrokerOS {label}: {reference_id}")
    if reference.get("type") != "Account" or reference.get("record_type") != expected_record_type:
        raise InvalidBrokerOSPayloadError(f"Invalid BrokerOS {label}: {reference_id}")
    if not isinstance(reference.get("Name"), str) or not reference["Name"].strip():
        raise InvalidBrokerOSPayloadError(f"BrokerOS {label} has no name: {reference_id}")
    return reference


def _resolve_location(references: Dict[str, dict], reference_id: str) -> dict:
    reference = _resolve_reference(references, reference_id, "location reference")
    if set(reference) - LOCATION_KEYS or reference.get("type") != "Location":
        raise InvalidBrokerOSPayloadError(f"Invalid BrokerOS location: {reference_id}")
    required = ("Name", "bos__City__c", "bos__State__c", "bos__Postal_Code__c")
    if any(
        not isinstance(reference.get(key), str) or not reference[key].strip() for key in required
    ):
        raise InvalidBrokerOSPayloadError(f"BrokerOS location is incomplete: {reference_id}")
    return reference


def _upsert_customer(
    session: Session,
    source: BrokerSource,
    source_customer_id: str,
    reference: dict,
    observed_at: datetime,
) -> Customer:
    customer = session.scalar(
        select(Customer).where(
            Customer.broker_source_id == source.id,
            Customer.source_customer_id == source_customer_id,
        )
    )
    name = reference["Name"]
    if customer is None:
        customer = Customer(
            broker_id=source.broker_id,
            broker_source_id=source.id,
            source_customer_id=source_customer_id,
            name=name,
            created_at=observed_at,
            updated_at=observed_at,
        )
        session.add(customer)
    elif customer.name != name:
        customer.name = name
        customer.updated_at = observed_at
    session.flush()
    return customer


def _upsert_carrier(
    session: Session,
    source: BrokerSource,
    source_carrier_id: str,
    reference: dict,
    observed_at: datetime,
) -> Carrier:
    carrier = session.scalar(
        select(Carrier).where(
            Carrier.broker_source_id == source.id,
            Carrier.source_carrier_id == source_carrier_id,
        )
    )
    name = reference["Name"]
    if carrier is None:
        carrier = Carrier(
            broker_id=source.broker_id,
            broker_source_id=source.id,
            source_carrier_id=source_carrier_id,
            name=name,
            created_at=observed_at,
            updated_at=observed_at,
        )
        session.add(carrier)
    elif carrier.name != name:
        carrier.name = name
        carrier.updated_at = observed_at
    session.flush()
    return carrier


def _sync_stops(
    session: Session,
    source: BrokerSource,
    load: Load,
    source_stops: List[BrokerOSStop],
    references: Dict[str, dict],
) -> Tuple[List[LoadStop], List[str]]:
    if any(
        not stop.source_sequence.is_finite() or stop.source_sequence <= 0 for stop in source_stops
    ):
        raise InvalidBrokerOSPayloadError(
            f"BrokerOS stop sequence must be finite and positive for load {load.source_load_id}"
        )
    ordered_stops = sorted(source_stops, key=lambda stop: stop.source_sequence)
    if any(
        left.source_sequence == right.source_sequence
        for left, right in zip(ordered_stops, ordered_stops[1:])
    ):
        raise InvalidBrokerOSPayloadError(
            f"Duplicate BrokerOS stop sequence for load {load.source_load_id}"
        )
    desired = []
    used_location_ids = []
    for sequence_number, source_stop in enumerate(ordered_stops, start=1):
        if not source_stop.is_pickup and not source_stop.is_dropoff:
            raise InvalidBrokerOSPayloadError("BrokerOS stop must be pickup, dropoff, or both")
        location = _resolve_location(references, source_stop.location_ref)
        used_location_ids.append(source_stop.location_ref)
        if source_stop.is_pickup and source_stop.is_dropoff:
            stop_type = StopType.PICKUP_DROPOFF
        elif source_stop.is_pickup:
            stop_type = StopType.PICKUP
        else:
            stop_type = StopType.DROPOFF
        arrival = (
            _require_aware_utc(source_stop.arrival_time, "bos__Arrival_Time__c")
            if source_stop.arrival_time is not None
            else None
        )
        desired.append(
            LoadStop(
                broker_id=load.broker_id,
                load_id=load.id,
                sequence_number=sequence_number,
                stop_type=stop_type,
                city=location["bos__City__c"],
                state=location["bos__State__c"],
                postal_code=location["bos__Postal_Code__c"],
                scheduled_date=source_stop.scheduled_date,
                source_location_id=source_stop.location_ref,
                location_name=location["Name"],
                source_sequence_value=source_stop.source_sequence,
                actual_arrived_at=arrival,
            )
        )
    existing = {
        stop.sequence_number: stop
        for stop in session.scalars(
            select(LoadStop)
            .where(LoadStop.broker_id == source.broker_id, LoadStop.load_id == load.id)
            .order_by(LoadStop.sequence_number)
        )
    }
    synchronized = []
    for wanted in desired:
        current = existing.pop(wanted.sequence_number, None)
        if current is None:
            session.add(wanted)
            synchronized.append(wanted)
        else:
            for field in (
                "stop_type",
                "city",
                "state",
                "postal_code",
                "scheduled_date",
                "source_location_id",
                "location_name",
                "source_sequence_value",
                "scheduled_start_at",
                "scheduled_end_at",
                "actual_arrived_at",
                "actual_departed_at",
            ):
                setattr(current, field, getattr(wanted, field))
            synchronized.append(current)
    for removed in existing.values():
        session.delete(removed)
    session.flush()
    return synchronized, used_location_ids


def _record_rate_observations(
    session: Session,
    source: BrokerSource,
    ingestion_file: IngestionFile,
    load: Load,
    customer_rate: Optional[Decimal],
    carrier_rate: Optional[Decimal],
    source_updated_at: datetime,
) -> None:
    for side, amount in ((RateSide.BILL, customer_rate), (RateSide.PAY, carrier_rate)):
        latest = session.scalar(
            select(LoadRateObservation)
            .where(
                LoadRateObservation.load_id == load.id,
                LoadRateObservation.side == side,
            )
            .order_by(LoadRateObservation.observation_number.desc())
        )
        if latest is not None and latest.amount == amount:
            continue
        next_number = (latest.observation_number if latest is not None else 0) + 1
        session.add(
            LoadRateObservation(
                broker_id=source.broker_id,
                broker_source_id=source.id,
                load_id=load.id,
                ingestion_file_id=ingestion_file.id,
                side=side,
                amount=amount,
                observation_number=next_number,
                observed_at=ingestion_file.synced_at,
                source_updated_at=source_updated_at,
            )
        )


def _aggregate_weight(line_items: List[BrokerOSLineItem]) -> Optional[Decimal]:
    if not line_items:
        return None
    total = Decimal("0")
    found_weight = False
    for item in line_items:
        if item.weight is None:
            continue
        if item.weight < 0 or not item.weight.is_finite():
            raise InvalidBrokerOSPayloadError(
                "BrokerOS cargo weight must be finite and non-negative"
            )
        unit = (item.weight_units or "").strip().casefold()
        if unit in {"lb", "lbs", "pound", "pounds"}:
            pounds = item.weight
        elif unit in {"kg", "kgs", "kilogram", "kilograms"}:
            pounds = item.weight * KG_TO_LB
        else:
            raise InvalidBrokerOSPayloadError(
                f"Unsupported BrokerOS weight unit: {item.weight_units}"
            )
        total += pounds
        found_weight = True
    if not found_weight:
        return None
    try:
        result = total.quantize(WEIGHT_SCALE, rounding=ROUND_HALF_UP)
    except InvalidOperation as exc:
        raise InvalidBrokerOSPayloadError(
            "BrokerOS cargo weight is outside the supported range"
        ) from exc
    if result > MAX_WEIGHT_LBS:
        raise InvalidBrokerOSPayloadError("BrokerOS cargo weight is outside the supported range")
    return result


def _validate_currency(value: Optional[Decimal], field_name: str) -> Optional[Decimal]:
    try:
        return validate_currency(value)
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise InvalidBrokerOSPayloadError(
            f"{field_name} must be a Decimal value with no fractions of a cent"
        ) from exc


def _validate_distance(value: Optional[Decimal]) -> Optional[Decimal]:
    if value is None:
        return None
    if not value.is_finite() or value < 0 or value > MAX_DISTANCE_MILES:
        raise InvalidBrokerOSPayloadError("bos__Distance_Miles__c is outside the supported range")
    return value


def _map_status(value: str) -> LoadStatus:
    try:
        return STATUS_MAP[value]
    except KeyError as exc:
        raise InvalidBrokerOSPayloadError(f"Unsupported BrokerOS status: {value}") from exc


def _map_equipment(value: Optional[str]) -> EquipmentType:
    if value is None:
        return EquipmentType.UNKNOWN
    try:
        return EQUIPMENT_MAP[value]
    except KeyError as exc:
        raise InvalidBrokerOSPayloadError(f"Unsupported BrokerOS equipment: {value}") from exc


def _require_aware_utc(value: Optional[datetime], field_name: str) -> Optional[datetime]:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        raise InvalidBrokerOSPayloadError(f"{field_name} must include a timezone offset")
    return value.astimezone(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _next_version_number(session: Session, load_id: str) -> int:
    return (
        session.scalar(
            select(func.max(LoadVersion.version_number)).where(LoadVersion.load_id == load_id)
        )
        or 0
    ) + 1


def _normalized_snapshot(load: Load, stops: List[LoadStop], source_status: str) -> Dict[str, Any]:
    return {
        "source_load_id": load.source_load_id,
        "display_number": load.display_number,
        "source_status": source_status,
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
                "source_sequence_value": _serialize_decimal(stop.source_sequence_value),
                "stop_type": stop.stop_type.value,
                "city": stop.city,
                "state": stop.state,
                "postal_code": stop.postal_code,
                "scheduled_date": stop.scheduled_date.isoformat()
                if stop.scheduled_date is not None
                else None,
                "source_location_id": stop.source_location_id,
                "location_name": stop.location_name,
                "actual_arrived_at": _serialize_datetime(stop.actual_arrived_at),
            }
            for stop in stops
        ],
    }


def _serialize_decimal(value: Optional[Decimal]) -> Optional[str]:
    return None if value is None else str(value)


def _serialize_datetime(value: Optional[datetime]) -> Optional[str]:
    return None if value is None else _as_utc(value).isoformat()


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest one BrokerOS sync file")
    parser.add_argument("path", type=Path, help="Path to a plain BrokerOS sync JSON file")
    parser.add_argument("--broker-source-id", required=True, help="Canonical BrokerOS source ID")
    arguments = parser.parse_args()
    try:
        with SessionLocal() as session:
            result = ingest_file(session, arguments.broker_source_id, arguments.path)
    except (BrokerOSIngestionError, OSError, SQLAlchemyError) as exc:
        parser.exit(1, f"BrokerOS ingestion failed: {exc}\n")
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
