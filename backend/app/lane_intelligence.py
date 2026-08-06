from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, Sequence

from sqlalchemy import exists, or_, select
from sqlalchemy.orm import Session

from app.lane_geography import (
    NORMALIZATION_VERSION,
    NormalizedLocation,
    normalize_location,
)
from app.load_stops import load_stops
from app.models import Load, LoadStatus, LoadStop, StopType

MIN_SUFFICIENT_HISTORY = 3
HISTORY_LOAD_LIMIT = 500
ELIGIBLE_HISTORY_STATUSES = (LoadStatus.DELIVERED, LoadStatus.COMPLETED)
TRAVEL_TIME_VERSION = "tx-metro-travel-time-v1"

# Fixed, directional planning estimates. Values are deliberately coarse and
# rounded to 15 minutes; they are not live traffic or dispatch ETAs.
_TRAVEL_TIME_MINUTES = {
    "AUSTIN>DFW": 210,
    "AUSTIN>HOUSTON": 165,
    "AUSTIN>SAN_ANTONIO": 90,
    "DFW>AUSTIN": 210,
    "DFW>HOUSTON": 255,
    "DFW>SAN_ANTONIO": 270,
    "HOUSTON>AUSTIN": 165,
    "HOUSTON>DFW": 255,
    "HOUSTON>SAN_ANTONIO": 210,
    "SAN_ANTONIO>AUSTIN": 90,
    "SAN_ANTONIO>DFW": 270,
    "SAN_ANTONIO>HOUSTON": 210,
}


class UnsupportedNormalizationVersion(ValueError):
    pass


class LaneNotDerivable(ValueError):
    pass


@dataclass(frozen=True)
class LaneEndpoint:
    location: NormalizedLocation
    sequence_number: int


@dataclass(frozen=True)
class DerivedLane:
    origin: LaneEndpoint
    destination: LaneEndpoint

    @property
    def exact_key(self) -> str:
        return f"{self.origin.location.exact_key}>{self.destination.location.exact_key}"

    @property
    def metro_key(self) -> Optional[str]:
        if not self.origin.location.metro_key or not self.destination.location.metro_key:
            return None
        return f"{self.origin.location.metro_key}>{self.destination.location.metro_key}"


@dataclass(frozen=True)
class LaneHistory:
    exact_count: int
    nearby_count: int
    equipment_exact_count: int
    equipment_nearby_count: int
    selected_scope: str
    data_sufficiency: str
    fallback_reason: Optional[str]
    history_limit: int
    history_truncated: bool


@dataclass(frozen=True)
class LaneIntelligence:
    broker_id: str
    load_id: str
    normalization_version: str
    lane: DerivedLane
    history: LaneHistory
    typical_travel_time_minutes: Optional[int]


def typical_travel_time_minutes(metro_key: Optional[str]) -> Optional[int]:
    if metro_key is None:
        return None
    return _TRAVEL_TIME_MINUTES.get(metro_key)


def validate_normalization_version(version: str) -> None:
    if version != NORMALIZATION_VERSION:
        raise UnsupportedNormalizationVersion(version)


def derive_primary_lane(stops: Sequence[LoadStop]) -> DerivedLane:
    ordered_stops = sorted(stops, key=lambda stop: stop.sequence_number)
    origin_stop = next(
        (
            stop
            for stop in ordered_stops
            if stop.stop_type in (StopType.PICKUP, StopType.PICKUP_DROPOFF)
        ),
        None,
    )
    destination_stop = next(
        (
            stop
            for stop in reversed(ordered_stops)
            if stop.stop_type in (StopType.DROPOFF, StopType.PICKUP_DROPOFF)
        ),
        None,
    )
    if origin_stop is None or destination_stop is None:
        raise LaneNotDerivable("load must have pickup and delivery stops")
    if origin_stop.sequence_number >= destination_stop.sequence_number:
        raise LaneNotDerivable("pickup and delivery stops must be distinct and ordered")

    return DerivedLane(
        origin=LaneEndpoint(
            location=normalize_location(
                origin_stop.city, origin_stop.state, origin_stop.postal_code
            ),
            sequence_number=origin_stop.sequence_number,
        ),
        destination=LaneEndpoint(
            location=normalize_location(
                destination_stop.city, destination_stop.state, destination_stop.postal_code
            ),
            sequence_number=destination_stop.sequence_number,
        ),
    )


