import json
from pathlib import Path

import pytest

from app.config import Settings, settings
from app.ingestion import brokeros, freightflow, hauldesk
from app.ingestion.common import (
    IngestionFileSecurityError,
    IngestionLimitError,
    enforce_ingestion_file_size,
    enforce_ingestion_limits,
    read_verified_file,
)
from scripts.validate_resource_limits import validate_resource_limits


def test_ingestion_file_limit(monkeypatch):
    monkeypatch.setattr(settings, "ingestion_max_file_bytes", 4)

    with pytest.raises(IngestionLimitError, match="byte limit"):
        enforce_ingestion_limits(b"12345", {})


def test_ingestion_path_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "ingestion_max_file_bytes", 4)
    path = Path(tmp_path) / "oversized.json"
    path.write_bytes(b"12345")

    with pytest.raises(IngestionLimitError, match="byte limit"):
        enforce_ingestion_file_size(path)


def test_verified_ingestion_rejects_symlinks_and_checksum_mismatches(tmp_path):
    path = Path(tmp_path) / "payload.json"
    path.write_bytes(b"payload")
    link = Path(tmp_path) / "link.json"
    link.symlink_to(path)

    with pytest.raises(IngestionFileSecurityError):
        read_verified_file(link)
    with pytest.raises(IngestionFileSecurityError, match="checksum"):
        read_verified_file(path, expected_checksum="0" * 64)


def test_verified_ingestion_rejects_path_escape(tmp_path):
    root = Path(tmp_path) / "root"
    root.mkdir()
    outside = Path(tmp_path) / "outside.json"
    outside.write_bytes(b"payload")

    with pytest.raises(IngestionFileSecurityError, match="escapes"):
        read_verified_file(root / ".." / "outside.json", root=root)


def test_ingestion_record_limit(monkeypatch):
    monkeypatch.setattr(settings, "ingestion_max_records", 1)
    payload = {"loads": [{"id": 1}, {"id": 2}]}

    with pytest.raises(IngestionLimitError, match="record limit"):
        enforce_ingestion_limits(json.dumps(payload).encode(), payload)


def test_non_object_payload_is_left_to_schema_validation(monkeypatch):
    monkeypatch.setattr(settings, "ingestion_max_records", 1)

    enforce_ingestion_limits(b"[]", [])


@pytest.mark.parametrize(
    ("parse", "error"),
    [
        (freightflow.ingest_contents, freightflow.InvalidFreightFlowPayloadError),
        (hauldesk._parse_payload, hauldesk.InvalidHaulDeskPayloadError),
        (brokeros._parse_payload, brokeros.InvalidBrokerOSPayloadError),
    ],
)
def test_each_adapter_translates_limit_errors(monkeypatch, parse, error):
    monkeypatch.setattr(settings, "ingestion_max_records", 0)
    payload = json.dumps({"loads": [{}], "records": [{}]}).encode()

    with pytest.raises(error):
        if parse is freightflow.ingest_contents:
            parse(None, "source", "payload.json", payload)
        else:
            parse(payload)


@pytest.mark.parametrize(
    ("name", "value"),
    (
        ("DB_POOL_SIZE", "101"),
        ("DB_MAX_OVERFLOW", "201"),
        ("DB_POOL_TIMEOUT_SECONDS", "301"),
        ("DB_POOL_RECYCLE_SECONDS", "86401"),
        ("DB_STATEMENT_TIMEOUT_MS", "300001"),
        ("DB_IDLE_TRANSACTION_TIMEOUT_MS", "600001"),
        ("INGESTION_MAX_FILE_BYTES", str(100 * 1024 * 1024 + 1)),
        ("INGESTION_MAX_RECORDS", "100001"),
    ),
)
def test_production_resource_limits_reject_unsafe_values(monkeypatch, name, value):
    _set_production_env(monkeypatch)
    monkeypatch.setenv(name, value)

    with pytest.raises(ValueError):
        Settings(_env_file=None)


def test_production_resource_limits_accept_documented_boundaries(monkeypatch):
    _set_production_env(monkeypatch)
    values = {
        "DB_POOL_SIZE": "100",
        "DB_MAX_OVERFLOW": "200",
        "DB_POOL_TIMEOUT_SECONDS": "300",
        "DB_POOL_RECYCLE_SECONDS": "86400",
        "DB_STATEMENT_TIMEOUT_MS": "300000",
        "DB_IDLE_TRANSACTION_TIMEOUT_MS": "600000",
        "INGESTION_MAX_FILE_BYTES": str(100 * 1024 * 1024),
        "INGESTION_MAX_RECORDS": "100000",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)

    configured = Settings(_env_file=None)

    assert configured.db_pool_size == 100
    assert configured.ingestion_max_records == 100000


def test_compose_resource_limits_accept_defaults_and_reject_excessive_values():
    validate_resource_limits({})

    for name in (
        "MIGRATION_CPU_LIMIT",
        "BACKEND_CPU_LIMIT",
        "WORKER_CPU_LIMIT",
        "FRONTEND_CPU_LIMIT",
        "MIGRATION_MEMORY_LIMIT",
        "BACKEND_MEMORY_LIMIT",
        "WORKER_MEMORY_LIMIT",
        "FRONTEND_MEMORY_LIMIT",
    ):
        with pytest.raises(ValueError, match=name):
            validate_resource_limits({name: "bad"})


def test_compose_resource_validator_reads_the_same_env_file_as_compose(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("BACKEND_MEMORY_LIMIT=3G\n")

    with pytest.raises(ValueError, match="BACKEND_MEMORY_LIMIT"):
        validate_resource_limits({}, env_file=env_file)


def _set_production_env(monkeypatch) -> None:
    monkeypatch.delenv("AUTH_SECRET", raising=False)
    monkeypatch.delenv("SHARED_POOL_ID_SECRET", raising=False)
    monkeypatch.setenv("SHARED_POOL_READ_ENABLED", "false")
    values = {
        "DATABASE_URL": "postgresql+psycopg://user:password@db:5432/carrier_pool?sslmode=require",
        "DEMO_MODE": "false",
        "AUTH_MODE": "oidc",
        "ALLOW_MOCK_AUTH": "false",
        "AUTH_ISSUER": "https://issuer.example/",
        "AUTH_AUDIENCE": "carrier-pool",
        "AUTH_JWKS_URL": "https://issuer.example/jwks",
        "AUTH_LOGIN_URL": "https://issuer.example/authorize",
        "AUTH_TOKEN_URL": "https://issuer.example/token",
        "AUTH_CLIENT_ID": "carrier-pool",
        "AUTH_REDIRECT_URI": "https://app.example.com/login",
        "ALLOWED_HOSTS": "app.example.com",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)
