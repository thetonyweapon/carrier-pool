from __future__ import annotations

import json
import logging
import math
import re
import threading
import time
from collections import defaultdict
from typing import Mapping, Optional
from uuid import uuid4

from opentelemetry import trace
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

_logger = logging.getLogger("carrier_pool.request")
_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_METRIC_NAME_PATTERN = re.compile(r"^[a-zA-Z_:][a-zA-Z0-9_:]*$")
_LABEL_NAME_PATTERN = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")
_MAX_METRIC_NAME_LENGTH = 128
_MAX_LABEL_NAME_LENGTH = 64
_MAX_LABEL_VALUE_LENGTH = 128
_FAILURE_CLASS_LABELS = frozenset(
    {
        "DBAPIError",
        "ConnectionError",
        "FileAccessError",
        "IncrementalFailure",
        "IntegrityError",
        "InvalidPayload",
        "LeaseExpired",
        "OperationalError",
        "TimeoutError",
        "Other",
    }
)
_tracer = trace.get_tracer("carrier-pool")
_lock = threading.Lock()
_counters: defaultdict[tuple[str, tuple[tuple[str, str], ...]], int] = defaultdict(int)
_timers: defaultdict[tuple[str, tuple[tuple[str, str], ...]], list[float]] = defaultdict(
    lambda: [0, 0.0]
)


def increment(name: str, labels: Optional[Mapping[str, object]] = None, value: int = 1) -> None:
    if len(name) > _MAX_METRIC_NAME_LENGTH or not _METRIC_NAME_PATTERN.fullmatch(name):
        raise ValueError("invalid metric name")
    if not math.isfinite(value) or value < 0:
        raise ValueError("metric increment must be non-negative")
    key = (name, _label_key(labels))
    with _lock:
        _counters[key] += value


def observe_seconds(name: str, value: float, labels: Optional[Mapping[str, object]] = None) -> None:
    if len(name) > _MAX_METRIC_NAME_LENGTH or not _METRIC_NAME_PATTERN.fullmatch(name):
        raise ValueError("invalid metric name")
    if not math.isfinite(value) or value < 0:
        raise ValueError("metric duration must be finite and non-negative")
    key = (name, _label_key(labels))
    with _lock:
        _timers[key][0] += 1
        _timers[key][1] += value


def render_metrics(
    source_lags: Optional[Mapping[str, Optional[float]]] = None,
    job_states: Optional[Mapping[str, int]] = None,
) -> str:
    lines: list[str] = []
    with _lock:
        counters = list(_counters.items())
        timers = list(_timers.items())
    for (name, labels), value in sorted(counters):
        lines.append(f"{name}{_render_labels(labels)} {value}")
    for (name, labels), (count, total) in sorted(timers):
        lines.append(f"{name}_count{_render_labels(labels)} {count}")
        lines.append(f"{name}_sum{_render_labels(labels)} {total:.6f}")
    for source_id, lag in sorted((source_lags or {}).items()):
        source_labels = _render_labels(_label_key({"source_id": source_id}))
        rendered_lag = -1 if lag is None or not math.isfinite(lag) else max(lag, 0)
        lines.append(f"carrier_pool_source_lag_seconds{source_labels} {rendered_lag:.3f}")
    for state, count in sorted((job_states or {}).items()):
        state_labels = _render_labels(_label_key({"status": state}))
        lines.append(f"carrier_pool_ingestion_jobs{state_labels} {max(count, 0)}")
    return "\n".join(lines) + "\n"


def reset_metrics() -> None:
    with _lock:
        _counters.clear()
        _timers.clear()


def record_ingestion_failure(failure_class: str, tms_type: Optional[str] = None) -> None:
    labels: dict[str, object] = {"failure_class": normalize_failure_class(failure_class)}
    if tms_type is not None:
        labels["tms"] = tms_type
    increment("carrier_pool_ingestion_failures_total", labels)


def normalize_failure_class(failure_class: str) -> str:
    if failure_class in _FAILURE_CLASS_LABELS:
        return failure_class
    if failure_class.endswith("PayloadError"):
        return "InvalidPayload"
    if failure_class in {"ValueError", "ValidationError"}:
        return "InvalidPayload"
    if failure_class.endswith("FileSecurityError") or failure_class == "FileNotFoundError":
        return "FileAccessError"
    if failure_class.endswith("IngestionError"):
        return "IncrementalFailure"
    return "Other"


def configure_logging() -> None:
    if _logger.handlers:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(_JsonFormatter())
    _logger.addHandler(handler)
    _logger.setLevel(logging.INFO)
    _logger.propagate = False


class RequestObservabilityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = canonical_request_id(request.headers.get("X-Request-ID"))
        request.state.request_id = request_id
        started = time.perf_counter()
        response: Optional[Response] = None
        with _tracer.start_as_current_span("http.request") as span:
            span.set_attribute("http.request.method", request.method)
            span.set_attribute("http.request.id", request_id)
            try:
                response = await call_next(request)
                return response
            finally:
                duration = time.perf_counter() - started
                status_code = response.status_code if response is not None else 500
                route = request.scope.get("route")
                route_path = getattr(route, "path", "unknown")
                span.set_attribute("http.response.status_code", status_code)
                increment(
                    "carrier_pool_requests_total",
                    {"method": request.method, "route": route_path, "status": status_code},
                )
                observe_seconds(
                    "carrier_pool_request_duration_seconds",
                    duration,
                    {"method": request.method, "route": route_path},
                )
                _logger.info(
                    "request_complete",
                    extra={
                        "request_event": {
                            "request_id": request_id,
                            "method": request.method,
                            "route": route_path,
                            "status": status_code,
                            "duration_seconds": round(duration, 6),
                        }
                    },
                )
                if response is not None:
                    response.headers["X-Request-ID"] = request_id


def canonical_request_id(candidate: Optional[str]) -> str:
    if candidate is not None and _REQUEST_ID_PATTERN.fullmatch(candidate):
        return candidate
    return str(uuid4())


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        event = getattr(record, "request_event", None)
        if event is None:
            event = {"message": record.getMessage()}
        return json.dumps(event, sort_keys=True)


def _label_key(labels: Optional[Mapping[str, object]]) -> tuple[tuple[str, str], ...]:
    normalized = []
    for key, value in (labels or {}).items():
        if len(key) > _MAX_LABEL_NAME_LENGTH or not _LABEL_NAME_PATTERN.fullmatch(key):
            raise ValueError("invalid metric label name")
        label_value = str(value)
        if key == "failure_class":
            label_value = normalize_failure_class(label_value)
        normalized.append((key, label_value[:_MAX_LABEL_VALUE_LENGTH]))
    return tuple(sorted(normalized))


def _render_labels(labels: tuple[tuple[str, str], ...]) -> str:
    if not labels:
        return ""
    return "{" + ",".join(f'{key}="{_escape(value)}"' for key, value in labels) + "}"


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
