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
OPERATIONAL_START = date(2026, 7, 29)
HISTORICAL_SLOTS = tuple(range(44))
OPERATIONAL_SLOTS = tuple(
    range((OPERATIONAL_START - START).days * 4, (OPERATIONAL_START - START).days * 4 + 16)
)
SYNC_SLOTS = HISTORICAL_SLOTS + OPERATIONAL_SLOTS


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
    schedule_offset_days: int = 0
    forced_status: Optional[str] = None


def historical_scenario(
    number: int,
    pickup: Tuple[str, str, str, str],
    delivery: Tuple[str, str, str, str],
    equipment: str,
    customer: str,
    carrier: str,
    distance_miles: str,
    weight_lbs: str,
    sell: str,
    buy: str,
) -> Scenario:
    return Scenario(
        number,
        pickup,
        delivery,
        equipment,
        customer,
        carrier,
        Decimal(distance_miles),
        Decimal(weight_lbs),
        Decimal(sell),
        Decimal(buy),
        (number - 1) * 2,
    )


# One load starts every two syncs. Each is exported through all six lifecycle states,
# so every historical file contains only records that were created or substantively changed.
SCENARIOS = (
    historical_scenario(
        1,
        ("Sugar Land", "TX", "77478", "Houston"),
        ("Carrollton", "TX", "75006", "DFW"),
        "Reefer",
        "CUST-GULF",
        "CARR-ALPHA",
        "244.0",
        "42000.0",
        "2850.00",
        "2200.00",
    ),
    historical_scenario(
        2,
        ("Dallas", "TX", "75201", "DFW"),
        ("Houston", "TX", "77002", "Houston"),
        "Dry Van",
        "CUST-NORTH",
        "CARR-BRAVO",
        "250.0",
        "34000.0",
        "2525.00",
        "1900.00",
    ),
    historical_scenario(
        3,
        ("Pearland", "TX", "77584", "Houston"),
        ("Schertz", "TX", "78154", "San Antonio"),
        "Reefer",
        "CUST-GULF",
        "CARR-ALPHA",
        "205.0",
        "38000.0",
        "2310.00",
        "1725.00",
    ),
    historical_scenario(
        4,
        ("Dallas", "TX", "75201", "DFW"),
        ("Houston", "TX", "77002", "Houston"),
        "Dry Van",
        "CUST-NORTH",
        "CARR-BRAVO",
        "252.0",
        "35000.0",
        "2575.00",
        "1950.00",
    ),
    historical_scenario(
        5,
        ("Arlington", "TX", "76011", "DFW"),
        ("Missouri City", "TX", "77459", "Houston"),
        "Reefer",
        "CUST-NORTH",
        "CARR-ALPHA",
        "248.0",
        "41000.0",
        "2910.00",
        "2260.00",
    ),
    historical_scenario(
        6,
        ("Dallas", "TX", "75201", "DFW"),
        ("Houston", "TX", "77002", "Houston"),
        "Dry Van",
        "CUST-GULF",
        "CARR-BRAVO",
        "247.0",
        "32000.0",
        "2490.00",
        "1880.00",
    ),
    historical_scenario(
        7,
        ("Georgetown", "TX", "78626", "Austin"),
        ("Irving", "TX", "75039", "DFW"),
        "Flatbed",
        "CUST-SOUTH",
        "CARR-ALPHA",
        "230.0",
        "35000.0",
        "2490.00",
        "1840.00",
    ),
    historical_scenario(
        8,
        ("Dallas", "TX", "75201", "DFW"),
        ("Houston", "TX", "77002", "Houston"),
        "Dry Van",
        "CUST-NORTH",
        "CARR-BRAVO",
        "255.0",
        "36000.0",
        "2625.00",
        "1980.00",
    ),
    historical_scenario(
        9,
        ("The Woodlands", "TX", "77380", "Houston"),
        ("Round Rock", "TX", "78664", "Austin"),
        "Reefer",
        "CUST-GULF",
        "CARR-ALPHA",
        "190.0",
        "39000.0",
        "2380.00",
        "1780.00",
    ),
    historical_scenario(
        10,
        ("Dallas", "TX", "75201", "DFW"),
        ("Houston", "TX", "77002", "Houston"),
        "Dry Van",
        "CUST-NORTH",
        "CARR-BRAVO",
        "249.0",
        "33000.0",
        "2540.00",
        "1910.00",
    ),
    historical_scenario(
        11,
        ("Cypress", "TX", "77429", "Houston"),
        ("Boerne", "TX", "78006", "San Antonio"),
        "Reefer",
        "CUST-GULF",
        "CARR-ALPHA",
        "218.0",
        "29000.0",
        "2195.00",
        "1640.00",
    ),
    historical_scenario(
        12,
        ("Dallas", "TX", "75201", "DFW"),
        ("Houston", "TX", "77002", "Houston"),
        "Dry Van",
        "CUST-GULF",
        "CARR-BRAVO",
        "251.0",
        "37000.0",
        "2595.00",
        "1960.00",
    ),
    historical_scenario(
        13,
        ("New Braunfels", "TX", "78130", "San Antonio"),
        ("McKinney", "TX", "75070", "DFW"),
        "Flatbed",
        "CUST-SOUTH",
        "CARR-ALPHA",
        "286.0",
        "33000.0",
        "2680.00",
        "2050.00",
    ),
    historical_scenario(
        14,
        ("Dallas", "TX", "75201", "DFW"),
        ("Houston", "TX", "77002", "Houston"),
        "Dry Van",
        "CUST-NORTH",
        "CARR-BRAVO",
        "246.0",
        "34500.0",
        "2510.00",
        "1890.00",
    ),
    historical_scenario(
        15,
        ("San Marcos", "TX", "78666", "Austin"),
        ("Temple", "TX", "76501", "Austin"),
        "Reefer",
        "CUST-SOUTH",
        "CARR-ALPHA",
        "72.0",
        "28000.0",
        "1420.00",
        "980.00",
    ),
    historical_scenario(
        16,
        ("Dallas", "TX", "75201", "DFW"),
        ("Houston", "TX", "77002", "Houston"),
        "Dry Van",
        "CUST-GULF",
        "CARR-BRAVO",
        "253.0",
        "35500.0",
        "2610.00",
        "1975.00",
    ),
    historical_scenario(
        17,
        ("Frisco", "TX", "75034", "DFW"),
        ("Denton", "TX", "76201", "DFW"),
        "Flatbed",
        "CUST-NORTH",
        "CARR-DELTA",
        "29.0",
        "31000.0",
        "1680.00",
        "1210.00",
    ),
    historical_scenario(
        18,
        ("Baytown", "TX", "77520", "Houston"),
        ("Pasadena", "TX", "77506", "Houston"),
        "Reefer",
        "CUST-GULF",
        "CARR-ECHO",
        "24.0",
        "30000.0",
        "1860.00",
        "1320.00",
    ),
)

