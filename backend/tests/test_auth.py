import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from fastapi.testclient import TestClient

from app.auth import get_current_principal, issue_demo_token
from app.config import Settings, settings
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


def test_demo_token_endpoint_is_hidden_outside_demo_mode(monkeypatch) -> None:
    monkeypatch.setattr("app.auth_api.settings.demo_mode", False)
    with TestClient(create_app()) as client:
        response = client.post(
            "/demo/auth",
            json={"broker_id": "broker-a", "identifier": "admin", "password": "admin"},
        )
    assert response.status_code == 404


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
    assert error.value.detail == "invalid bearer token"


def test_mock_token_issuer_and_expiration_failures_use_invalid_token(monkeypatch) -> None:
    token = issue_demo_token("broker-a", actor="operator-a")
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

    original_issuer = settings.auth_issuer
    monkeypatch.setattr("app.auth.settings.auth_issuer", "wrong-issuer")
    with pytest.raises(HTTPException) as issuer_error:
        get_current_principal(credentials)
    assert issuer_error.value.detail == "invalid bearer token"

    monkeypatch.setattr("app.auth.settings.auth_issuer", original_issuer)
    monkeypatch.setattr("app.auth.settings.auth_token_ttl_seconds", -1)
    expired_token = issue_demo_token("broker-a", actor="operator-a")
    expired_credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=expired_token)
    with pytest.raises(HTTPException) as expiry_error:
        get_current_principal(expired_credentials)
    assert expiry_error.value.detail == "invalid bearer token"


def test_mock_auth_is_unavailable_outside_explicit_mock_profile(monkeypatch) -> None:
    token = issue_demo_token("broker-a")
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    monkeypatch.setattr("app.auth.settings.allow_mock_auth", False)

    with pytest.raises(HTTPException) as error:
        get_current_principal(credentials)
    assert error.value.status_code == 503


def test_mock_auth_is_unavailable_outside_demo_mode(monkeypatch) -> None:
    monkeypatch.setattr("app.auth.settings.demo_mode", False)
    with pytest.raises(ValueError, match="only enabled for demo mode"):
        issue_demo_token("broker-a")

    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="not-a-token")
    with pytest.raises(HTTPException) as error:
        get_current_principal(credentials)
    assert error.value.status_code == 503


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("auth_secret", "carrier-pool-compose-demo-auth-secret", "AUTH_SECRET"),
        (
            "shared_pool_id_secret",
            "carrier-pool-compose-demo-shared-secret",
            "SHARED_POOL_ID_SECRET",
        ),
    ),
)
def test_non_demo_settings_reject_demo_fallback_secrets(monkeypatch, field, value, message) -> None:
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("DEMO_MODE", "false")
    monkeypatch.setenv("AUTH_MODE", "oidc")
    monkeypatch.setenv("ALLOW_MOCK_AUTH", "false")
    monkeypatch.delenv("AUTH_SECRET", raising=False)
    monkeypatch.delenv("SHARED_POOL_ID_SECRET", raising=False)
    env_field = {
        "auth_secret": "AUTH_SECRET",
        "shared_pool_id_secret": "SHARED_POOL_ID_SECRET",
    }[field]
    monkeypatch.setenv(env_field, value)
    with pytest.raises(ValueError, match=message):
        Settings(_env_file=None)


def test_non_demo_settings_reject_mock_auth(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("DEMO_MODE", "false")
    monkeypatch.setenv("AUTH_MODE", "mock")
    monkeypatch.setenv("ALLOW_MOCK_AUTH", "true")
    with pytest.raises(ValueError, match="only permitted"):
        Settings(_env_file=None)
