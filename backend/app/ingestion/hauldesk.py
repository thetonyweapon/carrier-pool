import argparse
import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Union
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.ingestion.common import (
    CarrierIdentityConflictError,
    IngestionLimitError,
    enforce_ingestion_file_size,
    enforce_ingestion_limits,
    ingestion_transaction,
    read_verified_file,
    upsert_carrier_identity,
    validate_carrier_identity_transition,
)
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
    RateLineItem,
    RateSide,
    StopType,
    TmsType,
    validate_currency,
)

CENTRAL = ZoneInfo("America/Chicago")
KG_TO_LB = Decimal("2.2046226218487757")
KM_TO_MILE = Decimal("0.621371192237334")
UNIT_SCALE = Decimal("0.1")
MAX_WEIGHT_LBS = Decimal("99999999999.9")
MAX_DISTANCE_MILES = Decimal("999999999.9")
RATE_CODES = {"LINEHAUL", "FUEL", "ACCESSORIAL", "ADJUSTMENT"}


class HaulDeskIngestionError(Exception):
    """Base exception for HaulDesk ingestion errors."""


class ConflictingHaulDeskFileError(HaulDeskIngestionError):
    """A filename was already ingested with different content."""


class OutOfOrderHaulDeskFileError(HaulDeskIngestionError):
    """A source file is not later than the latest successful sync."""


class InvalidHaulDeskPayloadError(HaulDeskIngestionError):
    """The source payload cannot be normalized safely."""


class HaulDeskModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class HaulDeskLoad(HaulDeskModel):
    load_num: str
    status_code: int
    customer_code: str
    customer_name: str
    carrier_ref: Optional[Union[str, int]] = None
    equip: str
    weight_kg: Decimal
    dist_km: Decimal
    pu_city: str
    pu_state: str
    pu_zip: str
    pu_date: str
    pu_departed_at: Optional[str] = None
    del_city: str
    del_state: str
    del_zip: str
    del_date: str
    del_arrived_at: Optional[str] = None
    entered_at: str
    updated_at: str


class HaulDeskCarrier(HaulDeskModel):
    carrier_id: Union[str, int]
    carrier_name: str
    mc_no: Optional[str] = None
    dot_no: Optional[str] = None
    home_city: Optional[str] = None
    home_state: Optional[str] = None
    phone: Optional[str] = None


class HaulDeskRate(HaulDeskModel):
    rate_id: Union[str, int]
    load_num: str
    side: str
    code: str
    amount_usd: Decimal
    created_at: str


class HaulDeskSync(HaulDeskModel):
    synced_at: str
    loads: List[HaulDeskLoad]
    carriers: List[HaulDeskCarrier]
    rates: List[HaulDeskRate]


@dataclass(frozen=True)
class IngestionResult:
    filename: str
    processed_loads: int
    duplicate: bool


STATUS_MAP = {
    10: LoadStatus.PLANNED,
    20: LoadStatus.ACTIVE,
    30: LoadStatus.COVERED,
    40: LoadStatus.IN_TRANSIT,
    50: LoadStatus.DELIVERED,
    90: LoadStatus.COMPLETED,
}
BOOKED_STATUSES = {
    LoadStatus.COVERED,
    LoadStatus.IN_TRANSIT,
    LoadStatus.DELIVERED,
    LoadStatus.COMPLETED,
}


def ingest_file(session: Session, broker_source_id: str, path: Path) -> IngestionResult:
    try:
        enforce_ingestion_file_size(path)
    except IngestionLimitError as exc:
        raise InvalidHaulDeskPayloadError("Invalid HaulDesk sync payload") from exc
    return ingest_contents(session, broker_source_id, path.name, read_verified_file(path))