DAY11_SCENARIOS = (
    Scenario(
        101,
        ("Dallas", "TX", "75201", "DFW"),
        ("Houston", "TX", "77002", "Houston"),
        "Dry Van",
        "CUST-DAY11",
        "CARR-ALPHA",
        Decimal("239.0"),
        Decimal("30000.0"),
        Decimal("2450.00"),
        Decimal("1800.00"),
        40,
    ),
    Scenario(
        102,
        ("San Antonio", "TX", "78205", "San Antonio"),
        ("Katy", "TX", "77494", "Houston"),
        "Reefer",
        "CUST-DAY11",
        "CARR-ECHO",
        Decimal("214.0"),
        Decimal("28000.0"),
        Decimal("2300.00"),
        Decimal("1700.00"),
        40,
    ),
)

OPERATIONAL_SCENARIOS = (
    Scenario(
        201,
        ("Dallas", "TX", "75201", "DFW"),
        ("Houston", "TX", "77002", "Houston"),
        "Dry Van",
        "CUST-RECENT",
        "CARR-BRAVO",
        Decimal("250.0"),
        Decimal("34000.0"),
        Decimal("2550.00"),
        Decimal("2000.00"),
        92,
    ),
    Scenario(
        202,
        ("Sugar Land", "TX", "77478", "Houston"),
        ("San Antonio", "TX", "78205", "San Antonio"),
        "Reefer",
        "CUST-RECENT",
        "CARR-CHARLIE",
        Decimal("210.0"),
        Decimal("30000.0"),
        Decimal("2420.00"),
        Decimal("1810.00"),
        94,
    ),
    Scenario(
        203,
        ("Georgetown", "TX", "78626", "Austin"),
        ("Irving", "TX", "75039", "DFW"),
        "Flatbed",
        "CUST-RECENT",
        "CARR-DELTA",
        Decimal("230.0"),
        Decimal("35000.0"),
        Decimal("2480.00"),
        Decimal("1850.00"),
        97,
    ),
    Scenario(
        301,
        ("Dallas", "TX", "75201", "DFW"),
        ("Houston", "TX", "77002", "Houston"),
        "Dry Van",
        "CUST-TODAY",
        "CARR-ECHO",
        Decimal("248.0"),
        Decimal("36000.0"),
        Decimal("2585.00"),
        Decimal("0.00"),
        103,
        forced_status="active",
    ),
    Scenario(
        302,
        ("Arlington", "TX", "76011", "DFW"),
        ("Katy", "TX", "77494", "Houston"),
        "Reefer",
        "CUST-TODAY",
        "CARR-ALPHA",
        Decimal("265.0"),
        Decimal("40000.0"),
        Decimal("2860.00"),
        Decimal("0.00"),
        104,
        forced_status="active",
    ),
    Scenario(
        303,
        ("Dallas", "TX", "75201", "DFW"),
        ("San Antonio", "TX", "78205", "San Antonio"),
        "Flatbed",
        "CUST-TODAY",
        "CARR-CHARLIE",
        Decimal("275.0"),
        Decimal("38000.0"),
        Decimal("2765.00"),
        Decimal("0.00"),
        105,
        forced_status="active",
    ),
    Scenario(
        401,
        ("Sugar Land", "TX", "77478", "Houston"),
        ("Carrollton", "TX", "75006", "DFW"),
        "Reefer",
        "CUST-FUTURE",
        "CARR-ALPHA",
        Decimal("244.0"),
        Decimal("42000.0"),
        Decimal("2950.00"),
        Decimal("0.00"),
        104,
        35,
    ),
    Scenario(
        402,
        ("Plano", "TX", "75024", "DFW"),
        ("New Braunfels", "TX", "78130", "San Antonio"),
        "Dry Van",
        "CUST-FUTURE",
        "CARR-BRAVO",
        Decimal("290.0"),
        Decimal("36000.0"),
        Decimal("2690.00"),
        Decimal("0.00"),
        105,
        42,
    ),
    Scenario(
        403,
        ("Houston", "TX", "77002", "Houston"),
        ("Round Rock", "TX", "78664", "Austin"),
        "Flatbed",
        "CUST-FUTURE",
        "CARR-DELTA",
        Decimal("195.0"),
        Decimal("32000.0"),
        Decimal("2350.00"),
        Decimal("0.00"),
        106,
        49,
    ),
)

