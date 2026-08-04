import hashlib
import os
import re
import stat
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Broker, Carrier, CarrierIdentity
from app.observability import increment


class CarrierIdentityConflictError(ValueError):
    """Carrier identifiers disagree with an existing broker-scoped identity."""


class IngestionLimitError(ValueError):
    """A source file exceeds configured resource limits."""


class IngestionFileSecurityError(ValueError):
    """A queued source file is not a safe regular file."""


@contextmanager
def ingestion_transaction(session: Session, tms_type: str):
    try:
        with session.begin():
            yield
    except Exception as exc:
        increment(
            "carrier_pool_ingestion_transactions_total",
            {
                "tms": tms_type,
                "outcome": "rolled_back",
                "failure_class": exc.__class__.__name__,
            },
        )
        raise
    else:
        increment(
            "carrier_pool_ingestion_transactions_total",
            {"tms": tms_type, "outcome": "committed"},
        )


def enforce_ingestion_file_size(path: Path) -> None:
    _validate_file_path(path)
    fd = _open_verified_descriptor(path)
    try:
        if os.fstat(fd).st_size > settings.ingestion_max_file_bytes:
            raise IngestionLimitError(
                f"sync file exceeds {settings.ingestion_max_file_bytes} byte limit"
            )
    finally:
        os.close(fd)


def read_verified_file(
    path: Path, *, expected_checksum: Optional[str] = None, root: Optional[Path] = None
) -> bytes:
    _validate_file_path(path, root=root)
    fd = _open_verified_descriptor(path)
    try:
        if os.fstat(fd).st_size > settings.ingestion_max_file_bytes:
            raise IngestionLimitError(
                f"sync file exceeds {settings.ingestion_max_file_bytes} byte limit"
            )
        with os.fdopen(fd, "rb") as file:
            fd = -1
            contents = file.read(settings.ingestion_max_file_bytes + 1)
    finally:
        if fd >= 0:
            os.close(fd)
    if len(contents) > settings.ingestion_max_file_bytes:
        raise IngestionLimitError(
            f"sync file exceeds {settings.ingestion_max_file_bytes} byte limit"
        )
    if expected_checksum and hashlib.sha256(contents).hexdigest() != expected_checksum:
        raise IngestionFileSecurityError("ingestion file checksum does not match queued content")
    return contents


def _open_verified_descriptor(path: Path) -> int:
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError as exc:
        raise IngestionFileSecurityError("ingestion path could not be opened safely") from exc
    if not stat.S_ISREG(os.fstat(fd).st_mode):
        os.close(fd)
        raise IngestionFileSecurityError("ingestion path must be a regular file")
    return fd


def _validate_file_path(path: Path, *, root: Optional[Path] = None) -> None:
    if not path.exists():
        raise FileNotFoundError(path)
    if path.is_symlink() or not path.is_file():
        raise IngestionFileSecurityError("ingestion path must be a regular non-symlink file")
    resolved = path.resolve(strict=True)
    if root is not None:
        resolved_root = root.resolve(strict=True)
        if resolved_root not in resolved.parents:
            raise IngestionFileSecurityError("ingestion path escapes the configured root")
    current = path
    while current != current.parent:
        if current.is_symlink():
            raise IngestionFileSecurityError("ingestion path cannot contain symlink components")
        if root is not None and current.resolve() == root.resolve():
            break
        current = current.parent


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


def validate_carrier_identity_transition(
    carrier: Optional[Carrier],
    mc_number: Optional[str],
    dot_number: Optional[str],
) -> None:
    """Reject a source carrier changing to unrelated identifiers."""
    if carrier is None:
        return
    incoming_mc = normalize_carrier_identifier(mc_number)
    incoming_dot = normalize_carrier_identifier(dot_number)
    existing_mc = normalize_carrier_identifier(carrier.mc_number)
    existing_dot = normalize_carrier_identifier(carrier.dot_number)
    if incoming_mc is not None and existing_mc is not None and incoming_mc != existing_mc:
        raise CarrierIdentityConflictError(
            "MC evidence conflicts with the existing carrier identity"
        )
    if incoming_dot is not None and existing_dot is not None and incoming_dot != existing_dot:
        raise CarrierIdentityConflictError(
            "DOT evidence conflicts with the existing carrier identity"
        )


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
