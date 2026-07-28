from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import Settings
from app.database import get_db
from app.main import create_app


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
