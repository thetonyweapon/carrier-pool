import json
from pathlib import Path

import pytest

from app.config import settings
from app.ingestion import brokeros, freightflow, hauldesk
from app.ingestion.common import (
    IngestionLimitError,
    enforce_ingestion_file_size,
    enforce_ingestion_limits,
)


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
