"""Validate production Compose CPU and memory limits before deployment."""

from __future__ import annotations

import os
import re
from argparse import ArgumentParser
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Mapping, Optional

CPU_LIMITS = {
    "MIGRATION_CPU_LIMIT": Decimal("1.0"),
    "BACKEND_CPU_LIMIT": Decimal("2.0"),
    "WORKER_CPU_LIMIT": Decimal("2.0"),
    "FRONTEND_CPU_LIMIT": Decimal("1.0"),
}
MEMORY_LIMITS = {
    "MIGRATION_MEMORY_LIMIT": 512 * 1024**2,
    "BACKEND_MEMORY_LIMIT": 2 * 1024**3,
    "WORKER_MEMORY_LIMIT": 2 * 1024**3,
    "FRONTEND_MEMORY_LIMIT": 512 * 1024**2,
}
_MEMORY_PATTERN = re.compile(r"^(?P<amount>[0-9]+(?:\.[0-9]+)?)(?P<unit>[KMGT]i?B?)?$", re.I)
_MEMORY_MULTIPLIERS = {
    "": 1,
    "K": 1000,
    "KB": 1000,
    "KI": 1024,
    "KIB": 1024,
    "M": 1000**2,
    "MB": 1000**2,
    "MI": 1024**2,
    "MIB": 1024**2,
    "G": 1000**3,
    "GB": 1000**3,
    "GI": 1024**3,
    "GIB": 1024**3,
    "T": 1000**4,
    "TB": 1000**4,
    "TI": 1024**4,
    "TIB": 1024**4,
}


def validate_resource_limits(
    environment: Optional[Mapping[str, str]] = None,
    env_file: Optional[Path] = None,
) -> None:
    values = dict(_read_env_file(env_file)) if env_file else {}
    values.update(environment or os.environ)
    environment = values
    errors = []
    for name, maximum in CPU_LIMITS.items():
        raw = environment.get(name, _default_cpu(name))
        try:
            value = Decimal(raw)
        except InvalidOperation:
            errors.append(f"{name} must be a positive decimal CPU value")
            continue
        if not value.is_finite() or value <= 0 or value > maximum:
            errors.append(f"{name} must be greater than 0 and at most {maximum}")
    for name, maximum in MEMORY_LIMITS.items():
        raw = environment.get(name, _default_memory(name))
        match = _MEMORY_PATTERN.fullmatch(raw.strip())
        if match is None:
            errors.append(f"{name} must be a valid memory quantity")
            continue
        unit = (match.group("unit") or "").upper()
        amount = Decimal(match.group("amount")) * _MEMORY_MULTIPLIERS[unit]
        if not amount.is_finite() or amount <= 0 or amount > maximum:
            errors.append(f"{name} must be positive and within its documented maximum")
    if errors:
        raise ValueError("; ".join(errors))


def _default_cpu(name: str) -> str:
    return {"MIGRATION_CPU_LIMIT": "0.50", "FRONTEND_CPU_LIMIT": "0.50"}.get(name, "1.00")


def _default_memory(name: str) -> str:
    return {"MIGRATION_MEMORY_LIMIT": "256M", "FRONTEND_MEMORY_LIMIT": "256M"}.get(name, "1G")


def _read_env_file(path: Path) -> Mapping[str, str]:
    values = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        values[name.strip()] = value.strip().strip('"').strip("'")
    return values


if __name__ == "__main__":
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    args = parser.parse_args()
    validate_resource_limits(env_file=args.env_file)
    print("production resource limits are valid")
