import hashlib
import hmac
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, Sequence

from sqlalchemy import and_, exists, func, or_, select, tuple_
from sqlalchemy.orm import Session

from app.lane_geography import NORMALIZATION_VERSION
from app.lane_intelligence import (
    ELIGIBLE_HISTORY_STATUSES,
    HISTORY_LOAD_LIMIT,
    LaneNotDerivable,
    derive_primary_lane,
)
from app.load_eligibility import LoadNotEligible, LoadNotFound, require_active_uncovered
from app.load_stops import load_stops
from app.models import (
    Broker,
    Carrier,
    CarrierIdentity,
    EquipmentType,
    Load,
    LoadStop,
    SharedPoolPolicy,
    SharedPoolPolicyEvent,
    SharedPoolQueryAudit,
)
from app.observability import canonical_request_id

SHARED_POOL_POLICY_VERSION = "shared-carrier-pool-v1"
SHARED_POOL_ATTRIBUTE_PROFILE = "public-carrier-name-v1"
SHARED_POOL_SCORING_VERSION = "shared-carrier-recommendations-v1"
MIN_SHARED_CONTRIBUTING_BROKERS = 3


class SharedPoolDisabled(ValueError):
    pass


class SharedPoolNotEligible(ValueError):
    pass


class SharedPoolUnavailable(ValueError):
    pass


class CarrierIdentityNotFound(ValueError):
    pass


@dataclass(frozen=True)
class SharedCarrierRecommendation:
    candidate_id: str
    name: str
    match_quality: str
    equipment_type: EquipmentType
    evidence_count_bucket: str
    contributing_broker_count_bucket: str
    score: int = 0


@dataclass(frozen=True)
class SharedCarrierPoolResult:
    broker_id: str
    load_id: str
    policy_version: str
    policy_revision: int
    scoring_version: str
    normalization_version: str
    recommendations: tuple[SharedCarrierRecommendation, ...]


@dataclass(frozen=True)
class _Evidence:
    broker_id: str
    carrier_name: str
    exact: bool
    equipment_type: EquipmentType


def set_shared_pool_policy(
    session: Session,
    broker_id: str,
    enabled: bool,
    changed_by: str,
    reason: Optional[str] = None,
    changed_by_subject: str = "system",
    request_id: Optional[str] = None,
) -> SharedPoolPolicy:
    """Record participation state for a future authenticated policy boundary."""
    # Make pending rows visible before the existence check. SessionLocal uses
    # autoflush=False, so a freshly-added (uncommitted) broker is not yet
    # reachable via Session.get unless we flush first.
    session.flush()
    if session.get(Broker, broker_id) is None:
        raise ValueError("broker not found")
    now = datetime.now(timezone.utc)
    request_id = canonical_request_id(request_id)
    # PostgreSQL uses this row lock to serialize concurrent policy revisions;
    # SQLite test databases do not provide row-level locking.
    policy = session.scalar(
        select(SharedPoolPolicy).where(SharedPoolPolicy.broker_id == broker_id).with_for_update()
    )
    if policy is None:
        policy = SharedPoolPolicy(
            broker_id=broker_id,
            enabled=enabled,
            policy_revision=1,
            attribute_profile=SHARED_POOL_ATTRIBUTE_PROFILE,
            changed_by=changed_by,
            changed_by_subject=changed_by_subject,
            reason=reason,
            updated_at=now,
        )
        session.add(policy)
    else:
        policy.enabled = enabled
        policy.policy_revision += 1
        policy.attribute_profile = SHARED_POOL_ATTRIBUTE_PROFILE
        policy.changed_by = changed_by
        policy.changed_by_subject = changed_by_subject
        policy.reason = reason
        policy.updated_at = now
    session.add(
        SharedPoolPolicyEvent(
            broker_id=broker_id,
            enabled=enabled,
            policy_revision=policy.policy_revision,
            policy_version=SHARED_POOL_POLICY_VERSION,
            attribute_profile=SHARED_POOL_ATTRIBUTE_PROFILE,
            changed_by=changed_by,
            changed_by_subject=changed_by_subject,
            request_id=request_id,
            reason=reason,
            created_at=now,
        )
    )
    session.flush()
    return policy


def set_shared_display_name(
    session: Session,
    broker_id: str,
    identity_id: str,
    shared_display_name: Optional[str],
) -> CarrierIdentity:
    """Explicitly approve or revoke a broker-owned identity's public name."""
    identity = session.scalar(
        select(CarrierIdentity)
        .where(
            CarrierIdentity.broker_id == broker_id,
            CarrierIdentity.id == identity_id,
        )
        .with_for_update()
    )
    if identity is None:
        raise CarrierIdentityNotFound("carrier identity not found")
    identity.shared_display_name = shared_display_name
    identity.updated_at = datetime.now(timezone.utc)
    session.flush()
    return identity