CORRECTIONS = {
    1: (3, Decimal("75.00"), Decimal("100.00")),
    201: (95, Decimal("50.00"), Decimal("80.00")),
}


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
    return [item for item in SCENARIOS if item.start_slot <= slot < item.start_slot + 6]


def lifecycle(slot: int, start: int, forced_status: Optional[str] = None) -> Tuple[str, int]:
    if forced_status == "active":
        return "active", 20
    if start == 40:
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
    status, _ = lifecycle(slot, scenario.start_slot, scenario.forced_status)
    if status in {"planned", "active"}:
        return scenario.sell, Decimal("0.00")
    correction_slot, sell_correction, pay_correction = CORRECTIONS.get(
        scenario.number, (None, Decimal("0.00"), Decimal("0.00"))
    )
    if correction_slot is None or slot < correction_slot:
        sell_correction = pay_correction = Decimal("0.00")
    return scenario.sell + sell_correction, scenario.buy + pay_correction


def scenario_distance(scenario: Scenario, slot: int) -> Decimal:
    distance = scenario.distance_miles
    if scenario.forced_status == "active" or scenario.start_slot == 40:
        distance += Decimal(slot - scenario.start_slot) / Decimal("2.0")
    return distance


def scheduled_times(scenario: Scenario) -> Tuple[datetime, datetime]:
    created = slot_datetime(scenario.start_slot) + timedelta(days=scenario.schedule_offset_days)
    return created + timedelta(hours=12), created + timedelta(hours=24)