def ingest_contents(
    session: Session,
    broker_source_id: str,
    filename: str,
    raw_contents: bytes,
    before_commit: Optional[Callable[[Session], None]] = None,
) -> IngestionResult:
    raw_payload, sync = _parse_payload(raw_contents)
    synced_at = _parse_central_datetime(sync.synced_at, "synced_at")
    checksum = hashlib.sha256(raw_contents).hexdigest()

    try:
        with ingestion_transaction(session, "hauldesk"):
            source = session.scalar(
                select(BrokerSource).where(BrokerSource.id == broker_source_id).with_for_update()
            )
            if source is None:
                raise HaulDeskIngestionError(f"Unknown broker source: {broker_source_id}")
            if source.tms_type != TmsType.HAULDESK:
                raise HaulDeskIngestionError("Broker source is not configured for HaulDesk")

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
                raise ConflictingHaulDeskFileError(
                    f"Source file {filename} was already recorded with different content or status"
                )

            latest_synced_at = session.scalar(
                select(func.max(IngestionFile.synced_at)).where(
                    IngestionFile.broker_source_id == source.id,
                    IngestionFile.status == IngestionStatus.SUCCEEDED,
                )
            )
            if latest_synced_at is not None and synced_at <= _as_utc(latest_synced_at):
                raise OutOfOrderHaulDeskFileError(
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

            carrier_by_id = {}
            for source_carrier in sync.carriers:
                carrier_id = str(source_carrier.carrier_id)
                if carrier_id in carrier_by_id:
                    raise InvalidHaulDeskPayloadError(
                        f"Duplicate HaulDesk carrier_id in file: {carrier_id}"
                    )
                try:
                    carrier_by_id[carrier_id] = _upsert_carrier(
                        session, source, source_carrier, synced_at
                    )
                except CarrierIdentityConflictError as exc:
                    raise InvalidHaulDeskPayloadError(str(exc)) from exc
            raw_loads = {str(load["load_num"]): load for load in raw_payload["loads"]}
            raw_rates = [dict(rate) for rate in raw_payload["rates"]]
            affected: Dict[str, Dict[str, Any]] = {}
            loads_by_source_id: Dict[str, Load] = {}
            for source_load in sync.loads:
                source_load_id = str(source_load.load_num)
                if source_load_id in loads_by_source_id:
                    raise InvalidHaulDeskPayloadError(
                        f"Duplicate HaulDesk load_num in file: {source_load_id}"
                    )
                raw_load = raw_loads[str(source_load.load_num)]
                load = _upsert_load(
                    session,
                    source,
                    ingestion_file,
                    source_load,
                    carrier_by_id,
                    source_carrier_ids={str(item.carrier_id) for item in sync.carriers},
                )
                loads_by_source_id[str(source_load.load_num)] = load
                affected[load.id] = {"load": raw_load, "rates": []}

            seen_rate_ids = set()
            for source_rate, raw_rate in zip(sync.rates, raw_rates):
                rate_id = str(source_rate.rate_id)
                load = loads_by_source_id.get(str(source_rate.load_num))
                if load is None:
                    load = session.scalar(
                        select(Load).where(
                            Load.broker_source_id == source.id,
                            Load.source_load_id == str(source_rate.load_num),
                        )
                    )
                if load is None:
                    raise InvalidHaulDeskPayloadError(
                        f"Rate {rate_id} references unknown load {source_rate.load_num}"
                    )
                if rate_id in seen_rate_ids:
                    raise InvalidHaulDeskPayloadError(
                        f"Duplicate HaulDesk rate_id in file: {rate_id}"
                    )
                seen_rate_ids.add(rate_id)
                existing_rate = session.scalar(
                    select(RateLineItem).where(
                        RateLineItem.broker_source_id == source.id,
                        RateLineItem.source_rate_id == rate_id,
                    )
                )
                if existing_rate is not None:
                    raise InvalidHaulDeskPayloadError(
                        f"HaulDesk rate_id was already ingested: {rate_id}"
                    )

                side = _map_rate_side(source_rate.side)
                code = _validate_rate_code(source_rate.code)
                amount = _validate_source_currency(source_rate.amount_usd, "amount_usd")
                source_created_at = _parse_central_datetime(source_rate.created_at, "created_at")
                session.add(
                    RateLineItem(
                        broker_id=source.broker_id,
                        broker_source_id=source.id,
                        load_id=load.id,
                        source_rate_id=rate_id,
                        side=side,
                        code=code,
                        amount=amount,
                        source_created_at=source_created_at,
                        ingested_at=synced_at,
                    )
                )
                affected.setdefault(load.id, {"load": None, "rates": []})["rates"].append(raw_rate)

            session.flush()
            for load_id, change in affected.items():
                load = session.get(Load, load_id)
                if change["rates"]:
                    _refresh_load_rates(session, source, load)
                    if change["load"] is None:
                        load.last_synced_at = synced_at
                stops = session.scalars(
                    select(LoadStop)
                    .where(LoadStop.broker_id == source.broker_id, LoadStop.load_id == load.id)
                    .order_by(LoadStop.sequence_number)
                ).all()
                session.add(
                    LoadVersion(
                        broker_id=source.broker_id,
                        broker_source_id=source.id,
                        load_id=load.id,
                        ingestion_file_id=ingestion_file.id,
                        version_number=_next_version_number(session, load.id),
                        observed_at=synced_at,
                        raw_payload={"load": change["load"], "rates": change["rates"]},
                        normalized_snapshot=_normalized_snapshot(load, stops, change["load"]),
                    )
                )

            if before_commit is not None:
                before_commit(session)
            ingestion_file.status = IngestionStatus.SUCCEEDED
            ingestion_file.processed_at = datetime.now(timezone.utc)
    except IntegrityError as exc:
        raise HaulDeskIngestionError(
            "HaulDesk ingestion violated a database constraint; retry if another sync is running"
        ) from exc

    return IngestionResult(filename=filename, processed_loads=len(sync.loads), duplicate=False)


def _parse_payload(raw_contents: bytes) -> Tuple[dict, HaulDeskSync]:
    try:
        raw_payload = json.loads(raw_contents)
        enforce_ingestion_limits(raw_contents, raw_payload)
        validation_payload = json.loads(raw_contents, parse_float=Decimal)
        return raw_payload, HaulDeskSync.model_validate(validation_payload)
    except (UnicodeDecodeError, json.JSONDecodeError, ValidationError, IngestionLimitError) as exc:
        raise InvalidHaulDeskPayloadError("Invalid HaulDesk sync payload") from exc


def _upsert_carrier(
    session: Session,
    source: BrokerSource,
    source_carrier: HaulDeskCarrier,
    observed_at: datetime,
) -> Carrier:
    source_carrier_id = str(source_carrier.carrier_id)
    carrier = session.scalar(
        select(Carrier).where(
            Carrier.broker_source_id == source.id,
            Carrier.source_carrier_id == source_carrier_id,
        )
    )
    validate_carrier_identity_transition(carrier, source_carrier.mc_no, source_carrier.dot_no)
    carrier_identity = upsert_carrier_identity(
        session,
        source.broker_id,
        source_carrier.mc_no,
        source_carrier.dot_no,
        observed_at,
    )
    identity_id = (
        carrier_identity.id
        if carrier_identity
        else (carrier.carrier_identity_id if carrier else None)
    )
    values = {
        "carrier_identity_id": identity_id,
        "name": source_carrier.carrier_name,
        "mc_number": source_carrier.mc_no or (carrier.mc_number if carrier else None),
        "dot_number": source_carrier.dot_no or (carrier.dot_number if carrier else None),
        "phone_number": source_carrier.phone,
        "home_city": source_carrier.home_city,
        "home_state": source_carrier.home_state,
    }
    if carrier is None:
        carrier = Carrier(
            broker_id=source.broker_id,
            broker_source_id=source.id,
            source_carrier_id=source_carrier_id,
            created_at=observed_at,
            updated_at=observed_at,
            **values,
        )
        session.add(carrier)
    else:
        changed = any(getattr(carrier, key) != value for key, value in values.items())
        if changed:
            for key, value in values.items():
                setattr(carrier, key, value)
            carrier.updated_at = observed_at
    session.flush()
    return carrier


def _upsert_customer(
    session: Session,
    source: BrokerSource,
    source_load: HaulDeskLoad,
    observed_at: datetime,
) -> Customer:
    source_customer_id = str(source_load.customer_code)
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
            name=source_load.customer_name,
            created_at=observed_at,
            updated_at=observed_at,
        )
        session.add(customer)
    elif customer.name != source_load.customer_name:
        customer.name = source_load.customer_name
        customer.updated_at = observed_at
    session.flush()
    return customer


