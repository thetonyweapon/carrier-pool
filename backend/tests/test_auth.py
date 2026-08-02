import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from fastapi.testclient import TestClient

from app.auth import get_current_principal, issue_demo_token
from app.main import create_app


def test_broker_scoped_routes_require_bearer_authentication() -> None:
    application = create_app()
    paths = (
        "/brokers/broker-a/loads",
        "/brokers/broker-a/loads/load/lane-intelligence",
        "/brokers/broker-a/loads/load/carrier-recommendations",
        "/brokers/broker-a/loads/load/carrier-rate-estimate",
        "/brokers/broker-a/carrier-candidates/carrier:carrier",
        "/brokers/broker-a/shared-pool-policy",
    )
    with TestClient(application) as client:
        for path in paths:
            assert client.get(path).status_code == 401


def test_broker_scoped_routes_reject_a_token_for_another_broker() -> None:
    application = create_app()
    token = issue_demo_token("broker-b")
    with TestClient(application) as client:
        response = client.get(
            "/brokers/broker-a/loads",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == 403


def test_mock_token_requires_matching_issuer_audience_and_subject(monkeypatch) -> None:
    token = issue_demo_token("broker-a", actor="operator-a")
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

    principal = get_current_principal(credentials)
    assert principal.broker_id == "broker-a"
    assert principal.actor == "operator-a"
    assert principal.subject == "operator-a"

    monkeypatch.setattr("app.auth.settings.auth_audience", "wrong-audience")
    with pytest.raises(HTTPException) as error:
        get_current_principal(credentials)
    assert error.value.status_code == 401
