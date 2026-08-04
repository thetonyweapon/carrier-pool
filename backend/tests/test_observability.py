import logging
from unittest.mock import MagicMock

import pytest

from app.ingestion.common import ingestion_transaction
from app.observability import (
    _JsonFormatter,
    increment,
    normalize_failure_class,
    observe_seconds,
    render_metrics,
    reset_metrics,
)


def test_metrics_escape_labels_and_render_timer_samples() -> None:
    reset_metrics()
    increment("carrier_pool_requests_total", {"route": '/loads/"quoted"'})
    observe_seconds("carrier_pool_request_duration_seconds", 0.25)

    output = render_metrics({"source-a": 12.5})

    assert 'route="/loads/\\"quoted\\""' in output
    assert "carrier_pool_request_duration_seconds_count 1" in output
    assert "carrier_pool_request_duration_seconds_sum 0.250000" in output
    assert 'carrier_pool_source_lag_seconds{source_id="source-a"} 12.500' in output
    reset_metrics()


def test_metrics_render_ingestion_job_states() -> None:
    output = render_metrics(job_states={"dead_letter": 2, "queued": 3})

    assert 'carrier_pool_ingestion_jobs{status="dead_letter"} 2' in output
    assert 'carrier_pool_ingestion_jobs{status="queued"} 3' in output


def test_metrics_bound_and_normalize_failure_labels() -> None:
    increment(
        "carrier_pool_ingestion_failures_total",
        {"failure_class": "secret-class", "source_id": "x" * 300},
    )
    output = render_metrics()

    assert 'failure_class="Other"' in output
    assert "x" * 129 not in output
    assert normalize_failure_class("InvalidHaulDeskPayloadError") == "InvalidPayload"


def test_metrics_reject_invalid_names_and_label_names() -> None:
    with pytest.raises(ValueError, match="invalid metric name"):
        increment("not a metric")
    with pytest.raises(ValueError, match="invalid metric label name"):
        increment("carrier_pool_test_total", {"bad-label": "value"})
    for value in (-1, float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValueError, match="non-negative"):
            increment("carrier_pool_test_total", value=value)
    with pytest.raises(ValueError, match="finite"):
        observe_seconds("carrier_pool_test_duration_seconds", float("nan"))


def test_transaction_metrics_and_structured_logs_exclude_raw_payloads() -> None:
    db = MagicMock()
    with ingestion_transaction(db, "hauldesk"):
        pass
    output = render_metrics()
    assert 'outcome="committed"' in output
    with pytest.raises(RuntimeError):
        with ingestion_transaction(db, "hauldesk"):
            raise RuntimeError("raw-secret-payload")
    assert 'outcome="rolled_back"' in render_metrics()

    record = logging.LogRecord(
        "carrier_pool.request",
        logging.INFO,
        __file__,
        1,
        "raw-secret-payload",
        (),
        None,
    )
    record.request_event = {"request_id": "request-1", "route": "/metrics"}
    assert "raw-secret-payload" not in _JsonFormatter().format(record)
