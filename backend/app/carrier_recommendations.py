from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.lane_geography import NORMALIZATION_VERSION
from app.lane_intelligence import (
    ELIGIBLE_HISTORY_STATUSES,
    HISTORY_LOAD_LIMIT,
    MIN_SUFFICIENT_HISTORY,
    LaneNotDerivable,
    derive_primary_lane,
    validate_normalization_version,
)
from app.load_stops import load_stops
from app.models import (
    Carrier,
    EquipmentType,
    Load,
    LoadStatus,
    LoadStop,
    PlatformAssignment,
    StopType,
)

SCORING_VERSION = "carrier-recommendations-v1"
MAX_RECOMMENDATIONS = 20


class UnsupportedScoringVersion(ValueError):
    pass


class RecommendationNotEligible(ValueError):
    pass


@dataclass(frozen=True)
class RecommendationFactor:
    code: str
    evidence_count: int
    contribution: int
    explanation: str


@dataclass(frozen=True)
class CarrierRecommendation:
    candidate_id: str
    carrier_identity_id: Optional[str]
    carrier_ids: tuple[str, ...]
    name: str
    score: int
    data_sufficiency: str
    factors: tuple[RecommendationFactor, ...]
    exact_same_equipment_count: int
    nearby_same_equipment_count: int
    exact_count: int
    nearby_count: int
    same_equipment_count: int
    latest_operational_evidence: Optional[datetime]


@dataclass(frozen=True)
class UnscoredCarrier:
    candidate_id: str
    carrier_identity_id: Optional[str]
    carrier_ids: tuple[str, ...]
    name: str
    reason: str


@dataclass(frozen=True)
class CarrierRecommendationResult:
    broker_id: str
    load_id: str
    scoring_version: str
    normalization_version: str
    data_as_of: datetime
    eligible_statuses: tuple[LoadStatus, ...]
    history_limit: int
    target_lane_exact_key: str
    target_lane_metro_key: Optional[str]
    recommendations: tuple[CarrierRecommendation, ...]
    unscored_carriers: tuple[UnscoredCarrier, ...]


@dataclass(frozen=True)
class _Candidate:
    candidate_id: str
    carrier_identity_id: Optional[str]
    carrier_ids: tuple[str, ...]
    name: str


@dataclass(frozen=True)
class _HistoricalEvidence:
    load_id: str
    candidate_id: str
    exact_key: str
    metro_key: Optional[str]
    equipment_type: EquipmentType
    customer_id: str
    operational_evidence: Optional[datetime]


def validate_scoring_version(version: str) -> None:
    if version != SCORING_VERSION:
        raise UnsupportedScoringVersion(version)


def _candidate_key(carrier: Carrier) -> tuple[str, Optional[str]]:
    if carrier.carrier_identity_id:
        return f"identity:{carrier.carrier_identity_id}", carrier.carrier_identity_id
    return f"carrier:{carrier.id}", None


def _display_carrier(rows: Sequence[Carrier], target_source_id: str) -> Carrier:
    return sorted(
        rows,
        key=lambda carrier: (
            carrier.broker_source_id != target_source_id,
            -carrier.updated_at.timestamp(),
            carrier.id,
        ),
    )[0]


def _candidate_groups(carriers: Sequence[Carrier], target_source_id: str) -> dict[str, _Candidate]:
    grouped: dict[tuple[str, Optional[str]], list[Carrier]] = {}
    for carrier in carriers:
        grouped.setdefault(_candidate_key(carrier), []).append(carrier)

    candidates: dict[str, _Candidate] = {}
    for (candidate_id, identity_id), rows in grouped.items():
        display = _display_carrier(rows, target_source_id)
        candidates[candidate_id] = _Candidate(
            candidate_id=candidate_id,
            carrier_identity_id=identity_id,
            carrier_ids=tuple(sorted(row.id for row in rows)),
            name=display.name,
        )
    return candidates


def _destination_stop(stops: Sequence[LoadStop]) -> Optional[LoadStop]:
    ordered = sorted(stops, key=lambda stop: stop.sequence_number)
    return next(
        (
            stop
            for stop in reversed(ordered)
            if stop.stop_type in (StopType.DROPOFF, StopType.PICKUP_DROPOFF)
        ),
        None,
    )


def _operational_evidence(stop: Optional[LoadStop]) -> Optional[datetime]:
    if stop is None:
        return None
    return stop.actual_arrived_at or stop.actual_departed_at


def _recency_points(evidence: Optional[datetime], as_of: datetime) -> int:
    if evidence is None or evidence > as_of:
        return 0
    age = as_of - evidence
    if age <= timedelta(days=7):
        return 5
    if age <= timedelta(days=30):
        return 3
    if age <= timedelta(days=90):
        return 1
    return 0


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _factor(
    code: str, count: int, points: int, cap: int, explanation: str
) -> Optional[RecommendationFactor]:
    contribution = min(count, cap) * points
    if contribution == 0:
        return None
    return RecommendationFactor(code, count, contribution, explanation.format(count=count))