def _history_scope(exact_count: int, nearby_count: int) -> tuple[str, str, Optional[str]]:
    if exact_count >= MIN_SUFFICIENT_HISTORY:
        return "exact", "sufficient", None
    if nearby_count >= MIN_SUFFICIENT_HISTORY:
        return (
            "nearby",
            "sufficient",
            "Exact directional history is below the sufficiency threshold",
        )
    if exact_count:
        return "exact", "thin", "Exact directional history is below the sufficiency threshold"
    if nearby_count:
        return "nearby", "thin", "No exact directional history"
    return "none", "none", "No exact or same-metro directional history"


def get_lane_intelligence(
    session: Session,
    broker_id: str,
    load_id: str,
    normalization_version: str = NORMALIZATION_VERSION,
) -> Optional[LaneIntelligence]:
    """Return broker-scoped lane history for a load.

    Returns ``None`` when the target load does not exist and raises
    ``LaneNotDerivable`` when its stops cannot define a primary lane.
    History is bounded to the most recent eligible loads for predictable MVP
    response cost.
    """
    validate_normalization_version(normalization_version)
    target = session.scalar(select(Load).where(Load.broker_id == broker_id, Load.id == load_id))
    if target is None:
        return None

    as_of = datetime.now(timezone.utc)
    future_stop_exists = exists(
        select(LoadStop.id).where(
            LoadStop.broker_id == broker_id,
            LoadStop.load_id == Load.id,
            or_(
                LoadStop.scheduled_date > as_of.date(),
                LoadStop.scheduled_start_at > as_of,
                LoadStop.scheduled_end_at > as_of,
                LoadStop.actual_arrived_at > as_of,
                LoadStop.actual_departed_at > as_of,
            ),
        )
    )
    history_loads = session.scalars(
        select(Load)
        .where(
            Load.broker_id == broker_id,
            Load.status.in_(ELIGIBLE_HISTORY_STATUSES),
            Load.id != load_id,
            Load.last_synced_at <= as_of,
            or_(Load.source_created_at.is_(None), Load.source_created_at <= as_of),
            or_(Load.source_updated_at.is_(None), Load.source_updated_at <= as_of),
            or_(Load.booked_at.is_(None), Load.booked_at <= as_of),
            ~future_stop_exists,
        )
        .order_by(Load.last_synced_at.desc(), Load.id.desc())
        .limit(HISTORY_LOAD_LIMIT + 1)
    ).all()
    history_truncated = len(history_loads) > HISTORY_LOAD_LIMIT
    history_loads = history_loads[:HISTORY_LOAD_LIMIT]
    stops_by_load = load_stops(
        session, broker_id, [target.id, *(load.id for load in history_loads)]
    )
    target_lane = derive_primary_lane(stops_by_load.get(target.id, []))

    exact_count = 0
    nearby_count = 0
    equipment_exact_count = 0
    equipment_nearby_count = 0
    for history_load in history_loads:
        try:
            history_lane = derive_primary_lane(stops_by_load.get(history_load.id, []))
        except LaneNotDerivable:
            continue
        if history_lane.exact_key == target_lane.exact_key:
            exact_count += 1
            if history_load.equipment_type == target.equipment_type:
                equipment_exact_count += 1
        elif target_lane.metro_key and history_lane.metro_key == target_lane.metro_key:
            nearby_count += 1
            if history_load.equipment_type == target.equipment_type:
                equipment_nearby_count += 1

    selected_scope, data_sufficiency, fallback_reason = _history_scope(exact_count, nearby_count)
    return LaneIntelligence(
        broker_id=broker_id,
        load_id=load_id,
        normalization_version=normalization_version,
        lane=target_lane,
        history=LaneHistory(
            exact_count=exact_count,
            nearby_count=nearby_count,
            equipment_exact_count=equipment_exact_count,
            equipment_nearby_count=equipment_nearby_count,
            selected_scope=selected_scope,
            data_sufficiency=data_sufficiency,
            fallback_reason=fallback_reason,
            history_limit=HISTORY_LOAD_LIMIT,
            history_truncated=history_truncated,
        ),
        typical_travel_time_minutes=typical_travel_time_minutes(target_lane.metro_key),
    )
