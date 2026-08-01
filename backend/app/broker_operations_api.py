from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import (
    Broker,
    BrokerSource,
    Carrier,
    CarrierIdentity,
    Customer,
    EquipmentType,
    Load,
    LoadStatus,
    LoadStop,
    PlatformAssignment,
    PlatformAssignmentEvent,
)

router = APIRouter(tags=["broker operations"])


class Summary(BaseModel):
    id: str
    name: str


class CarrierSummary(Summary):
    mc_number: Optional[str] = None
    dot_number: Optional[str] = None
    phone_number: Optional[str] = None


class Freshness(BaseModel):
    last_synced_at: datetime
    age_seconds: int


class AssignmentSummary(BaseModel):
    state: str
    carrier: Optional[CarrierSummary] = None
    candidate_id: Optional[str] = None
    assignment_version: int
    assigned_at: Optional[datetime] = None


class LoadListItem(BaseModel):
    id: str
    display_number: str
    status: str
    equipment_type: str
    weight_lbs: Optional[str] = None
    distance_miles: Optional[str] = None
    customer: Summary
    source: Summary
    carrier: Optional[CarrierSummary] = None
    origin: Optional[dict] = None
    destination: Optional[dict] = None
    next_schedule: Optional[object] = None
    customer_rate: Optional[str] = None
    carrier_rate: Optional[str] = None
    margin: Optional[str] = None
    freshness: Freshness
    assignment: AssignmentSummary


class LoadListResponse(BaseModel):
    broker_id: str
    items: list[LoadListItem]
    page: int
    page_size: int
    total: int


class StopResponse(BaseModel):
    id: str
    sequence_number: int
    stop_type: str
    city: str
    state: str
    postal_code: str
    scheduled_date: Optional[date] = None
    scheduled_start_at: Optional[datetime] = None
    scheduled_end_at: Optional[datetime] = None
    actual_arrived_at: Optional[datetime] = None
    actual_departed_at: Optional[datetime] = None
    location_name: Optional[str] = None


class LoadDetailResponse(LoadListItem):
    stops: list[StopResponse]


class AssignmentRequest(BaseModel):
    carrier_id: Optional[str] = None
    candidate_id: Optional[str] = None
    expected_assignment_version: int = 0
    demo_actor: str = "demo-user"


class AssignmentResponse(AssignmentSummary):
    broker_id: str
    load_id: str


class CandidateCarrierResponse(CarrierSummary):
    source_id: str
    home_city: Optional[str] = None
    home_state: Optional[str] = None


class CandidateDetailResponse(BaseModel):
    broker_id: str
    candidate_id: str
    carrier_identity_id: Optional[str] = None
    name: str
    mc_number: Optional[str] = None
    dot_number: Optional[str] = None
    carriers: list[CandidateCarrierResponse]


def _money(value: Optional[Decimal]) -> Optional[str]:
    """Format a monetary value as a 2-decimal string."""
    return format(value, ".2f") if value is not None else None


def _decimal(value: Optional[Decimal]) -> Optional[str]:
    """Format a non-monetary numeric value without forced 2-decimal places."""
    return str(value) if value is not None else None


def _carrier_summary(carrier: Optional[Carrier]) -> Optional[CarrierSummary]:
    if carrier is None:
        return None
    return CarrierSummary(
        id=carrier.id,
        name=carrier.name,
        mc_number=carrier.mc_number,
        dot_number=carrier.dot_number,
        phone_number=carrier.phone_number,
    )


def _freshness(load: Load) -> Freshness:
    now = datetime.now(timezone.utc)
    synced = load.last_synced_at
    # Treat timezone-naive datetimes as UTC (project convention).
    if synced.tzinfo is None:
        synced = synced.replace(tzinfo=timezone.utc)
    return Freshness(last_synced_at=synced, age_seconds=max(0, int((now - synced).total_seconds())))


def _assignment(
    assignment: Optional[PlatformAssignment], carrier: Optional[Carrier]
) -> AssignmentSummary:
    if assignment is None:
        return AssignmentSummary(state="unassigned", assignment_version=0)
    return AssignmentSummary(
        state="assigned",
        carrier=_carrier_summary(carrier),
        candidate_id=assignment.candidate_id,
        assignment_version=assignment.assignment_version,
        assigned_at=assignment.updated_at,
    )


def _stop_location(stop: Optional[LoadStop]) -> Optional[dict]:
    if stop is None:
        return None
    return {"city": stop.city, "state": stop.state, "postal_code": stop.postal_code}