def _score_candidate(
    candidate: _Candidate,
    evidence: Sequence[_HistoricalEvidence],
    target_lane_exact_key: str,
    target_lane_metro_key: Optional[str],
    target_equipment: EquipmentType,
    target_customer_id: str,
    as_of: datetime,
) -> CarrierRecommendation:
    exact = [item for item in evidence if item.exact_key == target_lane_exact_key]
    nearby = [
        item
        for item in evidence
        if item.exact_key != target_lane_exact_key
        and target_lane_metro_key
        and item.metro_key == target_lane_metro_key
    ]
    # Exclude loads already represented by exact or nearby lane evidence.
    excluded_load_ids = {item.load_id for item in (*exact, *nearby)}
    outside_lane = [item for item in evidence if item.load_id not in excluded_load_ids]
    equipment_is_known = target_equipment != EquipmentType.UNKNOWN
    exact_same = [
        item for item in exact if equipment_is_known and item.equipment_type == target_equipment
    ]
    nearby_same = [
        item for item in nearby if equipment_is_known and item.equipment_type == target_equipment
    ]
    exact_other = [
        item
        for item in exact
        if item.equipment_type not in (target_equipment, EquipmentType.UNKNOWN)
    ]
    nearby_other = [
        item
        for item in nearby
        if item.equipment_type not in (target_equipment, EquipmentType.UNKNOWN)
    ]
    same_equipment = [
        item
        for item in outside_lane
        if equipment_is_known and item.equipment_type == target_equipment
    ]
    same_customer = [item for item in evidence if item.customer_id == target_customer_id]
    latest_evidence = max(
        (item.operational_evidence for item in evidence if item.operational_evidence),
        default=None,
    )

    factors: list[RecommendationFactor] = []
    equipment_label = target_equipment.value.replace("_", "-")
    if target_equipment == EquipmentType.UNKNOWN:
        exact_other_explanation = "{count} exact directional loads with known equipment"
        nearby_other_explanation = "{count} same-metro loads with known equipment"
    else:
        exact_other_explanation = "{count} exact directional loads with other equipment"
        nearby_other_explanation = "{count} same-metro loads with other equipment"
    factor_specs = (
        (
            "exact_lane_same_equipment",
            exact_same,
            10,
            3,
            f"{{count}} exact directional {equipment_label} experience",
        ),
        (
            "nearby_lane_same_equipment",
            nearby_same,
            6,
            3,
            f"{{count}} same-metro directional {equipment_label} experience",
        ),
        (
            "exact_lane_other_equipment",
            exact_other,
            4,
            3,
            exact_other_explanation,
        ),
        (
            "nearby_lane_other_equipment",
            nearby_other,
            2,
            3,
            nearby_other_explanation,
        ),
        (
            "general_same_equipment",
            same_equipment,
            3,
            5,
            (
                f"{{count}} completed loads with matching {equipment_label} outside the target lane"
                if equipment_is_known
                else "{count} completed loads outside the target lane"
            ),
        ),
        ("same_customer", same_customer, 2, 5, "{count} completed loads for this customer"),
        ("overall_history", evidence, 1, 4, "{count} eligible completed loads"),
    )
    for code, items, points, cap, explanation in factor_specs:
        item = _factor(code, len(items), points, cap, explanation)
        if item:
            factors.append(item)

    recency = _recency_points(latest_evidence, as_of)
    if recency:
        factors.append(
            RecommendationFactor(
                "recent_operational_evidence",
                1,
                recency,
                "Latest destination activity was within the configured recency window",
            )
        )

    return CarrierRecommendation(
        candidate_id=candidate.candidate_id,
        carrier_identity_id=candidate.carrier_identity_id,
        carrier_ids=candidate.carrier_ids,
        name=candidate.name,
        score=sum(item.contribution for item in factors),
        data_sufficiency=("sufficient" if len(evidence) >= MIN_SUFFICIENT_HISTORY else "thin"),
        factors=tuple(factors),
        exact_same_equipment_count=len(exact_same),
        nearby_same_equipment_count=len(nearby_same),
        exact_count=len(exact),
        nearby_count=len(nearby),
        same_equipment_count=len(same_equipment),
        latest_operational_evidence=latest_evidence,
    )


def _recommendation_sort_key(item: CarrierRecommendation) -> tuple:
    # Evidence timestamps are normalized at ingestion; normalize again here so
    # a future caller cannot make naive datetimes affect local-time ordering.
    latest_timestamp = (
        _as_utc(item.latest_operational_evidence).timestamp()
        if item.latest_operational_evidence
        else float("-inf")
    )
    return (
        -item.score,
        -item.exact_same_equipment_count,
        -item.nearby_same_equipment_count,
        -item.exact_count,
        -item.nearby_count,
        -item.same_equipment_count,
        -sum(factor.evidence_count for factor in item.factors if factor.code == "overall_history"),
        -latest_timestamp,
        item.name.casefold(),
        0 if item.carrier_identity_id else 1,
        item.candidate_id,
    )