def _upsert_load(
    session: Session,
    source: BrokerSource,
    ingestion_file: IngestionFile,
    source_load: HaulDeskLoad,
    carriers: Dict[str, Carrier],
    source_carrier_ids: set[str],
) -> Load:
    observed_at = ingestion_file.synced_at
    source_created_at = _parse_central_datetime(source_load.entered_at, "entered_at")
    source_updated_at = _parse_central_datetime(source_load.updated_at, "updated_at")
    source_load_id = str(source_load.load_num)
    load = session.scalar(
        select(Load).where(
            Load.broker_source_id == source.id,
            Load.source_load_id == source_load_id,
        )
    )
    status = _map_status(source_load.status_code)
    equipment_type = _map_equipment(source_load.equip)
    weight_lbs = _convert_unit(source_load.weight_kg, KG_TO_LB, "weight_kg", MAX_WEIGHT_LBS)
    distance_miles = _convert_unit(source_load.dist_km, KM_TO_MILE, "dist_km", MAX_DISTANCE_MILES)
    if source_load.carrier_ref is not None:
        carrier_id = str(source_load.carrier_ref)
        if (
            carrier_id not in source_carrier_ids
            and session.scalar(
                select(Carrier).where(
                    Carrier.broker_source_id == source.id,
                    Carrier.source_carrier_id == carrier_id,
                )
            )
            is None
        ):
            raise InvalidHaulDeskPayloadError(
                f"Load {source_load.load_num} references unknown carrier {source_load.carrier_ref}"
            )
    customer = _upsert_customer(session, source, source_load, observed_at)
    carrier = None
    if source_load.carrier_ref is not None:
        carrier = carriers.get(str(source_load.carrier_ref))
        if carrier is None:
            carrier = session.scalar(
                select(Carrier).where(
                    Carrier.broker_source_id == source.id,
                    Carrier.source_carrier_id == str(source_load.carrier_ref),
                )
            )
        if carrier is None:
            raise InvalidHaulDeskPayloadError(
                f"Load {source_load.load_num} references unknown carrier {source_load.carrier_ref}"
            )
    if load is None:
        load = Load(
            broker_id=source.broker_id,
            broker_source_id=source.id,
            source_load_id=source_load_id,
            display_number=source_load_id,
            status=status,
            customer_id=customer.id,
            carrier_id=carrier.id if carrier else None,
            equipment_type=equipment_type,
            weight_lbs=weight_lbs,
            distance_miles=distance_miles,
            source_created_at=source_created_at,
            source_updated_at=source_updated_at,
            first_seen_at=observed_at,
            last_synced_at=observed_at,
        )
        session.add(load)
    else:
        load.status = status
        load.customer_id = customer.id
        load.carrier_id = carrier.id if carrier else None
        load.equipment_type = equipment_type
        load.weight_lbs = weight_lbs
        load.distance_miles = distance_miles
        load.source_created_at = source_created_at
        load.source_updated_at = source_updated_at
        load.last_synced_at = observed_at

    if load.booked_at is None and (carrier is not None or status in BOOKED_STATUSES):
        # HaulDesk has no booking event timestamp; updated_at is the closest source observation.
        load.booked_at = source_updated_at
    session.flush()
    _sync_stops(session, source, load, source_load)
    return load


