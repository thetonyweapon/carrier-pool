import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import Optional

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import Broker

_bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class BrokerPrincipal:
    broker_id: str
    actor: str


def issue_demo_token(broker_id: str, actor: str = "demo-user") -> str:
    if not settings.auth_secret:
        raise ValueError("AUTH_SECRET is not configured")
    payload = _encode_payload(
        {
            "broker_id": broker_id,
            "actor": actor,
            "expires_at": int(time.time()) + settings.auth_token_ttl_seconds,
        }
    )
    return f"{payload}.{_signature(payload)}"


def get_current_principal(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> BrokerPrincipal:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="bearer authentication required")
    if not settings.auth_secret:
        raise HTTPException(status_code=503, detail="authentication is not configured")
    try:
        payload, signature = credentials.credentials.split(".", 1)
        expected = _signature(payload)
        if not hmac.compare_digest(signature, expected):
            raise ValueError("invalid signature")
        decoded = json.loads(_decode_payload(payload))
        broker_id = str(decoded["broker_id"])
        actor = str(decoded["actor"])
        expires_at = int(decoded["expires_at"])
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=401, detail="invalid bearer token") from exc
    if expires_at <= int(time.time()) or not broker_id or not actor:
        raise HTTPException(status_code=401, detail="expired bearer token")
    return BrokerPrincipal(broker_id=broker_id, actor=actor)


def require_broker_principal(
    broker_id: str,
    principal: BrokerPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> BrokerPrincipal:
    if principal.broker_id != broker_id:
        raise HTTPException(status_code=403, detail="broker identity mismatch")
    if db.get(Broker, broker_id) is None:
        raise HTTPException(status_code=404, detail="broker not found")
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
