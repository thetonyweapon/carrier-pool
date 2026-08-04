import base64
import binascii
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from functools import lru_cache
from typing import Optional
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, build_opener
from urllib.request import Request as UrlRequest

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import Broker

_bearer = HTTPBearer(auto_error=False)
_MAX_IDP_RESPONSE_BYTES = 1_048_576


class _RejectRedirects(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError("identity provider redirects are not allowed")


_jwks_opener = build_opener(_RejectRedirects())
_OIDC_ALLOWED_ALGORITHMS = (
    "RS256",
    "RS384",
    "RS512",
    "PS256",
    "PS384",
    "PS512",
    "ES256",
    "ES384",
    "ES512",
    "EdDSA",
)


@dataclass(frozen=True)
class BrokerPrincipal:
    broker_id: str
    actor: str
    subject: str
    account_id: str = ""
    is_admin: bool = False


def issue_demo_token(broker_id: str, actor: str = "demo-user") -> str:
    if not settings.demo_mode:
        raise ValueError("mock authentication is only enabled for demo mode")
    if settings.auth_mode != "mock" or not settings.allow_mock_auth:
        raise ValueError("mock authentication is not enabled")
    if not settings.auth_secret:
        raise ValueError("AUTH_SECRET is not configured")
    return issue_authenticated_token(
        broker_id=broker_id,
        account_id=actor,
        actor=actor,
        subject=actor,
    )


def issue_authenticated_token(
    broker_id: str,
    account_id: str,
    actor: str,
    subject: str,
    is_admin: bool = False,
) -> str:
    payload = _encode_payload(
        {
            "aud": settings.auth_audience,
            "account_id": account_id,
            "admin": is_admin,
            "broker_id": broker_id,
            "actor": actor,
            "expires_at": int(time.time()) + settings.auth_token_ttl_seconds,
            "iss": settings.auth_issuer,
            "sub": subject,
        }
    )
    return f"{payload}.{_signature(payload)}"


def get_current_principal(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> BrokerPrincipal:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="bearer authentication required")
    if settings.auth_mode == "oidc":
        return _get_oidc_principal(credentials.credentials)
    if (
        not settings.demo_mode
        or settings.auth_mode != "mock"
        or not settings.allow_mock_auth
        or not settings.auth_secret
    ):
        raise HTTPException(status_code=503, detail="authentication is not configured")
    try:
        payload, signature = credentials.credentials.split(".", 1)
        expected = _signature(payload)
        if not hmac.compare_digest(signature, expected):
            raise ValueError("invalid signature")
        decoded = json.loads(_decode_payload(payload))
        audience = str(decoded["aud"])
        broker_id = str(decoded["broker_id"])
        actor = str(decoded["actor"])
        expires_at = int(decoded["expires_at"])
        issuer = str(decoded["iss"])
        subject = str(decoded["sub"])
        account_id = str(decoded.get("account_id", subject))
        is_admin = decoded.get("admin") is True
    except (
        ValueError,
        KeyError,
        TypeError,
        json.JSONDecodeError,
        binascii.Error,
        UnicodeError,
        OverflowError,
    ) as exc:
        raise HTTPException(status_code=401, detail="invalid bearer token") from exc
    if (
        expires_at <= int(time.time())
        or audience != settings.auth_audience
        or issuer != settings.auth_issuer
        or not broker_id
        or not actor
        or not subject
        or not account_id
    ):
        raise HTTPException(status_code=401, detail="invalid bearer token")
    return BrokerPrincipal(
        broker_id=broker_id,
        actor=actor,
        subject=subject,
        account_id=account_id,
        is_admin=is_admin,
    )


def _get_oidc_principal(token: str) -> BrokerPrincipal:
    try:
        signing_key = _jwks_client(settings.auth_jwks_url or "").get_signing_key_from_jwt(token)
        decoded = jwt.decode(
            token,
            signing_key.key,
            algorithms=_OIDC_ALLOWED_ALGORITHMS,
            audience=settings.auth_audience,
            issuer=settings.auth_issuer,
            options={"require": ["exp", "iss", "aud", "sub"]},
        )
        subject = _required_claim(decoded, "sub")
        broker_id = _required_claim(decoded, settings.auth_tenant_claim)
    except (jwt.PyJWTError, KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=401, detail="invalid bearer token") from exc
    return BrokerPrincipal(
        broker_id=broker_id,
        actor=subject,
        subject=subject,
        account_id=subject,
    )


def get_optional_principal(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> Optional[BrokerPrincipal]:
    if credentials is None or not settings.demo_mode:
        return None
    return get_current_principal(credentials)


def require_broker_principal(
    broker_id: str,
    principal: BrokerPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> BrokerPrincipal:
    if not principal.is_admin and principal.broker_id != broker_id:
        raise HTTPException(status_code=403, detail="broker identity mismatch")
    if db.get(Broker, broker_id) is None:
        raise HTTPException(status_code=404, detail="broker not found")
    if principal.is_admin:
        return BrokerPrincipal(
            broker_id=broker_id,
            actor=principal.actor,
            subject=principal.subject,
            account_id=principal.account_id,
            is_admin=True,
        )
    return principal


def _encode_payload(value: dict[str, object]) -> str:
    raw = json.dumps(value, separators=(",", ":"), sort_keys=True).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_payload(value: str) -> str:
    padded = value + "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(padded.encode()).decode()


def _signature(payload: str) -> str:
    return hmac.new(
        (settings.auth_secret or "").encode(), payload.encode(), hashlib.sha256
    ).hexdigest()


def _required_claim(payload: dict[str, object], claim_name: str) -> str:
    value = payload[claim_name]
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{claim_name} must be a non-empty string")
    return value


@lru_cache(maxsize=8)
def _jwks_client(url: str) -> PyJWKClient:
    return _SecureJWKClient(url, timeout=5)


class _SecureJWKClient(PyJWKClient):
    def fetch_data(self) -> dict:
        configured = urlparse(self.uri)
        try:
            with _jwks_opener.open(UrlRequest(self.uri), timeout=5) as response:
                final = urlparse(response.geturl())
                if final.scheme != "https" or final.hostname != configured.hostname:
                    raise ValueError("JWKS endpoint redirected to an untrusted URL")
                body = response.read(_MAX_IDP_RESPONSE_BYTES + 1)
                if len(body) > _MAX_IDP_RESPONSE_BYTES:
                    raise ValueError("JWKS response is too large")
                payload = json.loads(body)
        except Exception as exc:
            raise jwt.PyJWKClientError("JWKS fetch failed") from exc
        if not isinstance(payload, dict):
            raise jwt.PyJWKClientError("JWKS response was not an object")
        return payload