def get_carrier_recommendations(
    session: Session,
    broker_id: str,
    load_id: str,
    scoring_version: str = SCORING_VERSION,
    normalization_version: str = NORMALIZATION_VERSION,
) -> Optional[CarrierRecommendationResult]:
    """Return broker-scoped rankings for an active, uncovered load.

    Returns ``None`` when the target load does not exist. Raises
    ``RecommendationNotEligible`` when the target is not active and uncovered,
    and raises ``LaneNotDerivable`` when its stops cannot define a primary lane.
    Historical loads without derivable lanes are skipped.
    """
    validate_scoring_version(scoring_version)
    validate_normalization_version(normalization_version)

    target = session.scalar(select(Load).where(Load.broker_id == broker_id, Load.id == load_id))
    if target is None:
        return None
    if (
        target.status != LoadStatus.ACTIVE
        or target.carrier_id is not None
        or session.scalar(
            select(PlatformAssignment.id).where(
                PlatformAssignment.broker_id == broker_id,
                PlatformAssignment.load_id == load_id,
            )
        )
        is not None
    ):
        raise RecommendationNotEligible("load must be active and uncovered")

    carriers = session.scalars(
        select(Carrier).where(Carrier.broker_id == broker_id).order_by(Carrier.id)
    ).all()
    candidates = _candidate_groups(carriers, target.broker_source_id)

    historical_loads = session.scalars(
        select(Load)
        .where(
            Load.broker_id == broker_id,
            Load.status.in_(ELIGIBLE_HISTORY_STATUSES),
            Load.carrier_id.is_not(None),
            Load.id != load_id,
        )
        .order_by(Load.last_synced_at.desc(), Load.id.desc())
        .limit(HISTORY_LOAD_LIMIT)
    ).all()
    target_stops = load_stops(session, broker_id, [target.id])
    target_lane = derive_primary_lane(target_stops.get(target.id, []))
    historical_stops = load_stops(session, broker_id, [load.id for load in historical_loads])
    carrier_by_id = {carrier.id: carrier for carrier in carriers}
    evidence_by_candidate: dict[str, list[_HistoricalEvidence]] = {
        candidate_id: [] for candidate_id in candidates
    }
    for historical_load in historical_loads:
        carrier = carrier_by_id.get(historical_load.carrier_id)
        if carrier is None:
            continue
        candidate_id, _ = _candidate_key(carrier)
        stops = historical_stops.get(historical_load.id, [])
        try:
            lane = derive_primary_lane(stops)
        except LaneNotDerivable:
            continue
        destination = _destination_stop(stops)
        evidence_by_candidate.setdefault(candidate_id, []).append(
            _HistoricalEvidence(
                load_id=historical_load.id,
                candidate_id=candidate_id,
                exact_key=lane.exact_key,
                metro_key=lane.metro_key,
                equipment_type=historical_load.equipment_type,
                customer_id=historical_load.customer_id,
                operational_evidence=(
                    _as_utc(evidence)
                    if (evidence := _operational_evidence(destination)) is not None
                    else None
                ),
            )
        )

    scored = [
        _score_candidate(
            candidate,
            evidence_by_candidate.get(candidate_id, []),
            target_lane.exact_key,
            target_lane.metro_key,
            target.equipment_type,
            target.customer_id,
            _as_utc(target.last_synced_at),
        )
        for candidate_id, candidate in candidates.items()
        if evidence_by_candidate.get(candidate_id)
    ]
    scored.sort(key=_recommendation_sort_key)
    unscored = [
        UnscoredCarrier(
            candidate_id=candidate.candidate_id,
            carrier_identity_id=candidate.carrier_identity_id,
            carrier_ids=candidate.carrier_ids,
            name=candidate.name,
            reason="Known broker carrier with no eligible completed history",
        )
        for candidate_id, candidate in candidates.items()
        if not evidence_by_candidate.get(candidate_id)
    ]
    unscored.sort(key=lambda item: (item.name.casefold(), item.candidate_id))

    return CarrierRecommendationResult(
        broker_id=broker_id,
        load_id=load_id,
        scoring_version=scoring_version,
        normalization_version=normalization_version,
        data_as_of=_as_utc(target.last_synced_at),
        eligible_statuses=ELIGIBLE_HISTORY_STATUSES,
        history_limit=HISTORY_LOAD_LIMIT,
        target_lane_exact_key=target_lane.exact_key,
        target_lane_metro_key=target_lane.metro_key,
        recommendations=tuple(scored),
        unscored_carriers=tuple(unscored),
    )