def freightflow_payload(slot: int, records: Sequence[Scenario]) -> dict:
    synced = slot_datetime(slot)
    loads = []
    for scenario in records:
        status, _ = lifecycle(slot, scenario.start_slot, scenario.forced_status)
        updated = source_timestamp(scenario, slot)
        sell, buy = scenario_rates(scenario, slot)
        carrier = (
            None
            if status in {"planned", "active"}
            else {
                "carrierMasterId": scenario.carrier,
                "name": carrier_name(scenario.carrier),
                "mcNumber": carrier_mc(scenario.carrier),
                "dotNumber": carrier_dot(scenario.carrier),
                "phoneNumber": carrier_phone(scenario.carrier),
            }
        )
        pickup_ready, delivery_ready = scheduled_times(scenario)
        loads.append(
            {
                "shipmentId": f"FF-{scenario.number:03d}",
                "status": {
                    "planned": "Quoting",
                    "active": "Booking",
                    "covered": "Dispatched",
                    "in_transit": "En Route",
                    "delivered": "Delivered",
                    "completed": "Completed",
                }[status],
                "mileage": scenario_distance(scenario, slot)
                + (Decimal("2.0") if scenario.number == 1 and slot >= 3 else Decimal("0.0")),
                "totalSell": sell,
                "totalBuy": None if status in {"planned", "active"} else buy,
                "customer": {
                    "customerId": scenario.customer,
                    "name": customer_name(scenario.customer),
                },
                "carrier": carrier,
                "equipment": scenario.equipment,
                "weightTotal": scenario.weight_lbs,
                "stops": [
                    ff_stop(
                        scenario.pickup,
                        "Pickup",
                        pickup_ready,
                        updated if status in {"in_transit", "delivered", "completed"} else None,
                    ),
                    ff_stop(
                        scenario.delivery,
                        "Dropoff",
                        delivery_ready,
                        updated if status in {"delivered", "completed"} else None,
                    ),
                ],
                "createdDate": iso(slot_datetime(scenario.start_slot)),
                "lastModifiedDate": iso(updated),
            }
        )
    return {"syncedAt": iso(synced), "loads": loads}


def ff_stop(
    place: Tuple[str, str, str, str], kind: str, ready: datetime, actual: Optional[datetime]
) -> dict:
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
        status, status_code = lifecycle(slot, scenario.start_slot, scenario.forced_status)
        updated = source_timestamp(scenario, slot)
        pickup_ready, delivery_ready = scheduled_times(scenario)
        carrier_ref = None if status in {"planned", "active"} else scenario.carrier
        loads.append(
            {
                "load_num": f"HD-{scenario.number:03d}",
                "status_code": status_code,
                "customer_code": scenario.customer,
                "customer_name": customer_name(scenario.customer),
                "carrier_ref": carrier_ref,
                "equip": {"Dry Van": "V", "Reefer": "R", "Flatbed": "F"}[scenario.equipment],
                "weight_kg": (scenario.weight_lbs / Decimal("2.2046226218487757")).quantize(
                    Decimal("0.01")
                ),
                "dist_km": (
                    scenario_distance(scenario, slot) / Decimal("0.621371192237334")
                ).quantize(Decimal("0.01")),
                "pu_city": scenario.pickup[0],
                "pu_state": scenario.pickup[1],
                "pu_zip": scenario.pickup[2],
                "pu_date": pickup_ready.strftime("%Y-%m-%d"),
                "pu_departed_at": central_string(updated)
                if status in {"in_transit", "delivered", "completed"}
                else None,
                "del_city": scenario.delivery[0],
                "del_state": scenario.delivery[1],
                "del_zip": scenario.delivery[2],
                "del_date": delivery_ready.strftime("%Y-%m-%d"),
                "del_arrived_at": central_string(updated)
                if status in {"delivered", "completed"}
                else None,
                "entered_at": central_string(slot_datetime(scenario.start_slot)),
                "updated_at": central_string(updated),
            }
        )
        if carrier_ref:
            carriers.append(
                {
                    "carrier_id": scenario.carrier,
                    "carrier_name": carrier_name(scenario.carrier),
                    "mc_no": carrier_mc(scenario.carrier),
                    "dot_no": carrier_dot(scenario.carrier),
                    "home_city": carrier_home(scenario.carrier)[0],
                    "home_state": "TX",
                    "phone": carrier_phone(scenario.carrier),
                }
            )
        if status not in {"planned", "active"} and f"{scenario.number}-bill" not in known_rates:
            bill, pay = scenario_rates(scenario, slot)
            rates.extend(
                [
                    rate_row(known_rates, scenario, "bill", "LINEHAUL", bill, updated),
                    rate_row(known_rates, scenario, "pay", "LINEHAUL", pay, updated),
                ]
            )
        correction = CORRECTIONS.get(scenario.number)
        if (
            correction is not None
            and slot >= correction[0]
            and f"{scenario.number}-adjustment" not in known_rates
        ):
            rates.append(
                rate_row(
                    known_rates,
                    scenario,
                    "bill",
                    "ADJUSTMENT",
                    correction[1],
                    updated,
                    "adjustment",
                )
            )
        if (
            correction is not None
            and slot >= correction[0]
            and f"{scenario.number}-pay-adjustment" not in known_rates
        ):
            rates.append(
                rate_row(
                    known_rates,
                    scenario,
                    "pay",
                    "ADJUSTMENT",
                    correction[2],
                    updated,
                    "pay-adjustment",
                )
            )
    return {
        "synced_at": central_string(synced),
        "loads": loads,
        "carriers": carriers,
        "rates": rates,
    }