def get_shared_carrier_recommendations(
    session: Session,
    broker_id: str,
    load_id: str,
    id_secret: str,
    normalization_version: str = NORMALIZATION_VERSION,
    actor_subject: str = "system",
    request_id: Optional[str] = None,
) -> Optional[SharedCarrierPoolResult]:
    if not id_secret:
        raise SharedPoolUnavailable("shared pool identifier secret is not configured")
    request_id = canonical_request_id(request_id)
    if normalization_version != NORMALIZATION_VERSION:
        raise ValueError(f"unsupported normalization version: {normalization_version}")

    requester_policy = session.scalar(
        select(SharedPoolPolicy).where(
            SharedPoolPolicy.broker_id == broker_id,
            SharedPoolPolicy.enabled.is_(True),
        )
    )
    if requester_policy is None:
        raise SharedPoolDisabled("requesting broker has not opted into the shared pool")

    try:
        target = require_active_uncovered(session, broker_id, load_id)
    except LoadNotFound:
        return None
    except LoadNotEligible as exc:
        raise SharedPoolNotEligible(str(exc)) from exc

    target_stops = load_stops(session, broker_id, [target.id]).get(target.id, [])
    try:
        target_lane = derive_primary_lane(target_stops)
    except LaneNotDerivable as exc:
        raise SharedPoolNotEligible(str(exc)) from exc

    policies = session.scalars(
        select(SharedPoolPolicy)
        .where(SharedPoolPolicy.enabled.is_(True))
        .order_by(SharedPoolPolicy.broker_id)
    ).all()
    participant_scope_digest = _participant_scope_digest(policies)
    participant_ids = [policy.broker_id for policy in policies]
    as_of = datetime.now(timezone.utc)
    historical_loads = _historical_loads(session, participant_ids, as_of)
    historical_stops = _load_stops_by_scope(
        session, participant_ids, [load.id for load in historical_loads]
    )
    carrier_refs = {
        (load.broker_id, load.carrier_id)
        for load in historical_loads
        if load.carrier_id is not None
    }
    carriers = session.scalars(
        select(Carrier)
        .where(
            tuple_(Carrier.broker_id, Carrier.id).in_(carrier_refs),
        )
        .order_by(Carrier.broker_id, Carrier.id)
    ).all()
    identity_refs = {
        (carrier.broker_id, carrier.carrier_identity_id)
        for carrier in carriers
        if carrier.carrier_identity_id is not None
    }
    identities = session.scalars(
        select(CarrierIdentity).where(
            tuple_(CarrierIdentity.broker_id, CarrierIdentity.id).in_(identity_refs)
        )
    ).all()
    identity_by_id = {(identity.broker_id, identity.id): identity for identity in identities}
    identity_aliases = _shared_identity_aliases(identities)
    carrier_candidates = {
        (carrier.broker_id, carrier.id): _carrier_candidate(
            carrier, identity_by_id, identity_aliases
        )
        for carrier in carriers
    }
    carrier_candidates = {
        key: value for key, value in carrier_candidates.items() if value is not None
    }

    evidence_by_candidate: dict[str, list[_Evidence]] = defaultdict(list)
    for historical_load in historical_loads:
        if historical_load.broker_id == broker_id and historical_load.id == load_id:
            continue
        candidate = carrier_candidates.get((historical_load.broker_id, historical_load.carrier_id))
        if candidate is None:
            continue
        stops = historical_stops.get((historical_load.broker_id, historical_load.id), [])
        try:
            lane = derive_primary_lane(stops)
        except LaneNotDerivable:
            continue
        operational_times = [
            timestamp
            for stop in stops
            for timestamp in (stop.actual_arrived_at, stop.actual_departed_at)
            if timestamp is not None
        ]
        if operational_times and max(map(_as_utc, operational_times)) > as_of:
            continue
        exact = lane.exact_key == target_lane.exact_key
        nearby = (
            not exact
            and target_lane.metro_key is not None
            and lane.metro_key == target_lane.metro_key
        )
        if not exact and not nearby:
            continue
        evidence_by_candidate[candidate[0]].append(
            _Evidence(
                broker_id=historical_load.broker_id,
                carrier_name=candidate[1],
                exact=exact,
                equipment_type=historical_load.equipment_type,
            )
        )

    candidates = [
        _build_recommendation(candidate_key, evidence, id_secret, target.equipment_type)
        for candidate_key, evidence in evidence_by_candidate.items()
        if len({item.broker_id for item in evidence}) >= MIN_SHARED_CONTRIBUTING_BROKERS
    ]
    candidates.sort(key=_recommendation_sort_key)
    result = SharedCarrierPoolResult(
        broker_id=broker_id,
        load_id=load_id,
        policy_version=SHARED_POOL_POLICY_VERSION,
        policy_revision=requester_policy.policy_revision,
        scoring_version=SHARED_POOL_SCORING_VERSION,
        normalization_version=normalization_version,
        recommendations=tuple(candidates),
    )
    session.add(
        SharedPoolQueryAudit(
            broker_id=broker_id,
            load_id=load_id,
            query_type="recommendations",
            policy_version=SHARED_POOL_POLICY_VERSION,
            policy_revision=requester_policy.policy_revision,
            scoring_version=SHARED_POOL_SCORING_VERSION,
            normalization_version=normalization_version,
            participant_scope_digest=participant_scope_digest,
            participant_count=len(participant_ids),
            result_count=len(candidates),
            actor_subject=actor_subject,
            request_id=request_id,
            created_at=datetime.now(timezone.utc),
        )
    )
    session.commit()
    return result


