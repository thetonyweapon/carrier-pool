from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth import BrokerPrincipal, require_broker_principal
from app.carrier_recommendations import (
    MAX_RECOMMENDATIONS,
    SCORING_VERSION,
    RecommendationNotEligible,
    UnsupportedScoringVersion,
    get_carrier_recommendations,
)
from app.database import get_db
from app.lane_geography import NORMALIZATION_VERSION
from app.lane_intelligence import LaneNotDerivable, UnsupportedNormalizationVersion

router = APIRouter(tags=["carrier recommendations"])


class RecommendationFactorResponse(BaseModel):
    code: str
    evidence_count: int
    contribution: int
    explanation: str


class CarrierRecommendationResponse(BaseModel):
    rank: int
    candidate_id: str
    carrier_identity_id: Optional[str]
    carrier_ids: list[str]
    name: str
    score: int
    data_sufficiency: str
    factors: list[RecommendationFactorResponse]
    exact_same_equipment_count: int
    nearby_same_equipment_count: int
    exact_count: int
    nearby_count: int
    same_equipment_count: int
    latest_operational_evidence: Optional[datetime]


class UnscoredCarrierResponse(BaseModel):
    candidate_id: str
    carrier_identity_id: Optional[str]
    carrier_ids: list[str]
    name: str
    reason: str


class CarrierRecommendationsResponse(BaseModel):
    broker_id: str
    load_id: str
    scoring_version: str
    normalization_version: str
    data_as_of: datetime
    eligible_statuses: list[str]
    history_limit: int
    lane_exact_key: str
    lane_metro_key: Optional[str]
    recommendations: list[CarrierRecommendationResponse]
    unscored_carriers: list[UnscoredCarrierResponse]


@router.get(
    "/brokers/{broker_id}/loads/{load_id}/carrier-recommendations",
    response_model=CarrierRecommendationsResponse,
)
def carrier_recommendations(
    broker_id: str,
    load_id: str,
    scoring_version: str = SCORING_VERSION,
    normalization_version: str = NORMALIZATION_VERSION,
    limit: int = Query(MAX_RECOMMENDATIONS, ge=1, le=MAX_RECOMMENDATIONS),
    principal: BrokerPrincipal = Depends(require_broker_principal),
    db: Session = Depends(get_db),
) -> CarrierRecommendationsResponse:
    del principal
    try:
        result = get_carrier_recommendations(
            db,
            broker_id,
            load_id,
            scoring_version,
            normalization_version,
        )
    except (UnsupportedScoringVersion, UnsupportedNormalizationVersion) as exc:
        raise HTTPException(status_code=422, detail=f"unsupported version: {exc}") from exc
    except LaneNotDerivable as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RecommendationNotEligible as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    if result is None:
        raise HTTPException(status_code=404, detail="load not found")

    recommendations = tuple(enumerate(result.recommendations, start=1))[:limit]
    unscored_carriers = result.unscored_carriers[:limit]
    return CarrierRecommendationsResponse(
        broker_id=result.broker_id,
        load_id=result.load_id,
        scoring_version=result.scoring_version,
        normalization_version=result.normalization_version,
        data_as_of=result.data_as_of,
        eligible_statuses=[status.value for status in result.eligible_statuses],
        history_limit=result.history_limit,
        lane_exact_key=result.target_lane_exact_key,
        lane_metro_key=result.target_lane_metro_key,
        recommendations=[
            CarrierRecommendationResponse(
                rank=rank,
                candidate_id=item.candidate_id,
                carrier_identity_id=item.carrier_identity_id,
                carrier_ids=list(item.carrier_ids),
                name=item.name,
                score=item.score,
                data_sufficiency=item.data_sufficiency,
                factors=[
                    RecommendationFactorResponse(
                        code=factor.code,
                        evidence_count=factor.evidence_count,
                        contribution=factor.contribution,
                        explanation=factor.explanation,
                    )
                    for factor in item.factors
                ],
                exact_same_equipment_count=item.exact_same_equipment_count,
                nearby_same_equipment_count=item.nearby_same_equipment_count,
                exact_count=item.exact_count,
                nearby_count=item.nearby_count,
                same_equipment_count=item.same_equipment_count,
                latest_operational_evidence=item.latest_operational_evidence,
            )
            for rank, item in recommendations
        ],
        unscored_carriers=[
            UnscoredCarrierResponse(
                candidate_id=item.candidate_id,
                carrier_identity_id=item.carrier_identity_id,
                carrier_ids=list(item.carrier_ids),
                name=item.name,
                reason=item.reason,
            )
            for item in unscored_carriers
        ],
    )