def rate_row(
    known: Dict[str, int],
    scenario: Scenario,
    side: str,
    code: str,
    amount: Decimal,
    created: datetime,
    suffix: str = "base",
) -> dict:
    key = f"{scenario.number}-{side}" if suffix == "base" else f"{scenario.number}-{suffix}"
    sequence = known.setdefault(key, len(known) + 1)
    return {
        "rate_id": f"RATE-{sequence:04d}",
        "load_num": f"HD-{scenario.number:03d}",
        "side": side,
        "code": code,
        "amount_usd": amount,
        "created_at": central_string(created),
    }


def central_string(value: datetime) -> str:
    return value.replace(tzinfo=None).strftime("%Y-%m-%d %H:%M:%S")


def brokeros_payload(slot: int, records: Sequence[Scenario]) -> dict:
    synced = slot_datetime(slot).astimezone(timezone.utc)
    references = {}
    for scenario in records:
        references.update(
            {
                f"LOC-{scenario.number}-P": location_ref(
                    scenario.pickup, f"{scenario.pickup[0]} Crossdock"
                ),
                f"LOC-{scenario.number}-D": location_ref(
                    scenario.delivery, f"{scenario.delivery[0]} Distribution"
                ),
                f"CUST-{scenario.number}": {
                    "type": "Account",
                    "record_type": "Customer",
                    "Name": customer_name(scenario.customer),
                },
            }
        )
        if slot - scenario.start_slot >= 2:
            references[f"CARRIER-{scenario.carrier}"] = {
                "type": "Account",
                "record_type": "Carrier",
                "Name": carrier_name(scenario.carrier),
            }
    records_out = []
    for scenario in records:
        status, _ = lifecycle(slot, scenario.start_slot, scenario.forced_status)
        updated = source_timestamp(scenario, slot)
        sell, buy = scenario_rates(scenario, slot)
        records_out.append(
            {
                "Id": f"BROKEROS-{scenario.number:03d}",
                "Name": f"BOS{scenario.number:06d}",
                "bos__Load_Status__c": {
                    "planned": "Quotes Requested",
                    "active": "Ready to Book",
                    "covered": "Booked",
                    "in_transit": "In Transit",
                    "delivered": "Delivered",
                    "completed": "Paid",
                }[status],
                "bos__Distance_Miles__c": scenario_distance(scenario, slot),
                "bos__Customer__c": f"CUST-{scenario.number}",
                "bos__Carrier__c": f"CARRIER-{scenario.carrier}"
                if status not in {"planned", "active"}
                else None,
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
                "bos__Line_Items__r": [
                    {
                        "bos__Commodity__c": "General freight",
                        "bos__Weight__c": scenario.weight_lbs,
                        "bos__Weight_Units__c": "pounds",
                        "bos__Pallet_Count__c": Decimal("20"),
                    }
                ],
                "CreatedDate": utc_compact(slot_datetime(scenario.start_slot)),
                "LastModifiedDate": utc_compact(updated),
            }
        )
    return {
        "synced_at": utc_compact(synced),
        "records": records_out,
        "referenced_records": references,
    }


def location_ref(place: Tuple[str, str, str, str], name: str) -> dict:
    return {
        "type": "Location",
        "Name": name,
        "bos__City__c": place[0],
        "bos__State__c": place[1],
        "bos__Postal_Code__c": place[2],
    }


