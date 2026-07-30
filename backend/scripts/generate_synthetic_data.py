"""Generate the deterministic synthetic TMS exports used by the demo dataset.

The output is intentionally boring to reproduce: fixed IDs, fixed timestamps,
and compact, sorted JSON.  Each TMS has its own broker and source namespace.
"""

# Scenario declarations intentionally keep each record on one readable line.
# ruff: noqa: E501

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = ROOT / "data"
START = date(2026, 7, 6)
SLOTS = (0, 6, 12, 18)
CENTRAL_OFFSET = "-05:00"


@dataclass(frozen=True)
class Scenario:
    number: int
    pickup: Tuple[str, str, str, str]
    delivery: Tuple[str, str, str, str]
    equipment: str
    customer: str
    carrier: str
    distance_miles: Decimal
    weight_lbs: Decimal
    sell: Decimal
    buy: Decimal
    start_slot: int


SCENARIOS = (
    Scenario(1, ("Sugar Land", "TX", "77478", "Houston"), ("Carrollton", "TX", "75006", "DFW"), "Reefer", "CUST-GULF", "CARR-ALPHA", Decimal("244.0"), Decimal("42000.0"), Decimal("2850.00"), Decimal("2200.00"), 0),
    Scenario(2, ("Plano", "TX", "75024", "DFW"), ("Katy", "TX", "77494", "Houston"), "Dry Van", "CUST-NORTH", "CARR-BRAVO", Decimal("271.0"), Decimal("36000.0"), Decimal("2525.00"), Decimal("1900.00"), 0),
    Scenario(3, ("Pearland", "TX", "77584", "Houston"), ("Schertz", "TX", "78154", "San Antonio"), "Flatbed", "CUST-GULF", "CARR-CHARLIE", Decimal("205.0"), Decimal("38000.0"), Decimal("2310.00"), Decimal("1725.00"), 6),
    Scenario(4, ("New Braunfels", "TX", "78130", "San Antonio"), ("McKinney", "TX", "75070", "DFW"), "Dry Van", "CUST-SOUTH", "CARR-DELTA", Decimal("286.0"), Decimal("33000.0"), Decimal("2680.00"), Decimal("2050.00"), 6),
    Scenario(5, ("Arlington", "TX", "76011", "DFW"), ("Missouri City", "TX", "77459", "Houston"), "Reefer", "CUST-NORTH", "CARR-ALPHA", Decimal("248.0"), Decimal("41000.0"), Decimal("2910.00"), Decimal("2260.00"), 12),
    Scenario(6, ("Cypress", "TX", "77429", "Houston"), ("Boerne", "TX", "78006", "San Antonio"), "Dry Van", "CUST-GULF", "CARR-ECHO", Decimal("218.0"), Decimal("29000.0"), Decimal("2195.00"), Decimal("1640.00"), 12),
    Scenario(7, ("Georgetown", "TX", "78626", "San Antonio"), ("Irving", "TX", "75039", "DFW"), "Flatbed", "CUST-SOUTH", "CARR-DELTA", Decimal("242.0"), Decimal("35000.0"), Decimal("2490.00"), Decimal("1840.00"), 18),
    Scenario(8, ("The Woodlands", "TX", "77380", "Houston"), ("Round Rock", "TX", "78664", "DFW"), "Reefer", "CUST-GULF", "CARR-CHARLIE", Decimal("190.0"), Decimal("39000.0"), Decimal("2380.00"), Decimal("1780.00"), 18),
)

DAY11_SCENARIOS = (
    Scenario(101, ("Dallas", "TX", "75201", "DFW"), ("Houston", "TX", "77002", "Houston"), "Dry Van", "CUST-DAY11", "CARR-ALPHA", Decimal("239.0"), Decimal("30000.0"), Decimal("2450.00"), Decimal("1800.00"), 40),
    Scenario(102, ("San Antonio", "TX", "78205", "San Antonio"), ("Katy", "TX", "77494", "Houston"), "Reefer", "CUST-DAY11", "CARR-ECHO", Decimal("214.0"), Decimal("28000.0"), Decimal("2300.00"), Decimal("1700.00"), 40),
)


def slot_datetime(slot: int) -> datetime:
    day, hour = divmod(slot, 4)
    return datetime.combine(START + timedelta(days=day), datetime.min.time()).replace(
        hour=SLOTS[hour], tzinfo=timezone(timedelta(hours=-5))
    )


def filename(slot: int) -> str:
    value = slot_datetime(slot)
    return value.strftime("%Y-%m-%dT%H-%M_sync.json")


def iso(value: datetime) -> str:
    return value.isoformat(timespec="seconds")


