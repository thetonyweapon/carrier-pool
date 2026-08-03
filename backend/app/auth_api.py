from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import (
    BrokerPrincipal,
    get_current_principal,
    get_optional_principal,
    issue_authenticated_token,
)
from app.config import settings
from app.database import get_db
from app.demo_accounts import (
    AccountAuthenticationError,
    AccountPermissionError,
    AccountSession,
    AccountValidationError,
    DemoAccountRegistry,
    account_registry,
)
from app.models import Broker

router = APIRouter(tags=["authentication"])


class DemoBrokerResponse(BaseModel):
    id: str
    name: str
    is_demo: bool


class DemoAuthRequest(BaseModel):
    broker_id: str
    identifier: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=1, max_length=128)


class DemoAuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    broker_id: str
    account_id: str
    is_admin: bool


class AccountCreateRequest(BaseModel):
    broker_id: str
    name: str = Field(min_length=1, max_length=255)
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=1, max_length=128)


class AccountCreateResponse(BaseModel):
    account_id: str
    broker_id: str
    email: str
    name: str


class ProfileResponse(BaseModel):
    account_id: str
    email: Optional[str]
    name: str
    broker_id: str
    broker_name: str
    is_admin: bool
    is_demo: bool
    profile_locked: bool


class ProfileUpdateRequest(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    email: Optional[str] = Field(default=None, min_length=3, max_length=255)
    password: Optional[str] = Field(default=None, min_length=1, max_length=128)


def _require_demo() -> None:
    if not settings.demo_mode:
        raise HTTPException(status_code=404, detail="not found")


def _profile(
    account: DemoAccountRegistry,
    principal: BrokerPrincipal,
    broker: Broker,
) -> ProfileResponse:
    profile = account.profile(principal_session(principal), broker.is_demo)
    return ProfileResponse(
        account_id=profile.account_id,
        email=profile.email,
        name=profile.name,
        broker_id=broker.id,
        broker_name=broker.name,
        is_admin=profile.is_admin,
        is_demo=profile.is_demo,
        profile_locked=profile.profile_locked,
    )


def principal_session(principal: BrokerPrincipal):
    return AccountSession(
        account_id=principal.account_id,
        identifier=principal.actor if principal.is_admin else principal.subject,
        name=principal.actor,
        broker_id=principal.broker_id,
        is_admin=principal.is_admin,
    )


@router.get("/demo/brokers", response_model=list[DemoBrokerResponse])
def demo_brokers(
    principal: Optional[BrokerPrincipal] = Depends(get_optional_principal),
    db: Session = Depends(get_db),
) -> list[DemoBrokerResponse]:
    _require_demo()
    broker_filter = None if principal is None or principal.is_admin else principal.broker_id
    return [
        DemoBrokerResponse(id=broker.id, name=broker.name, is_demo=broker.is_demo)
        for broker in db.scalars(
            select(Broker)
            .where(Broker.id == broker_filter if broker_filter else True)
            .order_by(Broker.name, Broker.id)
        ).all()
    ]


@router.post("/demo/auth", response_model=DemoAuthResponse)
def demo_auth(
    request: DemoAuthRequest,
    db: Session = Depends(get_db),
    accounts: DemoAccountRegistry = Depends(account_registry),
) -> DemoAuthResponse:
    _require_demo()
    broker = db.get(Broker, request.broker_id)
    if broker is None:
        raise HTTPException(status_code=404, detail="broker not found")
    try:
        session = accounts.authenticate(request.identifier, request.password, broker.id)
    except (AccountAuthenticationError, AccountValidationError) as exc:
        raise HTTPException(status_code=401, detail="invalid credentials") from exc
    token = issue_authenticated_token(
        broker_id=broker.id,
        account_id=session.account_id,
        actor=session.name,
        subject=session.identifier,
        is_admin=session.is_admin,
    )
    return DemoAuthResponse(
        access_token=token,
        broker_id=broker.id,
        account_id=session.account_id,
        is_admin=session.is_admin,
    )


@router.post("/demo/accounts", response_model=AccountCreateResponse, status_code=201)
def create_demo_account(
    request: AccountCreateRequest,
    db: Session = Depends(get_db),
    accounts: DemoAccountRegistry = Depends(account_registry),
) -> AccountCreateResponse:
    _require_demo()
    broker = db.get(Broker, request.broker_id)
    if broker is None:
        raise HTTPException(status_code=404, detail="broker not found")
    if broker.is_demo:
        raise HTTPException(status_code=403, detail="demo broker accounts are locked")
    try:
        session = accounts.create(broker.id, request.name, request.email, request.password)
    except AccountValidationError as exc:
        status = 409 if "already registered" in str(exc) else 422
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    return AccountCreateResponse(
        account_id=session.account_id,
        broker_id=broker.id,
        email=session.identifier,
        name=session.name,
    )


@router.get("/me", response_model=ProfileResponse)
def current_profile(
    broker_id: Optional[str] = Query(default=None),
    principal: BrokerPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
    accounts: DemoAccountRegistry = Depends(account_registry),
) -> ProfileResponse:
    _require_demo()
    selected_broker_id = broker_id or principal.broker_id
    if not principal.is_admin and selected_broker_id != principal.broker_id:
        raise HTTPException(status_code=403, detail="broker identity mismatch")
    broker = db.get(Broker, selected_broker_id)
    if broker is None:
        raise HTTPException(status_code=404, detail="broker not found")
    return _profile(accounts, principal, broker)


@router.patch("/me", response_model=ProfileResponse)
def update_profile(
    request: ProfileUpdateRequest,
    principal: BrokerPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
    accounts: DemoAccountRegistry = Depends(account_registry),
) -> ProfileResponse:
    _require_demo()
    broker = db.get(Broker, principal.broker_id)
    if broker is None:
        raise HTTPException(status_code=404, detail="broker not found")
    try:
        updated = accounts.update(
            principal_session(principal),
            broker.is_demo,
            request.name,
            request.email,
            request.password,
        )
    except AccountPermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except AccountAuthenticationError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except AccountValidationError as exc:
        status = 409 if "already registered" in str(exc) else 422
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    next_principal = BrokerPrincipal(
        broker_id=broker.id,
        actor=updated.name,
        subject=updated.identifier,
        account_id=updated.account_id,
        is_admin=False,
    )
    return _profile(accounts, next_principal, broker)
