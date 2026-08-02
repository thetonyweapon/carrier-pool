import re
from dataclasses import dataclass
from typing import Optional

NORMALIZATION_VERSION = "tx-metro-v1"

_ZIP_TO_METRO = {
    "75006": ("DFW", "Dallas-Fort Worth"),
    "75024": ("DFW", "Dallas-Fort Worth"),
    "75039": ("DFW", "Dallas-Fort Worth"),
    "75070": ("DFW", "Dallas-Fort Worth"),
    "75201": ("DFW", "Dallas-Fort Worth"),
    "76011": ("DFW", "Dallas-Fort Worth"),
    "77002": ("HOUSTON", "Houston"),
    "77380": ("HOUSTON", "Houston"),
    "77429": ("HOUSTON", "Houston"),
    "77459": ("HOUSTON", "Houston"),
    "77478": ("HOUSTON", "Houston"),
    "77494": ("HOUSTON", "Houston"),
    "77584": ("HOUSTON", "Houston"),
    "78006": ("SAN_ANTONIO", "San Antonio"),
    "78130": ("SAN_ANTONIO", "San Antonio"),
    "78154": ("SAN_ANTONIO", "San Antonio"),
    "78205": ("SAN_ANTONIO", "San Antonio"),
    "78626": ("AUSTIN", "Austin"),
    "78664": ("AUSTIN", "Austin"),
}

_CITY_TO_METRO = {
    ("ARLINGTON", "TX"): ("DFW", "Dallas-Fort Worth"),
    ("CARROLLTON", "TX"): ("DFW", "Dallas-Fort Worth"),
    ("DALLAS", "TX"): ("DFW", "Dallas-Fort Worth"),
    ("IRVING", "TX"): ("DFW", "Dallas-Fort Worth"),
    ("MCKINNEY", "TX"): ("DFW", "Dallas-Fort Worth"),
    ("PLANO", "TX"): ("DFW", "Dallas-Fort Worth"),
    ("BOERNE", "TX"): ("SAN_ANTONIO", "San Antonio"),
    ("CYPRESS", "TX"): ("HOUSTON", "Houston"),
    ("GEORGETOWN", "TX"): ("AUSTIN", "Austin"),
    ("HOUSTON", "TX"): ("HOUSTON", "Houston"),
    ("KATY", "TX"): ("HOUSTON", "Houston"),
    ("MISSOURI CITY", "TX"): ("HOUSTON", "Houston"),
    ("NEW BRAUNFELS", "TX"): ("SAN_ANTONIO", "San Antonio"),
    ("PEARLAND", "TX"): ("HOUSTON", "Houston"),
    ("ROUND ROCK", "TX"): ("AUSTIN", "Austin"),
    ("SAN ANTONIO", "TX"): ("SAN_ANTONIO", "San Antonio"),
    ("SCHERTZ", "TX"): ("SAN_ANTONIO", "San Antonio"),
    ("SUGAR LAND", "TX"): ("HOUSTON", "Houston"),
    ("THE WOODLANDS", "TX"): ("HOUSTON", "Houston"),
}


def _match_method(has_postal_metro: bool, has_metro: bool) -> str:
    if has_postal_metro:
        return "postal_code"
    if has_metro:
        return "city_state"
    return "unmapped"


@dataclass(frozen=True)
class NormalizedLocation:
    city: str
    state: str
    postal_code: str
    exact_key: str
    metro_key: Optional[str]
    metro_name: Optional[str]
    match_method: str


def normalize_location(city: str, state: str, postal_code: str) -> NormalizedLocation:
    normalized_city = " ".join(city.strip().upper().split())
    normalized_state = state.strip().upper()
    postal_match = re.match(r"^(\d{5})(?:-?\d{4})?$", postal_code.strip())
    postal5 = postal_match.group(1) if postal_match else postal_code.strip().upper()

    postal_metro = _ZIP_TO_METRO.get(postal5)
    metro = postal_metro
    if metro is None:
        metro = _CITY_TO_METRO.get((normalized_city, normalized_state))
    exact_key = f"US:{normalized_state}:ZIP:{postal5}"
    if not postal_match:
        exact_key = f"US:{normalized_state}:CITY:{normalized_city.replace(' ', '_')}"

    return NormalizedLocation(
        city=normalized_city,
        state=normalized_state,
        postal_code=postal5,
        exact_key=exact_key,
        metro_key=metro[0] if metro else None,
        metro_name=metro[1] if metro else None,
        match_method=_match_method(postal_metro is not None, metro is not None),
    )
