from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional, Sequence

from sqlalchemy import and_, exists, select
from sqlalchemy.orm import Session

from app.lane_geography import NORMALIZATION_VERSION
from app.lane_intelligence import (
    HISTORY_LOAD_LIMIT,
    LaneNotDerivable,
    derive_primary_lane,
    validate_normalization_version,
)
from app.load_stops import load_stops
from app.models import (
    BrokerSource,
    EquipmentType,
    Load,
    LoadStatus,
    LoadStop,
    PlatformAssignment,
    TmsType,
)

ESTIMATION_VERSION = "carrier-rate-estimation-v1"
RATE_CORRECTION_POLICY = "one_current_effective_total_per_load"
HISTORY_STATUSES = (LoadStatus.COMPLETED,)
PRIMARY_LOOKBACK_DAYS = 180
EXTENDED_LOOKBACK_DAYS = 365
MIN_EXACT_SAMPLES = 3
MIN_BROAD_SAMPLES = 5
CENT = Decimal("0.01")


class UnsupportedEstimationVersion(ValueError):
    pass


class RateEstimationNotEligible(ValueError):
    pass


@dataclass(frozen=True)
class RateObservation:
    load_id: str
    exact_key: str
    metro_key: Optional[str]
    equipment_type: EquipmentType
    carrier_pay: Decimal
    distance_miles: Optional[Decimal]
    rate_date: datetime
    source_type: TmsType


@dataclass(frozen=True)
class EstimateTierAttempt:
    tier: str
    lookback_days: int
    sample_size: int
    minimum_required: int
    reason: str


@dataclass(frozen=True)
class RateEstimateResult:
    status: str
    broker_id: str
    load_id: str
    data_as_of: datetime
    currency: str
    estimate_amount: Optional[Decimal]
    low_amount: Optional[Decimal]
    high_amount: Optional[Decimal]
    calculation_mode: Optional[str]
    range_method: Optional[str]
    confidence_level: str
    data_sufficiency: str
    confidence_reasons: tuple[str, ...]
    selected_tier: Optional[str]
    lane_scope: Optional[str]
    equipment_scope: Optional[str]
    lookback_days: Optional[int]
    sample_size: int
    candidate_count_before_exclusions: int
    excluded_counts: dict[str, int]
    source_types: tuple[str, ...]
    oldest_rate_date: Optional[datetime]
    newest_rate_date: Optional[datetime]
    attempted_tiers: tuple[EstimateTierAttempt, ...]
    target_lane_exact_key: str
    target_lane_metro_key: Optional[str]
    target_equipment_type: EquipmentType
    target_distance_miles: Optional[Decimal]
    estimation_version: str
    normalization_version: str
    historical_statuses: tuple[LoadStatus, ...]


@dataclass(frozen=True)
class _Tier:
    code: str
    lane_scope: str
    equipment_scope: str
    minimum_required: int


TIERS = (
    _Tier("exact_lane_equipment", "exact", "equipment", MIN_EXACT_SAMPLES),
    _Tier("metro_lane_equipment", "metro", "equipment", MIN_EXACT_SAMPLES),
    _Tier("exact_lane_any_equipment", "exact", "any_known", MIN_EXACT_SAMPLES),
    _Tier("metro_lane_any_equipment", "metro", "any_known", MIN_EXACT_SAMPLES),
    _Tier("broker_equipment", "broker", "equipment", MIN_EXACT_SAMPLES),
    _Tier("broker_any_equipment", "broker", "any_known", MIN_BROAD_SAMPLES),
)


def validate_estimation_version(version: str) -> None:
    if version != ESTIMATION_VERSION:
        raise UnsupportedEstimationVersion(version)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _rate_date(load: Load) -> datetime:
    return _as_utc(load.booked_at or load.source_updated_at or load.last_synced_at)


def _money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def _percentile(values: Sequence[Decimal], fraction: Decimal) -> Decimal:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("percentile requires at least one value")
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * fraction
    lower_index = int(position)
    upper_index = min(lower_index + 1, len(ordered) - 1)
    remainder = position - lower_index
    return ordered[lower_index] + (ordered[upper_index] - ordered[lower_index]) * remainder


def _tier_matches(
    tier: _Tier,
    observation: RateObservation,
    target_lane_exact_key: str,
    target_lane_metro_key: Optional[str],
    target_equipment: EquipmentType,
) -> bool:
    if tier.lane_scope == "exact" and observation.exact_key != target_lane_exact_key:
        return False
    if tier.lane_scope == "metro" and (
        target_lane_metro_key is None or observation.metro_key != target_lane_metro_key
    ):
        return False
    if tier.equipment_scope == "equipment" and (
        target_equipment == EquipmentType.UNKNOWN or observation.equipment_type != target_equipment
    ):
        return False
    if tier.equipment_scope == "any_known" and observation.equipment_type == EquipmentType.UNKNOWN:
        return False
    return True