def _sync_stops(
    session: Session,
    source: BrokerSource,
    load: Load,
    source_load: HaulDeskLoad,
) -> List[LoadStop]:
    desired_stops = _build_stops(load, source_load)
    existing_stops = {
        stop.sequence_number: stop
        for stop in session.scalars(
            select(LoadStop)
            .where(LoadStop.broker_id == source.broker_id, LoadStop.load_id == load.id)
            .order_by(LoadStop.sequence_number)
        )
    }
    synchronized = []
    for desired in desired_stops:
        existing = existing_stops.pop(desired.sequence_number, None)
        if existing is None:
            session.add(desired)
            synchronized.append(desired)
            continue
        for field in (
            "stop_type",
            "city",
            "state",
            "postal_code",
            "scheduled_start_at",
            "scheduled_end_at",
            "actual_arrived_at",
            "actual_departed_at",
        ):
            setattr(existing, field, getattr(desired, field))
        synchronized.append(existing)
    for removed in existing_stops.values():
        session.delete(removed)
    session.flush()
    return synchronized


def _build_stops(load: Load, source_load: HaulDeskLoad) -> List[LoadStop]:
    return [
        LoadStop(
            broker_id=load.broker_id,
            load_id=load.id,
            sequence_number=1,
            stop_type=StopType.PICKUP,
            city=source_load.pu_city,
            state=source_load.pu_state,
            postal_code=source_load.pu_zip,
            scheduled_start_at=_parse_central_date(source_load.pu_date, "pu_date"),
            actual_departed_at=(
                _parse_central_datetime(source_load.pu_departed_at, "pu_departed_at")
                if source_load.pu_departed_at
                else None
            ),
        ),
        LoadStop(
            broker_id=load.broker_id,
            load_id=load.id,
            sequence_number=2,
            stop_type=StopType.DROPOFF,
            city=source_load.del_city,
            state=source_load.del_state,
            postal_code=source_load.del_zip,
            scheduled_start_at=_parse_central_date(source_load.del_date, "del_date"),
            actual_arrived_at=(
                _parse_central_datetime(source_load.del_arrived_at, "del_arrived_at")
                if source_load.del_arrived_at
                else None
            ),
        ),
    ]