def _load_item(
    load: Load,
    customer: Customer,
    source_name: str,
    source_id: str,
    stops: list[LoadStop],
    canonical_carrier: Optional[Carrier],
    assignment: Optional[PlatformAssignment],
    assigned_carrier: Optional[Carrier],
) -> LoadListItem:
    pickup = next((s for s in stops if s.stop_type.value in ("pickup", "pickup_dropoff")), None)
    delivery = next(
        (s for s in reversed(stops) if s.stop_type.value in ("dropoff", "pickup_dropoff")), None
    )
    schedule = pickup.scheduled_start_at if pickup else None
    if schedule is None and pickup:
        schedule = pickup.scheduled_end_at or pickup.scheduled_date
    return LoadListItem(
        id=load.id,
        display_number=load.display_number,
        status=load.status.value,
        equipment_type=load.equipment_type.value,
        weight_lbs=_decimal(load.weight_lbs),
        distance_miles=_decimal(load.distance_miles),
        customer=Summary(id=customer.id, name=customer.name),
        source=Summary(id=source_id, name=source_name),
        carrier=_carrier_summary(canonical_carrier),
        origin=_stop_location(pickup),
        destination=_stop_location(delivery),
        next_schedule=schedule,
        customer_rate=_money(load.customer_rate),
        carrier_rate=_money(load.carrier_rate),
        margin=_money(load.customer_rate - load.carrier_rate)
        if load.customer_rate is not None and load.carrier_rate is not None
        else None,
        freshness=_freshness(load),
        assignment=_assignment(assignment, assigned_carrier),
    )


def _load_or_404(db: Session, broker_id: str, load_id: str) -> Load:
    load = db.scalar(select(Load).where(Load.broker_id == broker_id, Load.id == load_id))
    if load is None:
        raise HTTPException(status_code=404, detail="load not found")
    return load


def _related(db: Session, load: Load):
    customer = db.get(Customer, load.customer_id)
    source = db.scalar(
        select(BrokerSource).where(
            BrokerSource.broker_id == load.broker_id, BrokerSource.id == load.broker_source_id
        )
    )
    source_name = source.source_name if source is not None else load.broker_source_id
    source_id = load.broker_source_id
    stops = db.scalars(
        select(LoadStop)
        .where(LoadStop.broker_id == load.broker_id, LoadStop.load_id == load.id)
        .order_by(LoadStop.sequence_number)
    ).all()
    assignment = db.scalar(
        select(PlatformAssignment).where(
            PlatformAssignment.broker_id == load.broker_id, PlatformAssignment.load_id == load.id
        )
    )
    assigned_carrier = (
        db.scalar(
            select(Carrier).where(
                Carrier.broker_id == load.broker_id, Carrier.id == assignment.carrier_id
            )
        )
        if assignment
        else None
    )
    canonical_carrier = (
        db.scalar(
            select(Carrier).where(
                Carrier.broker_id == load.broker_id, Carrier.id == load.carrier_id
            )
        )
        if load.carrier_id
        else None
    )
    if customer is None:
        raise HTTPException(status_code=500, detail="load customer is missing")
    return customer, source_name, source_id, stops, assignment, assigned_carrier, canonical_carrier


@router.get("/demo/brokers", response_model=list[Summary])
def demo_brokers(db: Session = Depends(get_db)) -> list[Summary]:
    if not settings.demo_mode:
        raise HTTPException(status_code=404, detail="not found")
    return [
        Summary(id=b.id, name=b.name)
        for b in db.scalars(select(Broker).order_by(Broker.name, Broker.id)).all()
    ]


