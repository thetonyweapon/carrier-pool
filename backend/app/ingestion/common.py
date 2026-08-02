import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Broker, Carrier, CarrierIdentity


class CarrierIdentityConflictError(ValueError):
    """Carrier identifiers disagree with an existing broker-scoped identity."""


class IngestionLimitError(ValueError):
    """A source file exceeds configured resource limits."""


def enforce_ingestion_file_size(path: Path) -> None:
    if path.stat().st_size > settings.ingestion_max_file_bytes:
        raise IngestionLimitError(
            f"sync file exceeds {settings.ingestion_max_file_bytes} byte limit"
        )


def enforce_ingestion_limits(raw_contents: bytes, payload: object) -> None:
    if len(raw_contents) > settings.ingestion_max_file_bytes:
        raise IngestionLimitError(
            f"sync file exceeds {settings.ingestion_max_file_bytes} byte limit"
        )
    if not isinstance(payload, dict):
        return
    records = payload.get("loads", payload.get("records", []))
    if isinstance(records, list) and len(records) > settings.ingestion_max_records:
        raise IngestionLimitError(
            f"sync file exceeds {settings.ingestion_max_records} record limit"
        )


def normalize_carrier_identifier(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    normalized = re.sub(r"[\s-]", "", str(value)).upper()
    if normalized.startswith("MC"):
        normalized = normalized[2:]
    elif normalized.startswith("DOT"):
        normalized = normalized[3:]
    if not normalized.isdigit():
        return None
    normalized = normalized.lstrip("0")
    return normalized or None


def upsert_carrier_identity(
    session: Session,
    broker_id: str,
    mc_number: Optional[str],
    dot_number: Optional[str],
    observed_at: datetime,
) -> Optional[CarrierIdentity]:
    normalized_mc = normalize_carrier_identifier(mc_number)
    normalized_dot = normalize_carrier_identifier(dot_number)
    if normalized_mc is None and normalized_dot is None:
        return None

    # Identity updates are broker-wide, so source-level locks alone are insufficient
    # when two TMS files are ingested concurrently.
    session.scalar(select(Broker).where(Broker.id == broker_id).with_for_update())
    match_conditions = []
    if normalized_mc is not None:
        match_conditions.append(CarrierIdentity.normalized_mc_number == normalized_mc)
    if normalized_dot is not None:
        match_conditions.append(CarrierIdentity.normalized_dot_number == normalized_dot)
    identities = session.scalars(
        select(CarrierIdentity)
        .where(
            CarrierIdentity.broker_id == broker_id,
            or_(*match_conditions),
        )
        .with_for_update()
    ).all()
    if len(identities) > 1:
        if normalized_mc is None or normalized_dot is None:
            raise CarrierIdentityConflictError(
                f"MC/DOT evidence maps to multiple carrier identities for broker {broker_id}"
            )
        mc_matches = [item for item in identities if item.normalized_mc_number == normalized_mc]
        dot_matches = [item for item in identities if item.normalized_dot_number == normalized_dot]
        if len(mc_matches) != 1 or len(dot_matches) != 1 or mc_matches[0].id == dot_matches[0].id:
            raise CarrierIdentityConflictError(
                f"MC {normalized_mc} and DOT {normalized_dot} map to conflicting carrier identities"
            )
        identity = mc_matches[0]
        duplicate = dot_matches[0]
        _merge_identity(session, identity, duplicate, normalized_mc, normalized_dot, observed_at)
    elif identities:
        identity = identities[0]
        _validate_identity_pair(identity, normalized_mc, normalized_dot)
        changed = False
        if identity.normalized_mc_number is None and normalized_mc is not None:
            identity.normalized_mc_number = normalized_mc
            changed = True
        if identity.normalized_dot_number is None and normalized_dot is not None:
            identity.normalized_dot_number = normalized_dot
            changed = True
        if changed:
            identity.updated_at = observed_at
    else:
        identity = CarrierIdentity(
            broker_id=broker_id,
            normalized_mc_number=normalized_mc,
            normalized_dot_number=normalized_dot,
            created_at=observed_at,
            updated_at=observed_at,
        )
        session.add(identity)
    session.flush()
    return identity


def _validate_identity_pair(
    identity: CarrierIdentity,
    normalized_mc: Optional[str],
    normalized_dot: Optional[str],
) -> None:
    if (
        normalized_mc is not None
        and identity.normalized_mc_number is not None
        and identity.normalized_mc_number != normalized_mc
    ) or (
        normalized_dot is not None
        and identity.normalized_dot_number is not None
        and identity.normalized_dot_number != normalized_dot
    ):
        raise CarrierIdentityConflictError(
            f"MC/DOT evidence conflicts with carrier identity {identity.id}"
        )


def _merge_identity(
    session: Session,
    identity: CarrierIdentity,
    duplicate: CarrierIdentity,
    normalized_mc: str,
    normalized_dot: str,
    observed_at: datetime,
) -> None:
    _validate_identity_pair(identity, normalized_mc, normalized_dot)
    _validate_identity_pair(duplicate, normalized_mc, normalized_dot)
    for carrier in session.scalars(
        select(Carrier).where(Carrier.carrier_identity_id == duplicate.id)
    ):
        carrier.carrier_identity_id = identity.id
    session.flush()
    session.delete(duplicate)
    session.flush()
    identity.normalized_mc_number = normalized_mc
    identity.normalized_dot_number = normalized_dot
    identity.updated_at = observed_at