def _refresh_load_rates(session: Session, source: BrokerSource, load: Load) -> None:
    load.customer_rate = _sum_rate_side(session, source, load, RateSide.BILL)
    load.carrier_rate = _sum_rate_side(session, source, load, RateSide.PAY)


def _sum_rate_side(
    session: Session, source: BrokerSource, load: Load, side: RateSide
) -> Optional[Decimal]:
    return session.scalar(
        select(func.sum(RateLineItem.amount)).where(
            RateLineItem.broker_source_id == source.id,
            RateLineItem.load_id == load.id,
            RateLineItem.side == side,
        )
    )


def _next_version_number(session: Session, load_id: str) -> int:
    return (
        session.scalar(
            select(func.max(LoadVersion.version_number)).where(LoadVersion.load_id == load_id)
        )
        or 0
    ) + 1


def _normalized_snapshot(
    load: Load, stops: List[LoadStop], raw_load: Optional[dict]
) -> Dict[str, Any]:
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
        "planned_pickup_date": raw_load.get("pu_date") if raw_load else None,
        "planned_delivery_date": raw_load.get("del_date") if raw_load else None,
        "stops": [
            {
                "sequence_number": stop.sequence_number,
                "stop_type": stop.stop_type.value,
                "city": stop.city,
                "state": stop.state,
                "postal_code": stop.postal_code,
                "scheduled_start_at": _serialize_datetime(stop.scheduled_start_at),
                "scheduled_end_at": _serialize_datetime(stop.scheduled_end_at),
                "actual_arrived_at": _serialize_datetime(stop.actual_arrived_at),
                "actual_departed_at": _serialize_datetime(stop.actual_departed_at),
            }
            for stop in stops
        ],
    }