def _carrier_candidate(
    carrier: Carrier,
    identity_by_id: dict[tuple[str, str], CarrierIdentity],
    identity_aliases: dict[tuple[str, str], str],
) -> Optional[tuple[str, str]]:
    identity = identity_by_id.get((carrier.broker_id, carrier.carrier_identity_id or ""))
    if identity is None or not identity.shared_display_name:
        return None
    candidate_key = identity_aliases.get((identity.broker_id, identity.id))
    if candidate_key is None:
        return None
    return candidate_key, identity.shared_display_name


def _shared_identity_aliases(
    identities: Sequence[CarrierIdentity],
) -> dict[tuple[str, str], str]:
    """Join opted-in identities through either normalized MC or DOT evidence."""
    identity_identifiers: dict[tuple[str, str], tuple[str, ...]] = {}
    mc_dots: dict[str, set[Optional[str]]] = defaultdict(set)
    dot_mcs: dict[str, set[Optional[str]]] = defaultdict(set)
    for identity in identities:
        key = (identity.broker_id, identity.id)
        if identity.normalized_mc_number:
            mc_dots[identity.normalized_mc_number].add(identity.normalized_dot_number)
        if identity.normalized_dot_number:
            dot_mcs[identity.normalized_dot_number].add(identity.normalized_mc_number)
        identity_identifiers[key] = tuple(
            identifier
            for identifier in (
                f"mc:{identity.normalized_mc_number}" if identity.normalized_mc_number else None,
                f"dot:{identity.normalized_dot_number}" if identity.normalized_dot_number else None,
            )
            if identifier is not None
        )

    conflicting_identifiers = {
        f"mc:{mc}" for mc, dots in mc_dots.items() if len({dot for dot in dots if dot}) > 1
    } | {f"dot:{dot}" for dot, mcs in dot_mcs.items() if len({mc for mc in mcs if mc}) > 1}
    parent: dict[str, str] = {}

    def find(identifier: str) -> str:
        parent.setdefault(identifier, identifier)
        while parent[identifier] != identifier:
            parent[identifier] = parent[parent[identifier]]
            identifier = parent[identifier]
        return identifier

    def union(left: str, right: str) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parent[max(left_root, right_root)] = min(left_root, right_root)

    for identifiers in identity_identifiers.values():
        if not identifiers or conflicting_identifiers.intersection(identifiers):
            continue
        find(identifiers[0])
        if len(identifiers) == 2:
            union(*identifiers)

    return {
        identity_key: find(identifiers[0])
        for identity_key, identifiers in identity_identifiers.items()
        if identifiers
        and not conflicting_identifiers.intersection(identifiers)
        and identifiers[0] in parent
    }


def _load_stops_by_scope(
    session: Session, broker_ids: Sequence[str], load_ids: Sequence[str]
) -> dict[tuple[str, str], list[LoadStop]]:
    if not broker_ids or not load_ids:
        return {}
    grouped: dict[tuple[str, str], list[LoadStop]] = defaultdict(list)
    stops = session.scalars(
        select(LoadStop)
        .where(LoadStop.broker_id.in_(broker_ids), LoadStop.load_id.in_(load_ids))
        .order_by(LoadStop.broker_id, LoadStop.load_id, LoadStop.sequence_number)
    ).all()
    for stop in stops:
        grouped[(stop.broker_id, stop.load_id)].append(stop)
    return grouped


