from typing import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import LoadStop


def load_stops(
    session: Session, broker_id: str, load_ids: Sequence[str]
) -> dict[str, list[LoadStop]]:
    """Load broker-scoped stops grouped by canonical load id."""
    if not load_ids:
        return {}
    rows = session.scalars(
        select(LoadStop)
        .where(LoadStop.broker_id == broker_id, LoadStop.load_id.in_(load_ids))
        .order_by(LoadStop.load_id, LoadStop.sequence_number)
    ).all()
    result: dict[str, list[LoadStop]] = {}
    for stop in rows:
        result.setdefault(stop.load_id, []).append(stop)
    return result
