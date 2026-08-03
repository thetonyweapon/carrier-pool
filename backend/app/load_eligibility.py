from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.models import Load, LoadStatus, PlatformAssignment


class LoadNotFound(ValueError):
    pass


class LoadNotEligible(ValueError):
    pass


def require_active_uncovered(session: Session, broker_id: str, load_id: str) -> Load:
    assignment_exists = exists(
        select(PlatformAssignment.id).where(
            PlatformAssignment.broker_id == Load.broker_id,
            PlatformAssignment.load_id == Load.id,
        )
    )
    row = session.execute(
        select(Load, assignment_exists.label("has_assignment")).where(
            Load.broker_id == broker_id, Load.id == load_id
        )
    ).one_or_none()
    if row is None:
        raise LoadNotFound
    load, has_assignment = row
    if load.status != LoadStatus.ACTIVE or load.carrier_id is not None or has_assignment:
        raise LoadNotEligible("load must be active and uncovered")
    return load


def is_active_uncovered(
    session: Session, load: Load, *, allow_assignment_update: bool = False
) -> bool:
    if load.status != LoadStatus.ACTIVE or load.carrier_id is not None:
        return False
    if allow_assignment_update:
        return True
    return (
        session.scalar(
            select(
                exists(
                    select(PlatformAssignment.id).where(
                        PlatformAssignment.broker_id == load.broker_id,
                        PlatformAssignment.load_id == load.id,
                    )
                )
            )
        )
        is False
    )
