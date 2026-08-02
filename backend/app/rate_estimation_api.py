from datetime import datetime
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth import BrokerPrincipal, require_broker_principal
from app.database import get_db
from app.lane_geography import NORMALIZATION_VERSION
from app.lane_intelligence import LaneNotDerivable, UnsupportedNormalizationVersion
from app.rate_estimation import (
    ESTIMATION_VERSION,
    RATE_CORRECTION_POLICY,
    RateEstimationNotEligible,
    UnsupportedEstimationVersion,
    estimate_carrier_rate,
)

router = APIRouter(tags=["carrier rate estimation"])


class EstimateTierAttemptResponse(BaseModel):
    tier: str
    lookback_days: int
    sample_size: int
    minimum_required: int
    reason: str


class EstimateAmountsResponse(BaseModel):
    amount: Optional[str]
    low: Optional[str]
    high: Optional[str]
    calculation_mode: Optional[str]
    range_method: Optional[str]


class EstimateConfidenceResponse(BaseModel):
    level: str
    data_sufficiency: str
    reasons: list[str]


class EstimatePopulationResponse(BaseModel):
    selected_tier: Optional[str]
    lane_scope: Optional[str]
    equipment_scope: Optional[str]
    lookback_days: Optional[int]
    sample_size: int
    candidate_count_before_exclusions: int
    excluded_counts: dict[str, int]
    source_types: list[str]
    oldest_rate_date: Optional[datetime]
    newest_rate_date: Optional[datetime]
    attempted_tiers: list[EstimateTierAttemptResponse]


class EstimateTargetResponse(BaseModel):
    lane_exact_key: str
    lane_metro_key: Optional[str]
    equipment_type: str
    distance_miles: Optional[str]


class EstimateMethodResponse(BaseModel):
    estimation_version: str
    normalization_version: str
    currency: str
    historical_statuses: list[str]
    correction_policy: str


class RateEstimateResponse(BaseModel):
    status: str
    broker_id: str
    load_id: str
    data_as_of: datetime
    estimate: EstimateAmountsResponse
    confidence: EstimateConfidenceResponse
    population: EstimatePopulationResponse
    target: EstimateTargetResponse
    method: EstimateMethodResponse


def _decimal_string(value: Optional[Decimal]) -> Optional[str]:
    return format(value, ".2f") if value is not None else None


@router.get(
    "/brokers/{broker_id}/loads/{load_id}/carrier-rate-estimate",
    response_model=RateEstimateResponse,
)
def carrier_rate_estimate(
    broker_id: str,
    load_id: str,
    estimation_version: str = ESTIMATION_VERSION,
    normalization_version: str = NORMALIZATION_VERSION,
    principal: BrokerPrincipal = Depends(require_broker_principal),
    db: Session = Depends(get_db),
) -> RateEstimateResponse:
    del principal
    try:
        result = estimate_carrier_rate(
            db,
            broker_id,
            load_id,
            estimation_version,
            normalization_version,
        )
    except (UnsupportedEstimationVersion, UnsupportedNormalizationVersion) as exc:
        raise HTTPException(status_code=422, detail=f"unsupported version: {exc}") from exc
    except LaneNotDerivable as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RateEstimationNotEligible as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    if result is None:
        raise HTTPException(status_code=404, detail="load not found")

    return RateEstimateResponse(
        status=result.status,
        broker_id=result.broker_id,
        load_id=result.load_id,
        data_as_of=result.data_as_of,
        estimate=EstimateAmountsResponse(
            amount=_decimal_string(result.estimate_amount),
            low=_decimal_string(result.low_amount),
            high=_decimal_string(result.high_amount),
            calculation_mode=result.calculation_mode,
            range_method=result.range_method,
        ),
        confidence=EstimateConfidenceResponse(
            level=result.confidence_level,
            data_sufficiency=result.data_sufficiency,
            reasons=list(result.confidence_reasons),
        ),
        population=EstimatePopulationResponse(
            selected_tier=result.selected_tier,
            lane_scope=result.lane_scope,
            equipment_scope=result.equipment_scope,
            lookback_days=result.lookback_days,
            sample_size=result.sample_size,
            candidate_count_before_exclusions=result.candidate_count_before_exclusions,
            excluded_counts=result.excluded_counts,
            source_types=list(result.source_types),
            oldest_rate_date=result.oldest_rate_date,
            newest_rate_date=result.newest_rate_date,
            attempted_tiers=[
                EstimateTierAttemptResponse(
                    tier=attempt.tier,
                    lookback_days=attempt.lookback_days,
                    sample_size=attempt.sample_size,
                    minimum_required=attempt.minimum_required,
                    reason=attempt.reason,
                )
                for attempt in result.attempted_tiers
            ],
        ),
        target=EstimateTargetResponse(
            lane_exact_key=result.target_lane_exact_key,
            lane_metro_key=result.target_lane_metro_key,
            equipment_type=result.target_equipment_type.value,
            distance_miles=_decimal_string(result.target_distance_miles),
        ),
        method=EstimateMethodResponse(
            estimation_version=result.estimation_version,
            normalization_version=result.normalization_version,
            currency=result.currency,
            historical_statuses=[status.value for status in result.historical_statuses],
            correction_policy=RATE_CORRECTION_POLICY,
        ),
    )