def _usable_observations(
    observations: Sequence[RateObservation],
    tier: _Tier,
    target_distance_miles: Optional[Decimal],
) -> tuple[list[RateObservation], str]:
    if target_distance_miles is not None and target_distance_miles > 0:
        usable = [
            observation
            for observation in observations
            if observation.distance_miles is not None and observation.distance_miles > 0
        ]
        return usable, "rate_per_mile"
    if tier.lane_scope == "exact":
        return list(observations), "raw_total"
    return [], "rate_per_mile"


def _confidence(
    tier: _Tier, sample_size: int, lookback_days: int, target_equipment: EquipmentType
) -> str:
    if (
        tier.code == "exact_lane_equipment"
        and sample_size >= 10
        and lookback_days == PRIMARY_LOOKBACK_DAYS
    ):
        return "high"
    if (
        tier.code in {"exact_lane_equipment", "metro_lane_equipment"}
        and sample_size >= 8
        and lookback_days == PRIMARY_LOOKBACK_DAYS
        and target_equipment != EquipmentType.UNKNOWN
    ):
        return "medium"
    return "low"


def _confidence_reasons(
    tier: _Tier, sample_size: int, lookback_days: int, target_equipment: EquipmentType
) -> tuple[str, ...]:
    reasons: list[str] = []
    if tier.lane_scope != "exact":
        reasons.append("Used broader-than-exact directional lane history")
    if tier.equipment_scope != "equipment":
        reasons.append("Used history across known equipment types")
    if sample_size < 8:
        reasons.append("Selected population met the minimum sample threshold only")
    if lookback_days == EXTENDED_LOOKBACK_DAYS:
        reasons.append("Extended the lookback window to 365 days")
    if target_equipment == EquipmentType.UNKNOWN:
        reasons.append("Target equipment is unknown")
    return tuple(reasons) or ("Used recent exact-lane and equipment history",)


def _load_observations(
    session: Session,
    broker_id: str,
    target_load_id: str,
    as_of: datetime,
) -> tuple[list[tuple[Load, BrokerSource]], int]:
    rows = session.execute(
        select(Load, BrokerSource)
        .join(
            BrokerSource,
            and_(
                BrokerSource.id == Load.broker_source_id,
                BrokerSource.broker_id == Load.broker_id,
            ),
        )
        .where(
            Load.broker_id == broker_id,
            Load.id != target_load_id,
            Load.status.in_(HISTORY_STATUSES),
            Load.carrier_id.is_not(None),
            Load.last_synced_at <= as_of,
        )
        .order_by(Load.last_synced_at.desc(), Load.id.desc())
        .limit(HISTORY_LOAD_LIMIT)
    ).all()
    return list(rows), len(rows)


def _build_observations(
    session: Session,
    broker_id: str,
    rows: Sequence[tuple[Load, BrokerSource]],
    as_of: datetime,
    stops_by_load: Optional[dict[str, list[LoadStop]]] = None,
) -> tuple[list[RateObservation], dict[str, int]]:
    if stops_by_load is None:
        stops_by_load = load_stops(session, broker_id, [load.id for load, _ in rows])
    excluded = {
        "null_rate": 0,
        "nonpositive_rate": 0,
        "unresolved_lane": 0,
        # Missing distance excludes an observation from RPM calculations, but
        # exact-lane raw-total estimates can still use that observation.
        "missing_distance_from_rpm": 0,
    }
    observations: list[RateObservation] = []
    for load, source in rows:
        if load.carrier_rate is None:
            excluded["null_rate"] += 1
            continue
        if load.carrier_rate <= 0:
            excluded["nonpositive_rate"] += 1
            continue
        try:
            lane = derive_primary_lane(stops_by_load.get(load.id, []))
        except LaneNotDerivable:
            excluded["unresolved_lane"] += 1
            continue
        if load.distance_miles is None or load.distance_miles <= 0:
            excluded["missing_distance_from_rpm"] += 1
        observations.append(
            RateObservation(
                load_id=load.id,
                exact_key=lane.exact_key,
                metro_key=lane.metro_key,
                equipment_type=load.equipment_type,
                carrier_pay=_money(load.carrier_rate),
                distance_miles=load.distance_miles,
                rate_date=min(_rate_date(load), as_of),
                source_type=source.tms_type,
            )
        )
    return observations, excluded


