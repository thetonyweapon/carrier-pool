from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import BrokerPrincipal, require_broker_principal
from app.config import settings
from app.database import get_db
from app.models import SharedPoolPolicy
from app.shared_carrier_pool import (
    SharedPoolDisabled,
    SharedPoolNotEligible,
    SharedPoolUnavailable,
    get_shared_carrier_recommendations,
    set_shared_pool_policy,
)
from app.shared_rate_estimation import get_shared_rate_estimate

router = APIRouter(tags=["shared carrier pool"])


class SharedCarrierRecommendationResponse(BaseModel):
    scope: str
    rank: int
    candidate_id: str
    name: str
    match_quality: str
    equipment_type: str
    evidence_count_bucket: str
    contributing_broker_count_bucket: str


class SharedCarrierRecommendationsResponse(BaseModel):
    broker_id: str
    load_id: str
    policy_version: str
    policy_revision: int
    scoring_version: str
    normalization_version: str
    recommendations: list[SharedCarrierRecommendationResponse]


class SharedPoolPolicyResponse(BaseModel):
    broker_id: str
    enabled: bool
    policy_revision: int
    attribute_profile: Optional[str] = None


class SharedPoolPolicyRequest(BaseModel):
    enabled: bool
    reason: Optional[str] = None


class SharedRateEstimateResponse(BaseModel):
    scope: str
    broker_id: str
    load_id: str
    policy_version: str
    policy_revision: int
    estimation_version: str
    normalization_version: str
    status: str
    estimate: dict[str, Optional[str]]
    confidence: str
    match_scope: Optional[str]
    equipment_scope: Optional[str]
    sample_count_bucket: str
    contributing_broker_count_bucket: str
    selected_tier: Optional[str]
    lookback_days: Optional[int]


@router.get("/brokers/{broker_id}/shared-pool-policy", response_model=SharedPoolPolicyResponse)
def shared_pool_policy(
    broker_id: str,
    db: Session = Depends(get_db),
    principal: BrokerPrincipal = Depends(require_broker_principal),
) -> SharedPoolPolicyResponse:
    del principal
    policy = db.scalar(select(SharedPoolPolicy).where(SharedPoolPolicy.broker_id == broker_id))
    if policy is None:
        return SharedPoolPolicyResponse(broker_id=broker_id, enabled=False, policy_revision=0)
    return SharedPoolPolicyResponse(
        broker_id=broker_id,
        enabled=policy.enabled,
        policy_revision=policy.policy_revision,
        attribute_profile=policy.attribute_profile,
    )


@router.put("/brokers/{broker_id}/shared-pool-policy", response_model=SharedPoolPolicyResponse)
def update_shared_pool_policy(
    broker_id: str,
    request: SharedPoolPolicyRequest,
    db: Session = Depends(get_db),
    principal: BrokerPrincipal = Depends(require_broker_principal),
) -> SharedPoolPolicyResponse:
    policy = set_shared_pool_policy(
        db,
        broker_id,
        request.enabled,
        principal.actor,
        request.reason,
    )
    db.commit()
    return SharedPoolPolicyResponse(
        broker_id=broker_id,
        enabled=policy.enabled,
        policy_revision=policy.policy_revision,
        attribute_profile=policy.attribute_profile,
    )


@router.get(
    "/brokers/{broker_id}/loads/{load_id}/shared-carrier-rate-estimate",
    response_model=SharedRateEstimateResponse,
)
def shared_carrier_rate_estimate(
    broker_id: str,
    load_id: str,
    db: Session = Depends(get_db),
    principal: BrokerPrincipal = Depends(require_broker_principal),
) -> SharedRateEstimateResponse:
    del principal
    if not settings.shared_pool_read_enabled:
        raise HTTPException(status_code=404, detail="not found")
    # Rate estimates omit opaque candidate IDs, so the shared-pool ID secret is
    # not required here (unlike recommendations). The shared_pool_id_secret is
    # still validated at the recommendation endpoint below.
    try:
        result = get_shared_rate_estimate(db, broker_id, load_id)
    except SharedPoolDisabled as exc:
        raise HTTPException(status_code=404, detail="not found") from exc
    except SharedPoolNotEligible as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="load not found")
    return SharedRateEstimateResponse(
        scope="shared",
        broker_id=result.broker_id,
        load_id=result.load_id,
        policy_version=result.policy_version,
        policy_revision=result.policy_revision,
        estimation_version=result.estimation_version,
        normalization_version=result.normalization_version,
        status=result.status,
        estimate={
            "amount": _decimal_string(result.amount),
            "low": _decimal_string(result.low),
            "high": _decimal_string(result.high),
            "calculation_mode": result.calculation_mode,
        },
        confidence=result.confidence,
        match_scope=result.match_scope,
        equipment_scope=result.equipment_scope,
        sample_count_bucket=result.sample_count_bucket,
        contributing_broker_count_bucket=result.contributing_broker_count_bucket,
        selected_tier=result.selected_tier,
        lookback_days=result.lookback_days,
    )


@router.get(
    "/brokers/{broker_id}/loads/{load_id}/shared-carrier-recommendations",
    response_model=SharedCarrierRecommendationsResponse,
)
def shared_carrier_recommendations(
    broker_id: str,
    load_id: str,
    db: Session = Depends(get_db),
    principal: BrokerPrincipal = Depends(require_broker_principal),
) -> SharedCarrierRecommendationsResponse:
    del principal
    # Shared reads are disabled by default and require the authenticated broker
    # identity boundary and an opaque-ID secret for HMAC candidate IDs.
    if not settings.shared_pool_read_enabled:
        raise HTTPException(status_code=404, detail="not found")
    if not settings.shared_pool_id_secret:
        raise HTTPException(
            status_code=503, detail="shared pool identifier secret is not configured"
        )
    try:
        result = get_shared_carrier_recommendations(
            db,
            broker_id,
            load_id,
            settings.shared_pool_id_secret,
        )
    except SharedPoolDisabled as exc:
        raise HTTPException(status_code=404, detail="not found") from exc
    except SharedPoolNotEligible as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except SharedPoolUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="load not found")
    return SharedCarrierRecommendationsResponse(
        broker_id=result.broker_id,
        load_id=result.load_id,
        policy_version=result.policy_version,
        policy_revision=result.policy_revision,
        scoring_version=result.scoring_version,
        normalization_version=result.normalization_version,
        recommendations=[
            SharedCarrierRecommendationResponse(
                scope="shared",
                rank=rank,
                candidate_id=item.candidate_id,
                name=item.name,
                match_quality=item.match_quality,
                equipment_type=item.equipment_type.value,
                evidence_count_bucket=item.evidence_count_bucket,
                contributing_broker_count_bucket=item.contributing_broker_count_bucket,
            )
            for rank, item in enumerate(result.recommendations, start=1)
        ],
    )


def _decimal_string(value) -> Optional[str]:
    return format(value, ".2f") if value is not None else None
