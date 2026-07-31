from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.lane_geography import NORMALIZATION_VERSION
from app.lane_intelligence import (
    ELIGIBLE_HISTORY_STATUSES,
    LaneNotDerivable,
    UnsupportedNormalizationVersion,
    get_lane_intelligence,
)

router = APIRouter(tags=["lane intelligence"])


class LaneLocationResponse(BaseModel):
    exact_key: str
    metro_key: Optional[str]
    metro_name: Optional[str]
    match_method: str


class LaneResponse(BaseModel):
    exact_key: str
    metro_key: Optional[str]
    origin: LaneLocationResponse
    destination: LaneLocationResponse


class LaneHistoryResponse(BaseModel):
    eligible_statuses: list[str]
    exact_count: int
    nearby_count: int
    equipment_exact_count: int
    equipment_nearby_count: int
    selected_scope: str
    data_sufficiency: str
    fallback_reason: Optional[str]


class LaneIntelligenceResponse(BaseModel):
    broker_id: str
    load_id: str
    normalization_version: str
    lane: LaneResponse
    history: LaneHistoryResponse


@router.get(
    "/brokers/{broker_id}/loads/{load_id}/lane-intelligence",
    response_model=LaneIntelligenceResponse,
)
def lane_intelligence(
    broker_id: str,
    load_id: str,
    normalization_version: str = NORMALIZATION_VERSION,
    db: Session = Depends(get_db),
) -> LaneIntelligenceResponse:
    try:
        result = get_lane_intelligence(db, broker_id, load_id, normalization_version)
    except UnsupportedNormalizationVersion as exc:
        raise HTTPException(
            status_code=422,
            detail=f"unsupported normalization version: {exc}",
        ) from exc
    except LaneNotDerivable as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if result is None:
        raise HTTPException(status_code=404, detail="load not found")

    return LaneIntelligenceResponse(
        broker_id=result.broker_id,
        load_id=result.load_id,
        normalization_version=result.normalization_version,
        lane=LaneResponse(
            exact_key=result.lane.exact_key,
            metro_key=result.lane.metro_key,
            origin=LaneLocationResponse(
                exact_key=result.lane.origin.location.exact_key,
                metro_key=result.lane.origin.location.metro_key,
                metro_name=result.lane.origin.location.metro_name,
                match_method=result.lane.origin.location.match_method,
            ),
            destination=LaneLocationResponse(
                exact_key=result.lane.destination.location.exact_key,
                metro_key=result.lane.destination.location.metro_key,
                metro_name=result.lane.destination.location.metro_name,
                match_method=result.lane.destination.location.match_method,
            ),
        ),
        history=LaneHistoryResponse(
            eligible_statuses=[status.value for status in ELIGIBLE_HISTORY_STATUSES],
            exact_count=result.history.exact_count,
            nearby_count=result.history.nearby_count,
            equipment_exact_count=result.history.equipment_exact_count,
            equipment_nearby_count=result.history.equipment_nearby_count,
            selected_scope=result.history.selected_scope,
            data_sufficiency=result.history.data_sufficiency,
            fallback_reason=result.history.fallback_reason,
        ),
    )