def utc_compact(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000+0000")


def active_scenarios(slot: int) -> List[Scenario]:
    candidates = [item for item in SCENARIOS if item.start_slot <= slot < item.start_slot + 6]
    return candidates or list(SCENARIOS[-2:])


def lifecycle(slot: int, start: int) -> Tuple[str, int]:
    if start >= 40:
        return "active", 20
    age = slot - start
    if age < 1:
        return "planned", 10
    if age < 2:
        return "active", 20
    if age < 3:
        return "covered", 30
    if age < 4:
        return "in_transit", 40
    if age < 5:
        return "delivered", 50
    return "completed", 90


def source_timestamp(scenario: Scenario, slot: int) -> datetime:
    return slot_datetime(max(scenario.start_slot, slot))


def scenario_rates(scenario: Scenario, slot: int) -> Tuple[Decimal, Decimal]:
    status, _ = lifecycle(slot, scenario.start_slot)
    if status in {"planned", "active"}:
        return scenario.sell, Decimal("0.00")
    correction = Decimal("75.00") if scenario.number == 1 and slot >= 3 else Decimal("0.00")
    return scenario.sell + correction, scenario.buy


def scheduled_times(scenario: Scenario) -> Tuple[datetime, datetime]:
    created = slot_datetime(scenario.start_slot)
    return created + timedelta(hours=12), created + timedelta(hours=24)


def freightflow_payload(slot: int, records: Sequence[Scenario]) -> dict:
    synced = slot_datetime(slot)
    loads = []
    for scenario in records:
        status, _ = lifecycle(slot, scenario.start_slot)
        updated = source_timestamp(scenario, slot)
        sell, buy = scenario_rates(scenario, slot)
        carrier = None if status in {"planned", "active"} else {
            "carrierMasterId": scenario.carrier,
            "name": carrier_name(scenario.carrier),
            "mcNumber": carrier_mc(scenario.carrier),
            "dotNumber": carrier_dot(scenario.carrier),
            "phoneNumber": carrier_phone(scenario.carrier),
        }
        pickup_ready, delivery_ready = scheduled_times(scenario)
        loads.append({
            "shipmentId": f"FF-{scenario.number:03d}",
            "status": {"planned": "Quoting", "active": "Booking", "covered": "Dispatched", "in_transit": "En Route", "delivered": "Delivered", "completed": "Completed"}[status],
            "mileage": scenario.distance_miles + (Decimal("2.0") if scenario.number == 1 and slot >= 3 else Decimal("0.0")),
            "totalSell": sell,
            "totalBuy": None if status in {"planned", "active"} else buy,
            "customer": {"customerId": scenario.customer, "name": customer_name(scenario.customer)},
            "carrier": carrier,
            "equipment": scenario.equipment,
            "weightTotal": scenario.weight_lbs,
            "stops": [
                ff_stop(scenario.pickup, "Pickup", pickup_ready, updated if status in {"in_transit", "delivered", "completed"} else None),
                ff_stop(scenario.delivery, "Dropoff", delivery_ready, updated if status in {"delivered", "completed"} else None),
            ],
            "createdDate": iso(slot_datetime(scenario.start_slot)),
            "lastModifiedDate": iso(updated),
        })
    return {"syncedAt": iso(synced), "loads": loads}


def ff_stop(place: Tuple[str, str, str, str], kind: str, ready: datetime, actual: Optional[datetime]) -> dict:
    return {
        "stopType": kind,
        "city": place[0],
        "state": place[1],
        "zipCode": place[2],
        "estimatedReadyDateTime": iso(ready),
        "estimatedCloseDateTime": iso(ready + timedelta(hours=8)),
        "actualDepartureDateTime": iso(actual) if actual else None,
    }


def hauldesk_payload(slot: int, records: Sequence[Scenario], known_rates: Dict[str, int]) -> dict:
    synced = slot_datetime(slot)
    loads = []
    carriers = []
    rates = []
    for scenario in records:
        status, status_code = lifecycle(slot, scenario.start_slot)
        updated = source_timestamp(scenario, slot)
        pickup_ready, delivery_ready = scheduled_times(scenario)
        carrier_ref = None if status in {"planned", "active"} else scenario.carrier
        loads.append({
            "load_num": f"HD-{scenario.number:03d}", "status_code": status_code,
            "customer_code": scenario.customer, "customer_name": customer_name(scenario.customer),
            "carrier_ref": carrier_ref, "equip": scenario.equipment,
            "weight_kg": (scenario.weight_lbs / Decimal("2.2046226218487757")).quantize(Decimal("0.01")),
            "dist_km": (scenario.distance_miles / Decimal("0.621371192237334")).quantize(Decimal("0.01")),
            "pu_city": scenario.pickup[0], "pu_state": scenario.pickup[1], "pu_zip": scenario.pickup[2],
            "pu_date": pickup_ready.strftime("%Y-%m-%d"),
            "pu_departed_at": central_string(updated) if status in {"in_transit", "delivered", "completed"} else None,
            "del_city": scenario.delivery[0], "del_state": scenario.delivery[1], "del_zip": scenario.delivery[2],
            "del_date": delivery_ready.strftime("%Y-%m-%d"),
            "del_arrived_at": central_string(updated) if status in {"delivered", "completed"} else None,
            "entered_at": central_string(slot_datetime(scenario.start_slot)), "updated_at": central_string(updated),
        })
        if carrier_ref:
            carriers.append({
                "carrier_id": scenario.carrier, "carrier_name": carrier_name(scenario.carrier),
                "mc_no": carrier_mc(scenario.carrier), "dot_no": carrier_dot(scenario.carrier),
                "home_city": carrier_home(scenario.carrier)[0], "home_state": "TX", "phone": carrier_phone(scenario.carrier),
            })
        if status not in {"planned", "active"} and f"{scenario.number}-bill" not in known_rates:
            bill, pay = scenario_rates(scenario, slot)
            rates.extend([
                rate_row(known_rates, scenario, "bill", "LINEHAUL", bill, updated),
                rate_row(known_rates, scenario, "pay", "LINEHAUL", pay, updated),
            ])
        if scenario.number == 1 and slot >= 3 and f"{scenario.number}-adjustment" not in known_rates:
            rates.append(rate_row(known_rates, scenario, "bill", "ADJUSTMENT", Decimal("75.00"), updated, "adjustment"))
    return {"synced_at": central_string(synced), "loads": loads, "carriers": carriers, "rates": rates}


def rate_row(known: Dict[str, int], scenario: Scenario, side: str, code: str, amount: Decimal, created: datetime, suffix: str = "base") -> dict:
    key = f"{scenario.number}-{side}" if suffix == "base" else f"{scenario.number}-{suffix}"
    sequence = known.setdefault(key, len(known) + 1)
    return {"rate_id": f"RATE-{sequence:04d}", "load_num": f"HD-{scenario.number:03d}", "side": side, "code": code, "amount_usd": amount, "created_at": central_string(created)}


def central_string(value: datetime) -> str:
    return value.replace(tzinfo=None).strftime("%Y-%m-%d %H:%M:%S")


def brokeros_payload(slot: int, records: Sequence[Scenario]) -> dict:
    synced = slot_datetime(slot).astimezone(timezone.utc)
    references = {}
    for scenario in records:
        references.update({
            f"LOC-{scenario.number}-P": location_ref(scenario.pickup, f"{scenario.pickup[0]} Crossdock"),
            f"LOC-{scenario.number}-D": location_ref(scenario.delivery, f"{scenario.delivery[0]} Distribution"),
            f"CUST-{scenario.number}": {"type": "Account", "record_type": "Customer", "Name": customer_name(scenario.customer)},
        })
        if slot - scenario.start_slot >= 2:
            references[f"CARRIER-{scenario.number}"] = {"type": "Account", "record_type": "Carrier", "Name": carrier_name(scenario.carrier)}
    records_out = []
    for scenario in records:
        status, _ = lifecycle(slot, scenario.start_slot)
        updated = source_timestamp(scenario, slot)
        sell, buy = scenario_rates(scenario, slot)
        records_out.append({
            "Id": f"BROKEROS-{scenario.number:03d}", "Name": f"BOS{scenario.number:06d}",
            "bos__Load_Status__c": {"planned": "Quotes Requested", "active": "Ready to Book", "covered": "Booked", "in_transit": "In Transit", "delivered": "Delivered", "completed": "Paid"}[status],
            "bos__Distance_Miles__c": scenario.distance_miles,
            "bos__Customer__c": f"CUST-{scenario.number}",
            "bos__Carrier__c": f"CARRIER-{scenario.number}" if status not in {"planned", "active"} else None,
            "bos__Equipment_Type__c": scenario.equipment,
            "bos__Customer_Rate__c": sell,
            "bos__Carrier_Rate__c": None if status in {"planned", "active"} else buy,
            "bos__Stops__r": [
                bos_stop(
                    1,
                    True,
                    False,
                    f"LOC-{scenario.number}-P",
                    scheduled_times(scenario)[0],
                    updated if status in {"in_transit", "delivered", "completed"} else None,
                ),
                bos_stop(
                    2,
                    False,
                    True,
                    f"LOC-{scenario.number}-D",
                    scheduled_times(scenario)[1],
                    updated if status in {"delivered", "completed"} else None,
                ),
            ],
            "bos__Line_Items__r": [{"bos__Commodity__c": "General freight", "bos__Weight__c": scenario.weight_lbs, "bos__Weight_Units__c": "pounds", "bos__Pallet_Count__c": Decimal("20")}],
            "CreatedDate": utc_compact(slot_datetime(scenario.start_slot)), "LastModifiedDate": utc_compact(updated),
        })
    return {"synced_at": utc_compact(synced), "records": records_out, "referenced_records": references}


def location_ref(place: Tuple[str, str, str, str], name: str) -> dict:
    return {"type": "Location", "Name": name, "bos__City__c": place[0], "bos__State__c": place[1], "bos__Postal_Code__c": place[2]}


def bos_stop(sequence: int, pickup: bool, dropoff: bool, location: str, scheduled: datetime, arrival: Optional[datetime]) -> dict:
    return {"bos__Number__c": Decimal(sequence), "bos__Is_Pickup__c": pickup, "bos__Is_Dropoff__c": dropoff, "bos__Location__c": location, "bos__Scheduled_Date__c": scheduled.strftime("%Y-%m-%d"), "bos__Arrival_Time__c": utc_compact(arrival) if arrival else None}


def customer_name(customer: str) -> str:
    return {
        "CUST-GULF": "Gulf Coast Foods",
        "CUST-NORTH": "Northstar Retail",
        "CUST-SOUTH": "Alamo Industrial",
        "CUST-DAY11": "Day Eleven Retail",
    }[customer]


def carrier_name(carrier: str) -> str:
    return {"CARR-ALPHA": "Lone Star Logistics", "CARR-BRAVO": "Prairie State Freight", "CARR-CHARLIE": "Triangle Heavy Haul", "CARR-DELTA": "Hill Country Carriers", "CARR-ECHO": "Bluebonnet Transport"}[carrier]


def carrier_mc(carrier: str) -> str:
    return {"CARR-ALPHA": "MC-120001", "CARR-BRAVO": "MC-120002", "CARR-CHARLIE": "MC-120003", "CARR-DELTA": "MC-120004", "CARR-ECHO": "MC-120005"}[carrier]


def carrier_dot(carrier: str) -> str:
    return {"CARR-ALPHA": "DOT-310001", "CARR-BRAVO": "DOT-310002", "CARR-CHARLIE": "DOT-310003", "CARR-DELTA": "DOT-310004", "CARR-ECHO": "DOT-310005"}[carrier]


def carrier_phone(carrier: str) -> str:
    return f"214-555-{1000 + int(carrier[-1], 36) % 9000:04d}"


def carrier_home(carrier: str) -> Tuple[str, str]:
    return {"CARR-ALPHA": ("Houston", "TX"), "CARR-BRAVO": ("Plano", "TX"), "CARR-CHARLIE": ("San Antonio", "TX"), "CARR-DELTA": ("New Braunfels", "TX"), "CARR-ECHO": ("Cypress", "TX")}[carrier]


def dump(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def generate(root: Path = DATA_ROOT, clean: bool = False) -> List[Path]:
    outputs: List[Path] = []
    destinations = {
        "tms_a_freightflow": freightflow_payload,
        "tms_b_hauldesk": hauldesk_payload,
        "tms_c_brokeros": brokeros_payload,
    }
    rate_state: Dict[str, int] = {}
    expected_names = {filename(slot) for slot in range(44)}
    for directory_name, builder in destinations.items():
        directory = root / directory_name
        directory.mkdir(parents=True, exist_ok=True)
        if clean:
            for old in directory.glob("*.json"):
                if old.name in expected_names:
                    old.unlink()
        for slot in range(44):
            records = DAY11_SCENARIOS if slot >= 40 else active_scenarios(slot)
            if directory_name == "tms_a_freightflow":
                payload = builder(slot, records)
            elif directory_name == "tms_b_hauldesk":
                payload = builder(slot, records, rate_state)
            else:
                payload = builder(slot, records)
            path = directory / filename(slot)
            dump(path, payload)
            outputs.append(path)
    return outputs


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DATA_ROOT)
    parser.add_argument("--clean", action="store_true", help="Remove all dated sync files before regeneration (preserves unrelated .json files)")
    args = parser.parse_args()
    paths = generate(args.root, clean=args.clean)
    print(f"generated {len(paths)} files under {args.root}")


if __name__ == "__main__":
    main()
