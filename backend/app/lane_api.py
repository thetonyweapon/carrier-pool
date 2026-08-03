from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth import BrokerPrincipal, require_broker_principal
from app.database import get_db
from app.lane_geography import NORMALIZATION_VERSION
from app.lane_intelligence import (
    ELIGIBLE_HISTORY_STATUSES,
    TRAVEL_TIME_VERSION,
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
    history_limit: int
    history_truncated: bool


class TravelTimeResponse(BaseModel):
    minutes: int
    label: str
    version: str


class LaneIntelligenceResponse(BaseModel):
    broker_id: str
    load_id: str
    normalization_version: str
    lane: LaneResponse
    history: LaneHistoryResponse
    typical_travel_time: Optional[TravelTimeResponse]


def _travel_time_label(minutes: int) -> str:
    hours, remainder = divmod(minutes, 60)
    parts = [f"{hours} hour" + ("" if hours == 1 else "s")] if hours else []
    if remainder:
        parts.append(f"{remainder} minute" + ("" if remainder == 1 else "s"))
    return f"Around {' '.join(parts)}"


@router.get(
    "/brokers/{broker_id}/loads/{load_id}/lane-intelligence",
    response_model=LaneIntelligenceResponse,
)
def lane_intelligence(
    broker_id: str,
    load_id: str,
    normalization_version: str = NORMALIZATION_VERSION,
    principal: BrokerPrincipal = Depends(require_broker_principal),
    db: Session = Depends(get_db),
) -> LaneIntelligenceResponse:
    broker_id = principal.broker_id
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

    typical_travel_time = result.typical_travel_time_minutes
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
            history_limit=result.history.history_limit,
            history_truncated=result.history.history_truncated,
        ),
        typical_travel_time=(
            TravelTimeResponse(
                minutes=typical_travel_time,
                label=_travel_time_label(typical_travel_time),
                version=TRAVEL_TIME_VERSION,
            )
            if typical_travel_time is not None
            else None
        ),
    )
