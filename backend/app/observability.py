from __future__ import annotations

import json
import logging
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
_tracer = trace.get_tracer("carrier-pool")
_lock = threading.Lock()
_counters: defaultdict[tuple[str, tuple[tuple[str, str], ...]], int] = defaultdict(int)
_timers: defaultdict[tuple[str, tuple[tuple[str, str], ...]], list[float]] = defaultdict(
    lambda: [0, 0.0]
)


def increment(name: str, labels: Optional[Mapping[str, object]] = None, value: int = 1) -> None:
    key = (name, _label_key(labels))
    with _lock:
        _counters[key] += value


def observe_seconds(name: str, value: float, labels: Optional[Mapping[str, object]] = None) -> None:
    key = (name, _label_key(labels))
    with _lock:
        _timers[key][0] += 1
        _timers[key][1] += value


def render_metrics(source_lags: Optional[Mapping[str, float]] = None) -> str:
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
        lines.append(
            f'carrier_pool_source_lag_seconds{{source_id="{_escape(source_id)}"}} {max(lag, 0):.3f}'
        )
    return "\n".join(lines) + "\n"


def reset_metrics() -> None:
    with _lock:
        _counters.clear()
        _timers.clear()


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
        request_id = request.headers.get("X-Request-ID") or str(uuid4())
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


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        event = getattr(record, "request_event", None)
        if event is None:
            event = {"message": record.getMessage()}
        return json.dumps(event, sort_keys=True)


def _label_key(labels: Optional[Mapping[str, object]]) -> tuple[tuple[str, str], ...]:
    return tuple(sorted((key, str(value)) for key, value in (labels or {}).items()))


def _render_labels(labels: tuple[tuple[str, str], ...]) -> str:
    if not labels:
        return ""
    return "{" + ",".join(f'{key}="{_escape(value)}"' for key, value in labels) + "}"


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
