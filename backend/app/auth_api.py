from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth import issue_demo_token
from app.config import settings
from app.database import get_db
from app.models import Broker

router = APIRouter(tags=["authentication"])


class DemoAuthRequest(BaseModel):
    broker_id: str
    actor: str = "demo-user"


class DemoAuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    broker_id: str


@router.post("/demo/auth", response_model=DemoAuthResponse)
def demo_auth(request: DemoAuthRequest, db: Session = Depends(get_db)) -> DemoAuthResponse:
    if not settings.demo_mode:
        raise HTTPException(status_code=404, detail="not found")
    if db.get(Broker, request.broker_id) is None:
        raise HTTPException(status_code=404, detail="broker not found")
    try:
        token = issue_demo_token(request.broker_id, request.actor)
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return DemoAuthResponse(access_token=token, broker_id=request.broker_id)