def _map_status(status_code: int) -> LoadStatus:
    try:
        return STATUS_MAP[status_code]
    except KeyError as exc:
        raise InvalidHaulDeskPayloadError(
            f"Unsupported HaulDesk status_code: {status_code}"
        ) from exc


def _map_equipment(equip: str) -> EquipmentType:
    return {
        "V": EquipmentType.DRY_VAN,
        "R": EquipmentType.REEFER,
        "F": EquipmentType.FLATBED,
    }.get(equip.upper(), EquipmentType.UNKNOWN)


def _map_rate_side(side: str) -> RateSide:
    try:
        return RateSide(side.lower())
    except ValueError as exc:
        raise InvalidHaulDeskPayloadError(f"Unsupported HaulDesk rate side: {side}") from exc


def _validate_rate_code(code: str) -> str:
    if code not in RATE_CODES:
        raise InvalidHaulDeskPayloadError(f"Unsupported HaulDesk rate code: {code}")
    return code


def _validate_source_currency(value: Decimal, field_name: str) -> Decimal:
    try:
        validated = validate_currency(value)
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise InvalidHaulDeskPayloadError(
            f"{field_name} must be a Decimal value with no fractions of a cent"
        ) from exc
    if validated is None:
        raise InvalidHaulDeskPayloadError(f"{field_name} must not be null")
    return validated


def _convert_unit(
    value: Decimal, multiplier: Decimal, field_name: str, maximum: Decimal
) -> Decimal:
    if not value.is_finite() or value < 0:
        raise InvalidHaulDeskPayloadError(f"{field_name} must be finite and non-negative")
    try:
        converted = (value * multiplier).quantize(UNIT_SCALE, rounding=ROUND_HALF_UP)
    except InvalidOperation as exc:
        raise InvalidHaulDeskPayloadError(f"{field_name} is outside the supported range") from exc
    if converted > maximum:
        raise InvalidHaulDeskPayloadError(f"{field_name} is outside the supported range")
    return converted


def _localize_central(naive: datetime, field_name: str) -> datetime:
    candidates = []
    for fold in (0, 1):
        aware = naive.replace(tzinfo=CENTRAL, fold=fold)
        utc_value = aware.astimezone(timezone.utc)
        if utc_value.astimezone(CENTRAL).replace(tzinfo=None) == naive:
            if utc_value not in candidates:
                candidates.append(utc_value)
    if len(candidates) != 1:
        raise InvalidHaulDeskPayloadError(
            f"{field_name} is ambiguous or nonexistent in America/Chicago"
        )
    return candidates[0]


def _parse_central_datetime(value: str, field_name: str) -> datetime:
    try:
        naive = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError) as exc:
        raise InvalidHaulDeskPayloadError(
            f"{field_name} must use YYYY-MM-DD HH:MM:SS Central time"
        ) from exc
    return _localize_central(naive, field_name)


def _parse_central_date(value: str, field_name: str) -> datetime:
    try:
        parsed_date = date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise InvalidHaulDeskPayloadError(f"{field_name} must use YYYY-MM-DD") from exc
    return _localize_central(datetime.combine(parsed_date, time.min), field_name)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _serialize_decimal(value: Optional[Decimal]) -> Optional[str]:
    return None if value is None else str(value)


def _serialize_datetime(value: Optional[datetime]) -> Optional[str]:
    return None if value is None else _as_utc(value).isoformat()


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest one HaulDesk sync file")
    parser.add_argument("path", type=Path, help="Path to a plain HaulDesk sync JSON file")
    parser.add_argument("--broker-source-id", required=True, help="Canonical HaulDesk source ID")
    arguments = parser.parse_args()
    try:
        with SessionLocal() as session:
            result = ingest_file(session, arguments.broker_source_id, arguments.path)
    except (HaulDeskIngestionError, OSError, SQLAlchemyError) as exc:
        parser.exit(1, f"HaulDesk ingestion failed: {exc}\n")
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