def bos_stop(
    sequence: int,
    pickup: bool,
    dropoff: bool,
    location: str,
    scheduled: datetime,
    arrival: Optional[datetime],
) -> dict:
    return {
        "bos__Number__c": Decimal(sequence),
        "bos__Is_Pickup__c": pickup,
        "bos__Is_Dropoff__c": dropoff,
        "bos__Location__c": location,
        "bos__Scheduled_Date__c": scheduled.strftime("%Y-%m-%d"),
        "bos__Arrival_Time__c": utc_compact(arrival) if arrival else None,
    }


def records_for_slot(slot: int) -> List[Scenario]:
    if slot < OPERATIONAL_SLOTS[0]:
        return DAY11_SCENARIOS if slot >= 40 else active_scenarios(slot)

    if slot == OPERATIONAL_SLOTS[-1]:
        return [scenario for scenario in OPERATIONAL_SCENARIOS if 301 <= scenario.number <= 303]

    recent = [
        scenario
        for scenario in OPERATIONAL_SCENARIOS
        if 201 <= scenario.number <= 203 and scenario.start_slot <= slot < scenario.start_slot + 6
    ]
    current = [
        scenario
        for scenario in OPERATIONAL_SCENARIOS
        if 301 <= scenario.number <= 303 and scenario.start_slot <= slot <= scenario.start_slot + 1
    ]
    future = [
        scenario
        for scenario in OPERATIONAL_SCENARIOS
        if 401 <= scenario.number <= 403 and scenario.start_slot == slot
    ]
    return recent + current + future


def customer_name(customer: str) -> str:
    return {
        "CUST-GULF": "Gulf Coast Foods",
        "CUST-NORTH": "Northstar Retail",
        "CUST-SOUTH": "Alamo Industrial",
        "CUST-DAY11": "Day Eleven Retail",
        "CUST-RECENT": "Recent Demo Shipper",
        "CUST-TODAY": "Today Demo Shipper",
        "CUST-FUTURE": "September Demo Shipper",
    }[customer]


def carrier_name(carrier: str) -> str:
    return {
        "CARR-ALPHA": "Lone Star Logistics",
        "CARR-BRAVO": "Prairie State Freight",
        "CARR-CHARLIE": "Triangle Heavy Haul",
        "CARR-DELTA": "Hill Country Carriers",
        "CARR-ECHO": "Bluebonnet Transport",
    }[carrier]


def carrier_mc(carrier: str) -> str:
    return {
        "CARR-ALPHA": "MC-120001",
        "CARR-BRAVO": "MC-120002",
        "CARR-CHARLIE": "MC-120003",
        "CARR-DELTA": "MC-120004",
        "CARR-ECHO": "MC-120005",
    }[carrier]


def carrier_dot(carrier: str) -> str:
    return {
        "CARR-ALPHA": "DOT-310001",
        "CARR-BRAVO": "DOT-310002",
        "CARR-CHARLIE": "DOT-310003",
        "CARR-DELTA": "DOT-310004",
        "CARR-ECHO": "DOT-310005",
    }[carrier]


def carrier_phone(carrier: str) -> str:
    return f"214-555-{1000 + int(carrier[-1], 36) % 9000:04d}"


def carrier_home(carrier: str) -> Tuple[str, str]:
    return {
        "CARR-ALPHA": ("Houston", "TX"),
        "CARR-BRAVO": ("Plano", "TX"),
        "CARR-CHARLIE": ("San Antonio", "TX"),
        "CARR-DELTA": ("New Braunfels", "TX"),
        "CARR-ECHO": ("Cypress", "TX"),
    }[carrier]


def dump(path: Path, payload: dict) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"
    )


def generate(root: Path = DATA_ROOT, clean: bool = False) -> List[Path]:
    outputs: List[Path] = []
    destinations = {
        "tms_a_freightflow": freightflow_payload,
        "tms_b_hauldesk": hauldesk_payload,
        "tms_c_brokeros": brokeros_payload,
    }
    rate_state: Dict[str, int] = {}
    expected_names = {filename(slot) for slot in SYNC_SLOTS}
    for directory_name, builder in destinations.items():
        directory = root / directory_name
        directory.mkdir(parents=True, exist_ok=True)
        if clean:
            for old in directory.glob("*.json"):
                if old.name in expected_names:
                    old.unlink()
        for slot in SYNC_SLOTS:
            records = records_for_slot(slot)
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
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Remove all dated sync files before regeneration (preserves unrelated .json files)",
    )
    args = parser.parse_args()
    paths = generate(args.root, clean=args.clean)
    print(f"generated {len(paths)} files under {args.root}")


if __name__ == "__main__":
    main()
