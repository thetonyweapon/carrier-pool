from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import Settings
from app.database import get_db
from app.main import create_app
from app.models import IngestionJobStatus
from app.observability import increment, reset_metrics


@pytest.fixture
def client() -> tuple[TestClient, MagicMock]:
    session = MagicMock(spec=Session)
    application = create_app()

    def override_db():
        yield session

    application.dependency_overrides[get_db] = override_db
    with TestClient(application) as test_client:
        yield test_client, session


def test_settings_read_database_url_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    database_url = "postgresql+psycopg://user:password@database:5432/app"
    monkeypatch.setenv("DATABASE_URL", database_url)

    assert Settings().database_url == database_url


def test_health_reports_database_status(client: tuple[TestClient, MagicMock]) -> None:
    test_client, session = client

    response = test_client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}
    session.execute.assert_called_once()


def test_health_returns_service_unavailable_when_database_fails(
    client: tuple[TestClient, MagicMock],
) -> None:
    test_client, session = client
    session.execute.side_effect = SQLAlchemyError("database unavailable")

    response = test_client.get("/health")

    assert response.status_code == 503
    assert response.json() == {"detail": {"status": "degraded", "database": "unavailable"}}


def test_liveness_and_request_id_do_not_require_database(
    client: tuple[TestClient, MagicMock],
) -> None:
    test_client, session = client
    response = test_client.get("/live", headers={"X-Request-ID": "request-123"})

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["X-Request-ID"] == "request-123"
    session.execute.assert_not_called()


def test_invalid_request_id_is_replaced_before_response_and_logging(
    client: tuple[TestClient, MagicMock],
) -> None:
    test_client, session = client
    response = test_client.get("/live", headers={"X-Request-ID": "raw secret\nvalue"})

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] != "raw secret\nvalue"
    session.execute.assert_not_called()


def test_metrics_endpoint_renders_counters_and_source_lag(
    client: tuple[TestClient, MagicMock],
) -> None:
    test_client, _ = client
    reset_metrics()
    increment("carrier_pool_test_total", {"outcome": "ok"})

    response = test_client.get("/metrics")

    assert response.status_code == 200
    assert 'carrier_pool_test_total{outcome="ok"} 1' in response.text
    reset_metrics()


def test_metrics_endpoint_renders_ingestion_job_states(
    client: tuple[TestClient, MagicMock],
) -> None:
    test_client, session = client
    source_result = MagicMock()
    source_result.all.return_value = [
        ("source-a", datetime.now(timezone.utc)),
    ]
    job_result = MagicMock()
    job_result.all.return_value = [(IngestionJobStatus.QUEUED, 3)]
    session.execute.side_effect = [source_result, job_result]

    response = test_client.get("/metrics")

    assert response.status_code == 200
    assert 'carrier_pool_ingestion_jobs{status="queued"} 3' in response.text


def test_metrics_endpoint_marks_sources_without_successful_sync(
    client: tuple[TestClient, MagicMock],
) -> None:
    test_client, session = client
    source_result = MagicMock()
    source_result.all.return_value = [("source-a", None)]
    job_result = MagicMock()
    job_result.all.return_value = []
    session.execute.side_effect = [source_result, job_result]

    response = test_client.get("/metrics")

    assert 'carrier_pool_source_lag_seconds{source_id="source-a"} -1.000' in response.text


def test_metrics_remains_available_when_database_is_down(
    client: tuple[TestClient, MagicMock],
) -> None:
    test_client, session = client
    session.execute.side_effect = SQLAlchemyError("database unavailable")

    response = test_client.get("/metrics")

    assert response.status_code == 200
