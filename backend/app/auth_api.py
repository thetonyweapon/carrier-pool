import json
from typing import Optional
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, build_opener
from urllib.request import Request as UrlRequest

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
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


class _RejectRedirects(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise URLError("identity provider redirects are not allowed")


_MAX_IDP_RESPONSE_BYTES = 1_048_576
_MAX_TOKEN_REQUEST_BYTES = 16_384
_token_opener = build_opener(_RejectRedirects())


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


class OidcTokenRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=4096)
    code_verifier: str = Field(min_length=43, max_length=128)


class OidcTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


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


@router.post("/oidc/token", response_model=OidcTokenResponse)
def exchange_oidc_code(payload: OidcTokenRequest, http_request: Request) -> OidcTokenResponse:
    if settings.demo_mode or not settings.auth_token_url or not settings.auth_client_id:
        raise HTTPException(status_code=404, detail="not found")
    content_length = http_request.headers.get("content-length")
    if content_length is not None and int(content_length) > _MAX_TOKEN_REQUEST_BYTES:
        raise HTTPException(status_code=413, detail="request body is too large")
    form = urlencode(
        {
            "grant_type": "authorization_code",
            "code": payload.code,
            "code_verifier": payload.code_verifier,
            "client_id": settings.auth_client_id,
            "redirect_uri": settings.auth_redirect_uri or "",
        }
    ).encode()
    try:
        with _token_opener.open(
            UrlRequest(
                settings.auth_token_url,
                data=form,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                method="POST",
            ),
            timeout=5,
        ) as response:
            body = response.read(_MAX_IDP_RESPONSE_BYTES + 1)
            if len(body) > _MAX_IDP_RESPONSE_BYTES:
                raise ValueError("identity provider response is too large")
            payload = json.loads(body)
    except (OSError, URLError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=502, detail="identity provider token exchange failed"
        ) from exc
    access_token = payload.get("access_token") if isinstance(payload, dict) else None
    token_type = payload.get("token_type") if isinstance(payload, dict) else None
    if not isinstance(access_token, str) or not access_token.strip() or len(access_token) > 8192:
        raise HTTPException(status_code=502, detail="identity provider returned no access token")
    if not isinstance(token_type, str) or token_type.casefold() != "bearer":
        raise HTTPException(
            status_code=502, detail="identity provider returned an invalid token type"
        )
    return OidcTokenResponse(
        access_token=access_token,
        token_type=token_type,
    )


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
            .order_by(Broker.id)
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
    if request.broker_id != "broker-local":
        raise HTTPException(
            status_code=403,
            detail="self-service accounts are limited to the local sandbox",
        )
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
    selected_broker_id = broker_id or principal.broker_id
    if not principal.is_admin and selected_broker_id != principal.broker_id:
        raise HTTPException(status_code=403, detail="broker identity mismatch")
    broker = db.get(Broker, selected_broker_id)
    if broker is None:
        raise HTTPException(status_code=404, detail="broker not found")
    if not settings.demo_mode:
        return ProfileResponse(
            account_id=principal.account_id,
            email=None,
            name=principal.actor,
            broker_id=broker.id,
            broker_name=broker.name,
            is_admin=principal.is_admin,
            is_demo=False,
            profile_locked=True,
        )
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
