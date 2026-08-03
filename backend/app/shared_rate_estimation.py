from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.lane_geography import NORMALIZATION_VERSION
from app.lane_intelligence import derive_primary_lane
from app.load_eligibility import LoadNotEligible, LoadNotFound, require_active_uncovered
from app.load_stops import load_stops
from app.models import (
    EquipmentType,
    Load,
    LoadStop,
    SharedPoolPolicy,
    SharedPoolQueryAudit,
)
from app.observability import canonical_request_id, increment
from app.shared_carrier_pool import (
    MIN_SHARED_CONTRIBUTING_BROKERS,
    SHARED_POOL_POLICY_VERSION,
    SharedPoolDisabled,
    SharedPoolNotEligible,
    _count_bucket,
    _historical_loads,
    _load_stops_by_scope,
    _participant_scope_digest,
)

SHARED_RATE_ESTIMATION_VERSION = "shared-carrier-rate-estimation-v1"
PRIMARY_LOOKBACK_DAYS = 180
EXTENDED_LOOKBACK_DAYS = 365
MIN_RATE_SAMPLES = 3
CENT = Decimal("0.01")


@dataclass(frozen=True)
class SharedRateEstimateResult:
    broker_id: str
    load_id: str
    policy_version: str
    policy_revision: int
    estimation_version: str
    normalization_version: str
    status: str
    amount: Optional[Decimal]
    low: Optional[Decimal]
    high: Optional[Decimal]
    calculation_mode: Optional[str]
    confidence: str
    match_scope: Optional[str]
    equipment_scope: Optional[str]
    sample_count_bucket: str
    contributing_broker_count_bucket: str
    selected_tier: Optional[str]
    lookback_days: Optional[int]


@dataclass(frozen=True)
class _Observation:
    broker_id: str
    exact_key: str
    metro_key: Optional[str]
    equipment_type: EquipmentType
    amount: Decimal
    distance_miles: Optional[Decimal]
    rate_date: datetime


@dataclass(frozen=True)
class _Tier:
    code: str
    lane_scope: str
    equipment_scope: str


TIERS = (
    _Tier("exact_lane_equipment", "exact", "equipment"),
    _Tier("metro_lane_equipment", "metro", "equipment"),
    _Tier("exact_lane_any_equipment", "exact", "any_known"),
    _Tier("metro_lane_any_equipment", "metro", "any_known"),
)


def get_shared_rate_estimate(
    session: Session,
    broker_id: str,
    load_id: str,
    normalization_version: str = NORMALIZATION_VERSION,
    actor_subject: str = "system",
    request_id: Optional[str] = None,
) -> Optional[SharedRateEstimateResult]:
    request_id = canonical_request_id(request_id)
    if normalization_version != NORMALIZATION_VERSION:
        raise ValueError(f"unsupported normalization version: {normalization_version}")
    requester_policy = _enabled_policy(session, broker_id)
    try:
        target = require_active_uncovered(session, broker_id, load_id)
    except LoadNotFound:
        return None
    except LoadNotEligible as exc:
        raise SharedPoolNotEligible(str(exc)) from exc
    target_stops = load_stops(session, broker_id, [target.id]).get(target.id, [])
    try:
        target_lane = derive_primary_lane(target_stops)
    except ValueError as exc:
        raise SharedPoolNotEligible(str(exc)) from exc
    policies = session.scalars(
        select(SharedPoolPolicy)
        .where(SharedPoolPolicy.enabled.is_(True))
        .order_by(SharedPoolPolicy.broker_id)
    ).all()
    participant_ids = [policy.broker_id for policy in policies]
    scope_digest = _participant_scope_digest(policies)
    historical_loads = _historical_loads(session, participant_ids, _as_utc(target.last_synced_at))
    stops_by_load = _load_stops_by_scope(
        session,
        participant_ids,
        [load.id for load in historical_loads],
    )
    observations = [
        item
        for item in _observations(historical_loads, stops_by_load)
        if item.rate_date <= _as_utc(target.last_synced_at)
    ]
    selected = None
    for lookback_days in (PRIMARY_LOOKBACK_DAYS, EXTENDED_LOOKBACK_DAYS):
        cutoff = _as_utc(target.last_synced_at) - timedelta(days=lookback_days)
        recent = [item for item in observations if item.rate_date >= cutoff]
        for tier in TIERS:
            matched = [
                item
                for item in recent
                if _matches(
                    tier, item, target_lane.exact_key, target_lane.metro_key, target.equipment_type
                )
            ]
            usable, mode = _usable(matched, tier, target.distance_miles)
            broker_count = len({item.broker_id for item in usable})
            if len(usable) < MIN_RATE_SAMPLES or broker_count < MIN_SHARED_CONTRIBUTING_BROKERS:
                continue
            selected = (tier, lookback_days, usable, mode, broker_count)
            break
        if selected is not None:
            break

    if selected is None:
        result = SharedRateEstimateResult(
            broker_id=broker_id,
            load_id=load_id,
            policy_version=SHARED_POOL_POLICY_VERSION,
            policy_revision=requester_policy.policy_revision,
            estimation_version=SHARED_RATE_ESTIMATION_VERSION,
            normalization_version=normalization_version,
            status="unavailable",
            amount=None,
            low=None,
            high=None,
            calculation_mode=None,
            confidence="none",
            match_scope=None,
            equipment_scope=None,
            sample_count_bucket="0",
            contributing_broker_count_bucket="0",
            selected_tier=None,
            lookback_days=None,
        )
    else:
        tier, lookback_days, usable, mode, broker_count = selected
        values = (
            [
                item.amount / item.distance_miles
                for item in usable
                if item.distance_miles is not None and item.distance_miles > 0
            ]
            if mode == "rate_per_mile"
            else [item.amount for item in usable]
        )
        central, low, high = (
            _percentile(values, fraction)
            for fraction in (Decimal(".5"), Decimal(".25"), Decimal(".75"))
        )
        if mode == "rate_per_mile":
            if target.distance_miles is None:
                raise SharedPoolNotEligible("rate-per-mile estimate requires target distance")
            amounts = tuple(_money(value * target.distance_miles) for value in (central, low, high))
        else:
            amounts = tuple(_money(value) for value in (central, low, high))
        result = SharedRateEstimateResult(
            broker_id=broker_id,
            load_id=load_id,
            policy_version=SHARED_POOL_POLICY_VERSION,
            policy_revision=requester_policy.policy_revision,
            estimation_version=SHARED_RATE_ESTIMATION_VERSION,
            normalization_version=normalization_version,
            status="estimated",
            amount=amounts[0],
            low=amounts[1],
            high=amounts[2],
            calculation_mode="median_rate_per_mile"
            if mode == "rate_per_mile"
            else "median_all_in_total",
            confidence="high"
            if tier.code == "exact_lane_equipment" and len(usable) >= 10
            else "medium",
            match_scope=tier.lane_scope,
            equipment_scope=tier.equipment_scope,
            sample_count_bucket=_count_bucket(len(usable)),
            contributing_broker_count_bucket=_count_bucket(broker_count),
            selected_tier=tier.code,
            lookback_days=lookback_days,
        )

    session.add(
        SharedPoolQueryAudit(
            broker_id=broker_id,
            load_id=load_id,
            query_type="rate_estimate",
            policy_version=SHARED_POOL_POLICY_VERSION,
            policy_revision=requester_policy.policy_revision,
            scoring_version=SHARED_RATE_ESTIMATION_VERSION,
            normalization_version=normalization_version,
            participant_scope_digest=scope_digest,
            participant_count=len(participant_ids),
            result_count=1 if result.status == "estimated" else 0,
            actor_subject=actor_subject,
            request_id=request_id,
            created_at=datetime.now(timezone.utc),
        )
    )
    session.commit()
    return result