def estimate_carrier_rate(
    session: Session,
    broker_id: str,
    load_id: str,
    estimation_version: str = ESTIMATION_VERSION,
    normalization_version: str = NORMALIZATION_VERSION,
) -> Optional[RateEstimateResult]:
    """Estimate all-in carrier pay for an active, uncovered broker load.

    Returns ``None`` when the target does not exist. Raises
    ``RateEstimationNotEligible`` for non-active or covered targets and
    ``LaneNotDerivable`` when the target lane cannot be derived. A valid target
    with insufficient history returns a result with ``status='unavailable'``.
    """
    validate_estimation_version(estimation_version)
    validate_normalization_version(normalization_version)
    assignment_exists = exists(
        select(PlatformAssignment.id).where(
            PlatformAssignment.broker_id == broker_id,
            PlatformAssignment.load_id == load_id,
        )
    )
    target_row = session.execute(
        select(Load, assignment_exists.label("has_assignment")).where(
            Load.broker_id == broker_id, Load.id == load_id
        )
    ).one_or_none()
    if target_row is None:
        return None
    target, has_assignment = target_row
    if target.status != LoadStatus.ACTIVE or target.carrier_id is not None or has_assignment:
        raise RateEstimationNotEligible("load must be active and uncovered")

    as_of = _as_utc(target.last_synced_at)
    rows, candidate_count = _load_observations(session, broker_id, target.id, as_of)
    stops_by_load = load_stops(session, broker_id, [target.id, *(load.id for load, _ in rows)])
    target_lane = derive_primary_lane(stops_by_load.get(target.id, []))
    observations, excluded = _build_observations(session, broker_id, rows, as_of, stops_by_load)
    attempts: list[EstimateTierAttempt] = []

    for lookback_days in (PRIMARY_LOOKBACK_DAYS, EXTENDED_LOOKBACK_DAYS):
        cutoff = as_of - timedelta(days=lookback_days)
        recent = [observation for observation in observations if observation.rate_date >= cutoff]
        for tier in TIERS:
            matched = [
                observation
                for observation in recent
                if _tier_matches(
                    tier,
                    observation,
                    target_lane.exact_key,
                    target_lane.metro_key,
                    target.equipment_type,
                )
            ]
            usable, mode = _usable_observations(matched, tier, target.distance_miles)
            if len(usable) < tier.minimum_required:
                attempts.append(
                    EstimateTierAttempt(
                        tier=tier.code,
                        lookback_days=lookback_days,
                        sample_size=len(usable),
                        minimum_required=tier.minimum_required,
                        reason=(
                            "insufficient usable observations"
                            if usable != matched
                            else "insufficient matching observations"
                        ),
                    )
                )
                continue

            values = (
                [observation.carrier_pay / observation.distance_miles for observation in usable]
                if mode == "rate_per_mile"
                else [observation.carrier_pay for observation in usable]
            )
            central = _percentile(values, Decimal("0.5"))
            low = _percentile(values, Decimal("0.25"))
            high = _percentile(values, Decimal("0.75"))
            if mode == "rate_per_mile":
                if target.distance_miles is None:
                    raise RuntimeError("rate_per_mile mode requires target distance")
                estimate_amount = _money(central * target.distance_miles)
                low_amount = _money(low * target.distance_miles)
                high_amount = _money(high * target.distance_miles)
            else:
                estimate_amount = _money(central)
                low_amount = _money(low)
                high_amount = _money(high)
            dates = [observation.rate_date for observation in usable]
            source_types = tuple(sorted({observation.source_type.value for observation in usable}))
            return RateEstimateResult(
                status="estimated",
                broker_id=broker_id,
                load_id=load_id,
                data_as_of=as_of,
                currency="USD",
                estimate_amount=estimate_amount,
                low_amount=low_amount,
                high_amount=high_amount,
                calculation_mode=(
                    "median_rate_per_mile" if mode == "rate_per_mile" else "median_all_in_total"
                ),
                range_method="observed_interquartile_range",
                confidence_level=_confidence(
                    tier, len(usable), lookback_days, target.equipment_type
                ),
                data_sufficiency="minimum_met",
                confidence_reasons=_confidence_reasons(
                    tier, len(usable), lookback_days, target.equipment_type
                ),
                selected_tier=tier.code,
                lane_scope=tier.lane_scope,
                equipment_scope=tier.equipment_scope,
                lookback_days=lookback_days,
                sample_size=len(usable),
                candidate_count_before_exclusions=candidate_count,
                excluded_counts=excluded,
                source_types=source_types,
                oldest_rate_date=min(dates),
                newest_rate_date=max(dates),
                attempted_tiers=tuple(attempts),
                target_lane_exact_key=target_lane.exact_key,
                target_lane_metro_key=target_lane.metro_key,
                target_equipment_type=target.equipment_type,
                target_distance_miles=target.distance_miles,
                estimation_version=estimation_version,
                normalization_version=normalization_version,
                historical_statuses=HISTORY_STATUSES,
            )

    return RateEstimateResult(
        status="unavailable",
        broker_id=broker_id,
        load_id=load_id,
        data_as_of=as_of,
        currency="USD",
        estimate_amount=None,
        low_amount=None,
        high_amount=None,
        calculation_mode=None,
        range_method=None,
        confidence_level="none",
        data_sufficiency="insufficient",
        confidence_reasons=("No fallback population met the configured minimum sample size",),
        selected_tier=None,
        lane_scope=None,
        equipment_scope=None,
        lookback_days=None,
        sample_size=0,
        candidate_count_before_exclusions=candidate_count,
        excluded_counts=excluded,
        source_types=(),
        oldest_rate_date=None,
        newest_rate_date=None,
        attempted_tiers=tuple(attempts),
        target_lane_exact_key=target_lane.exact_key,
        target_lane_metro_key=target_lane.metro_key,
        target_equipment_type=target.equipment_type,
        target_distance_miles=target.distance_miles,
        estimation_version=estimation_version,
        normalization_version=normalization_version,
        historical_statuses=HISTORY_STATUSES,
    )