def _historical_loads(
    session: Session, participant_ids: Sequence[str], as_of: Optional[datetime] = None
) -> list[Load]:
    """Fetch a bounded, deterministic history slice for every participant."""
    if not participant_ids:
        return []
    filters = [
        Load.broker_id.in_(participant_ids),
        Load.status.in_(ELIGIBLE_HISTORY_STATUSES),
        Load.carrier_id.is_not(None),
    ]
    if as_of is not None:
        filters.append(Load.last_synced_at <= as_of)
        filters.extend(
            (
                or_(Load.source_created_at.is_(None), Load.source_created_at <= as_of),
                or_(Load.source_updated_at.is_(None), Load.source_updated_at <= as_of),
                or_(Load.booked_at.is_(None), Load.booked_at <= as_of),
                ~exists(
                    select(LoadStop.id).where(
                        LoadStop.broker_id == Load.broker_id,
                        LoadStop.load_id == Load.id,
                        or_(
                            LoadStop.scheduled_start_at > as_of,
                            LoadStop.scheduled_end_at > as_of,
                            LoadStop.actual_arrived_at > as_of,
                            LoadStop.actual_departed_at > as_of,
                        ),
                    )
                ),
                ~exists(
                    select(LoadStop.id).where(
                        LoadStop.broker_id == Load.broker_id,
                        LoadStop.load_id == Load.id,
                        LoadStop.scheduled_date > as_of.date(),
                    )
                ),
            )
        )
    ranked = (
        select(
            Load.id.label("load_id"),
            Load.broker_id.label("load_broker_id"),
            func.row_number()
            .over(
                partition_by=Load.broker_id,
                order_by=(Load.last_synced_at.desc(), Load.id.desc()),
            )
            .label("history_rank"),
        )
        .where(*filters)
        .subquery()
    )
    return session.scalars(
        select(Load)
        .join(
            ranked,
            and_(Load.id == ranked.c.load_id, Load.broker_id == ranked.c.load_broker_id),
        )
        .where(ranked.c.history_rank <= HISTORY_LOAD_LIMIT)
        .order_by(Load.broker_id, Load.last_synced_at.desc(), Load.id.desc())
    ).all()


def _build_recommendation(
    candidate_key: str,
    evidence: Sequence[_Evidence],
    id_secret: str,
    target_equipment: EquipmentType,
) -> SharedCarrierRecommendation:
    exact = [item for item in evidence if item.exact]
    nearby = [item for item in evidence if not item.exact]
    exact_same = [item for item in exact if item.equipment_type == target_equipment]
    nearby_same = [item for item in nearby if item.equipment_type == target_equipment]
    exact_other = [item for item in exact if item.equipment_type != target_equipment]
    nearby_other = [item for item in nearby if item.equipment_type != target_equipment]
    score = (
        min(len(exact_same), 3) * 10
        + min(len(nearby_same), 3) * 6
        + min(len(exact_other), 3) * 4
        + min(len(nearby_other), 3) * 2
        + min(len(evidence), 4)
    )
    names = Counter(item.carrier_name for item in evidence)
    name = min(names, key=lambda value: (-names[value], value.casefold(), value))
    return SharedCarrierRecommendation(
        candidate_id=_opaque_candidate_id(candidate_key, id_secret),
        name=name,
        match_quality="exact" if exact else "same_metro",
        equipment_type=(
            target_equipment if exact_same or nearby_same else evidence[0].equipment_type
        ),
        evidence_count_bucket=_count_bucket(len(evidence)),
        contributing_broker_count_bucket=_count_bucket(len({item.broker_id for item in evidence})),
        score=score,
    )


def _recommendation_sort_key(item: SharedCarrierRecommendation) -> tuple[bool, int, str, str]:
    return (item.match_quality != "exact", -item.score, item.name.casefold(), item.candidate_id)


def _opaque_candidate_id(candidate_key: str, secret: str) -> str:
    digest = hmac.new(secret.encode(), candidate_key.encode(), hashlib.sha256).hexdigest()
    return f"shared:{digest}"


def _participant_scope_digest(policies: Sequence[SharedPoolPolicy]) -> str:
    scope = ",".join(f"{policy.broker_id}:{policy.policy_revision}" for policy in policies)
    return hashlib.sha256(scope.encode()).hexdigest()


def _count_bucket(value: int) -> str:
    if value <= 0:
        return "0"
    if value == 1:
        return "1"
    if value == 2:
        return "2"
    if value <= 5:
        return "3-5"
    if value <= 10:
        return "6-10"
    return "11+"


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