def _enabled_policy(session: Session, broker_id: str) -> SharedPoolPolicy:
    policy = session.scalar(
        select(SharedPoolPolicy).where(
            SharedPoolPolicy.broker_id == broker_id,
            SharedPoolPolicy.enabled.is_(True),
        )
    )
    if policy is None:
        raise SharedPoolDisabled("requesting broker has not opted into the shared pool")
    return policy


def _observations(
    loads: Sequence[Load],
    stops_by_load: dict[tuple[str, str], list[LoadStop]],
) -> list[_Observation]:
    observations: list[_Observation] = []
    for load in loads:
        if load.carrier_rate is None or load.carrier_rate <= 0:
            continue
        try:
            lane = derive_primary_lane(stops_by_load.get((load.broker_id, load.id), []))
        except ValueError:
            increment("carrier_pool_skipped_observations_total", {"reason": "lane_not_derivable"})
            continue
        observations.append(
            _Observation(
                broker_id=load.broker_id,
                exact_key=lane.exact_key,
                metro_key=lane.metro_key,
                equipment_type=load.equipment_type,
                amount=load.carrier_rate,
                distance_miles=load.distance_miles,
                rate_date=_as_utc(load.booked_at or load.source_updated_at or load.last_synced_at),
            )
        )
    return observations


def _matches(
    tier: _Tier,
    item: _Observation,
    target_exact: str,
    target_metro: Optional[str],
    target_equipment: EquipmentType,
) -> bool:
    if tier.lane_scope == "exact" and item.exact_key != target_exact:
        return False
    if tier.lane_scope == "metro" and (target_metro is None or item.metro_key != target_metro):
        return False
    if tier.equipment_scope == "equipment" and item.equipment_type != target_equipment:
        return False
    if tier.equipment_scope == "any_known" and item.equipment_type == EquipmentType.UNKNOWN:
        return False
    return True


def _usable(
    observations: Sequence[_Observation],
    tier: _Tier,
    target_distance: Optional[Decimal],
) -> tuple[list[_Observation], str]:
    if target_distance is not None and target_distance > 0:
        return [
            item for item in observations if item.distance_miles and item.distance_miles > 0
        ], "rate_per_mile"
    return (
        (list(observations), "raw_total") if tier.lane_scope == "exact" else ([], "rate_per_mile")
    )


def _percentile(values: Sequence[Decimal], fraction: Decimal) -> Decimal:
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