@router.get("/brokers/{broker_id}/loads", response_model=LoadListResponse)
def loads(
    broker_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    status: Optional[LoadStatus] = None,
    equipment: Optional[EquipmentType] = None,
    assignment_state: Optional[str] = Query(None, pattern="^(assigned|unassigned)$"),
    search: Optional[str] = None,
    db: Session = Depends(get_db),
) -> LoadListResponse:
    pickup_schedule = (
        select(func.min(LoadStop.scheduled_start_at))
        .where(LoadStop.broker_id == broker_id, LoadStop.load_id == Load.id)
        .scalar_subquery()
    )
    query = select(Load).where(Load.broker_id == broker_id)
    if status:
        query = query.where(Load.status == status)
    if equipment:
        query = query.where(Load.equipment_type == equipment)
    if search:
        escaped = search.replace("%", "\\%").replace("_", "\\_")
        term = f"%{escaped}%"
        query = query.where(or_(Load.display_number.ilike(term), Load.id.ilike(term)))
    if assignment_state == "assigned":
        query = query.where(
            select(PlatformAssignment.id)
            .where(PlatformAssignment.broker_id == broker_id, PlatformAssignment.load_id == Load.id)
            .exists()
        )
    if assignment_state == "unassigned":
        query = query.where(
            ~select(PlatformAssignment.id)
            .where(PlatformAssignment.broker_id == broker_id, PlatformAssignment.load_id == Load.id)
            .exists()
        )
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.scalars(
        query.order_by(pickup_schedule.asc().nulls_last(), Load.display_number, Load.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    items = []
    # Batch-load related data to avoid N+1 queries.
    customer_ids = {load.customer_id for load in rows}
    source_ids = {(load.broker_id, load.broker_source_id) for load in rows}
    load_ids = {(load.broker_id, load.id) for load in rows}
    carrier_ids = set()
    customers = {
        c.id: c for c in db.scalars(select(Customer).where(Customer.id.in_(customer_ids))).all()
    }
    sources = {
        (s.broker_id, s.id): s
        for s in db.scalars(
            select(BrokerSource).where(
                BrokerSource.broker_id == broker_id,
                BrokerSource.id.in_([sid for _, sid in source_ids]),
            )
        ).all()
    }
    stops_by_load = {}
    for stop in db.scalars(
        select(LoadStop)
        .where(
            LoadStop.broker_id == broker_id,
            LoadStop.load_id.in_([lid for _, lid in load_ids]),
        )
        .order_by(LoadStop.broker_id, LoadStop.load_id, LoadStop.sequence_number)
    ).all():
        stops_by_load.setdefault((stop.broker_id, stop.load_id), []).append(stop)
    assignments = {
        (a.broker_id, a.load_id): a
        for a in db.scalars(
            select(PlatformAssignment).where(
                PlatformAssignment.broker_id == broker_id,
                PlatformAssignment.load_id.in_([lid for _, lid in load_ids]),
            )
        ).all()
    }
    for a in assignments.values():
        carrier_ids.add(a.carrier_id)
    for load in rows:
        if load.carrier_id:
            carrier_ids.add(load.carrier_id)
    carriers = {
        c.id: c
        for c in db.scalars(
            select(Carrier).where(Carrier.broker_id == broker_id, Carrier.id.in_(carrier_ids))
        ).all()
    }
    for load in rows:
        customer = customers.get(load.customer_id)
        if customer is None:
            raise HTTPException(status_code=500, detail="load customer is missing")
        source = sources.get((load.broker_id, load.broker_source_id))
        source_name = source.source_name if source is not None else load.broker_source_id
        load_stops = stops_by_load.get((load.broker_id, load.id), [])
        assignment = assignments.get((load.broker_id, load.id))
        assigned_carrier = carriers.get(assignment.carrier_id) if assignment else None
        canonical_carrier = carriers.get(load.carrier_id) if load.carrier_id else None
        items.append(
            _load_item(
                load,
                customer,
                source_name,
                load.broker_source_id,
                load_stops,
                canonical_carrier,
                assignment,
                assigned_carrier,
            )
        )
    return LoadListResponse(
        broker_id=broker_id, items=items, page=page, page_size=page_size, total=total
    )


@router.get("/brokers/{broker_id}/loads/{load_id}", response_model=LoadDetailResponse)
def load_detail(broker_id: str, load_id: str, db: Session = Depends(get_db)) -> LoadDetailResponse:
    load = _load_or_404(db, broker_id, load_id)
    customer, source_name, source_id, stops, assignment, assigned_carrier, canonical_carrier = (
        _related(db, load)
    )
    item = _load_item(
        load,
        customer,
        source_name,
        source_id,
        stops,
        canonical_carrier,
        assignment,
        assigned_carrier,
    )
    return LoadDetailResponse(
        **item.model_dump(),
        stops=[StopResponse.model_validate(stop, from_attributes=True) for stop in stops],
    )


@router.post("/brokers/{broker_id}/loads/{load_id}/assignments", response_model=AssignmentResponse)
def assign_load(
    broker_id: str, load_id: str, request: AssignmentRequest, db: Session = Depends(get_db)
) -> AssignmentResponse:
    if not settings.demo_mode:
        raise HTTPException(status_code=404, detail="not found")
    load = _load_or_404(db, broker_id, load_id)
    if load.status != LoadStatus.ACTIVE or load.carrier_id is not None:
        raise HTTPException(
            status_code=409, detail="load is not an active canonical uncovered target"
        )
    assignment = db.scalar(
        select(PlatformAssignment)
        .where(PlatformAssignment.broker_id == broker_id, PlatformAssignment.load_id == load_id)
        .with_for_update()
    )
    current_version = assignment.assignment_version if assignment else 0
    if request.expected_assignment_version != current_version:
        raise HTTPException(status_code=409, detail="assignment version conflict")
    carrier = None
    candidate_id = request.candidate_id
    if request.carrier_id:
        carrier = db.scalar(
            select(Carrier).where(Carrier.broker_id == broker_id, Carrier.id == request.carrier_id)
        )
        if carrier is None:
            raise HTTPException(status_code=422, detail="carrier is not owned by broker")
        if candidate_id is None:
            candidate_id = carrier.id
    elif candidate_id:
        if candidate_id.startswith("identity:"):
            identity_id = candidate_id.split(":", 1)[1]
            carriers = db.scalars(
                select(Carrier).where(
                    Carrier.broker_id == broker_id, Carrier.carrier_identity_id == identity_id
                )
            ).all()
        else:
            canonical_id = candidate_id.removeprefix("carrier:")
            carriers = db.scalars(
                select(Carrier).where(Carrier.broker_id == broker_id, Carrier.id == canonical_id)
            ).all()
        if len(carriers) != 1:
            raise HTTPException(
                status_code=422, detail="candidate must resolve to one broker carrier"
            )
        carrier = carriers[0]
    else:
        raise HTTPException(status_code=422, detail="carrier_id or candidate_id is required")
    now = datetime.now(timezone.utc)
    if assignment:
        assignment.carrier_id = carrier.id
        assignment.candidate_id = candidate_id
        assignment.assignment_version += 1
        assignment.demo_actor = request.demo_actor
        assignment.updated_at = now
    else:
        assignment = PlatformAssignment(
            broker_id=broker_id,
            load_id=load_id,
            carrier_id=carrier.id,
            candidate_id=candidate_id,
            demo_actor=request.demo_actor,
            assignment_version=1,
            created_at=now,
            updated_at=now,
        )
        db.add(assignment)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            raise HTTPException(status_code=409, detail="assignment version conflict")
    db.add(
        PlatformAssignmentEvent(
            broker_id=broker_id,
            assignment_id=assignment.id,
            load_id=load_id,
            carrier_id=carrier.id,
            candidate_id=candidate_id,
            assignment_version=assignment.assignment_version,
            demo_actor=request.demo_actor,
            created_at=now,
        )
    )
    db.commit()
    return AssignmentResponse(
        broker_id=broker_id, load_id=load_id, **_assignment(assignment, carrier).model_dump()
    )


@router.get(
    "/brokers/{broker_id}/carrier-candidates/{candidate_id}", response_model=CandidateDetailResponse
)
def carrier_candidate(
    broker_id: str, candidate_id: str, db: Session = Depends(get_db)
) -> CandidateDetailResponse:
    if candidate_id.startswith("identity:"):
        identity_id = candidate_id.split(":", 1)[1]
        identity = db.scalar(
            select(CarrierIdentity).where(
                CarrierIdentity.broker_id == broker_id, CarrierIdentity.id == identity_id
            )
        )
        carriers = db.scalars(
            select(Carrier)
            .where(Carrier.broker_id == broker_id, Carrier.carrier_identity_id == identity_id)
            .order_by(Carrier.id)
        ).all()
        if identity is None or not carriers:
            raise HTTPException(status_code=404, detail="carrier candidate not found")
        name = carriers[0].name
        mc_number, dot_number = identity.normalized_mc_number, identity.normalized_dot_number
    else:
        canonical_id = candidate_id.removeprefix("carrier:")
        carriers = db.scalars(
            select(Carrier).where(Carrier.broker_id == broker_id, Carrier.id == canonical_id)
        ).all()
        if not carriers:
            raise HTTPException(status_code=404, detail="carrier candidate not found")
        carrier = carriers[0]
        name, mc_number, dot_number = carrier.name, carrier.mc_number, carrier.dot_number
    return CandidateDetailResponse(
        broker_id=broker_id,
        candidate_id=candidate_id,
        carrier_identity_id=carriers[0].carrier_identity_id,
        name=name,
        mc_number=mc_number,
        dot_number=dot_number,
        carriers=[
            CandidateCarrierResponse(
                id=c.id,
                name=c.name,
                mc_number=c.mc_number,
                dot_number=c.dot_number,
                phone_number=c.phone_number,
                source_id=c.broker_source_id,
                home_city=c.home_city,
                home_state=c.home_state,
            )
            for c in carriers
        ],
    )
