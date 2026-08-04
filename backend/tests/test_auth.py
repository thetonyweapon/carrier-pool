import asyncio
import time
from types import SimpleNamespace
from urllib.error import URLError

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
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


def test_malformed_base64_bearer_tokens_are_rejected() -> None:
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="%%%%.%%%%")

    with pytest.raises(HTTPException) as error:
        get_current_principal(credentials)

    assert error.value.status_code == 401


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


def test_settings_accept_valid_production_oidc_configuration(monkeypatch) -> None:
    _set_settings_env(monkeypatch, AUTH_MODE="oidc", AUTH_JWKS_URL="https://issuer.example/jwks")

    configured = Settings(_env_file=None)

    assert configured.auth_mode == "oidc"
    assert configured.auth_jwks_url == "https://issuer.example/jwks"


@pytest.mark.parametrize(
    ("overrides", "message"),
    (
        ({"AUTH_MODE": "unknown"}, "AUTH_MODE"),
        ({"AUTH_MODE": "mock"}, "requires AUTH_MODE=oidc"),
        ({"AUTH_JWKS_URL": ""}, "AUTH_JWKS_URL"),
        ({"AUTH_ISSUER": "  "}, "AUTH_ISSUER"),
        ({"AUTH_AUDIENCE": ""}, "AUTH_AUDIENCE"),
        ({"AUTH_TENANT_CLAIM": "  "}, "AUTH_TENANT_CLAIM"),
        ({"AUTH_TOKEN_TTL_SECONDS": "0"}, "greater than 0"),
        ({"AUTH_TOKEN_TTL_SECONDS": "86401"}, "less than or equal to 86400"),
        ({"DATABASE_URL": "sqlite+pysqlite:///:memory:"}, "PostgreSQL"),
        ({"AUTH_REDIRECT_URI": "http://issuer.example/login"}, "HTTPS"),
        ({"ALLOWED_HOSTS": "localhost"}, "explicit ALLOWED_HOSTS"),
        ({"ALLOWED_HOSTS": "app.example.com:443"}, "explicit ALLOWED_HOSTS"),
    ),
)
def test_settings_reject_invalid_production_matrix(monkeypatch, overrides, message) -> None:
    _set_settings_env(monkeypatch, AUTH_MODE="oidc", AUTH_JWKS_URL="https://issuer.example/jwks")
    for name, value in overrides.items():
        monkeypatch.setenv(name, value)

    with pytest.raises(ValueError, match=message):
        Settings(_env_file=None)


def test_oidc_token_uses_verified_tenant_and_subject(monkeypatch) -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    class MockJWKClient:
        def __init__(self, url: str, **kwargs) -> None:
            assert url == "https://issuer.example/jwks"
            assert kwargs["timeout"] == 5

        def get_signing_key_from_jwt(self, token: str):
            assert token
            return SimpleNamespace(key=private_key.public_key())

    monkeypatch.setattr("app.auth.settings.demo_mode", False)
    monkeypatch.setattr("app.auth.settings.auth_mode", "oidc")
    monkeypatch.setattr("app.auth.settings.allow_mock_auth", False)
    monkeypatch.setattr("app.auth.settings.auth_jwks_url", "https://issuer.example/jwks")
    monkeypatch.setattr("app.auth.settings.auth_issuer", "https://issuer.example/")
    monkeypatch.setattr("app.auth.settings.auth_audience", "carrier-pool")
    monkeypatch.setattr("app.auth.settings.auth_tenant_claim", "tenant_id")
    monkeypatch.setattr("app.auth._SecureJWKClient", MockJWKClient)

    token = jwt.encode(
        {
            "aud": "carrier-pool",
            "broker_id": "attacker-controlled-value",
            "exp": int(time.time()) + 300,
            "iss": "https://issuer.example/",
            "sub": "identity-subject-42",
            "tenant_id": "verified-broker-42",
        },
        private_key,
        algorithm="RS256",
    )

    principal = get_current_principal(
        HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    )

    assert principal.broker_id == "verified-broker-42"
    assert principal.subject == "identity-subject-42"
    assert principal.actor == "identity-subject-42"

    for invalid_claims in (
        {"aud": "wrong-audience"},
        {"iss": "https://wrong-issuer.example/"},
        {"exp": int(time.time()) - 1},
    ):
        invalid_payload = {
            "aud": "carrier-pool",
            "exp": int(time.time()) + 300,
            "iss": "https://issuer.example/",
            "sub": "identity-subject-42",
            "tenant_id": "verified-broker-42",
        }
        invalid_payload.update(invalid_claims)
        invalid_token = jwt.encode(invalid_payload, private_key, algorithm="RS256")
        with pytest.raises(HTTPException) as error:
            get_current_principal(
                HTTPAuthorizationCredentials(scheme="Bearer", credentials=invalid_token)
            )
        assert error.value.status_code == 401

    with pytest.raises(HTTPException) as signature_error:
        invalid_signature = token.rsplit(".", 1)
        get_current_principal(
            HTTPAuthorizationCredentials(
                scheme="Bearer",
                credentials=f"{invalid_signature[0]}.{invalid_signature[1][::-1]}",
            )
        )
    assert signature_error.value.status_code == 401


@pytest.mark.parametrize("body", (b"x" * 1_048_577, b"not-json"))
def test_jwks_client_rejects_oversized_or_malformed_responses(monkeypatch, body) -> None:
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def geturl(self):
            return "https://issuer.example/jwks"

        def read(self, limit=None):
            del limit
            return body

    class FakeOpener:
        def open(self, request, timeout):
            return FakeResponse()

    monkeypatch.setattr("app.auth._jwks_opener", FakeOpener())
    from app.auth import _SecureJWKClient

    with pytest.raises(jwt.PyJWKClientError):
        _SecureJWKClient("https://issuer.example/jwks", timeout=5).fetch_data()


def test_oidc_code_exchange_returns_provider_access_token(monkeypatch) -> None:
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, limit=None):
            del limit
            return b'{"access_token":"provider-token","token_type":"Bearer"}'

    monkeypatch.setattr("app.auth_api.settings.demo_mode", False)
    monkeypatch.setattr("app.auth_api.settings.auth_token_url", "https://issuer.example/token")
    monkeypatch.setattr("app.auth_api.settings.auth_client_id", "carrier-pool")
    monkeypatch.setattr("app.auth_api.settings.auth_redirect_uri", "https://app.example.com/login")

    class FakeOpener:
        def open(self, request, timeout):
            return FakeResponse()

    monkeypatch.setattr("app.auth_api._token_opener", FakeOpener())

    with TestClient(create_app()) as client:
        response = client.post(
            "/oidc/token",
            json={"code": "authorization-code", "code_verifier": "v" * 43},
        )

    assert response.status_code == 200
    assert response.json() == {"access_token": "provider-token", "token_type": "Bearer"}


def test_oidc_code_exchange_rejects_oversized_request_and_extra_fields(monkeypatch) -> None:
    monkeypatch.setattr("app.auth_api.settings.demo_mode", False)
    monkeypatch.setattr("app.auth_api.settings.auth_token_url", "https://issuer.example/token")
    monkeypatch.setattr("app.auth_api.settings.auth_client_id", "carrier-pool")
    with TestClient(create_app()) as client:
        oversized = client.post(
            "/oidc/token",
            content=b'{"code":"authorization-code","code_verifier":"' + b"v" * 43 + b'"}',
            headers={"content-type": "application/json", "content-length": "20000"},
        )
        extra = client.post(
            "/oidc/token",
            json={"code": "authorization-code", "code_verifier": "v" * 43, "extra": "x"},
        )
    assert oversized.status_code == 413
    assert extra.status_code == 422


@pytest.mark.parametrize(
    ("headers", "chunks", "status"),
    (
        ([(b"content-length", b"-1")], [b"{}"], 413),
        ([(b"content-length", b"not-a-number")], [b"{}"], 413),
        ([(b"content-length", b"1"), (b"content-length", b"1")], [b"{}"], 413),
        ([], [b"{}"], 200),
        ([], [b"x" * 10_000, b"x" * 6_385], 413),
    ),
)
def test_oidc_body_limit_handles_malformed_missing_and_chunked_bodies(
    headers, chunks, status
) -> None:
    from app.main import OidcTokenBodyLimitMiddleware

    messages = [
        {"type": "http.request", "body": chunk, "more_body": index < len(chunks) - 1}
        for index, chunk in enumerate(chunks)
    ]
    received_body = bytearray()
    responses = []

    async def app(scope, receive, send):
        message = await receive()
        received_body.extend(message.get("body", b""))
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    async def receive():
        return messages.pop(0)

    async def send(message):
        responses.append(message)

    asyncio.run(
        OidcTokenBodyLimitMiddleware(app)(
            {"type": "http", "method": "POST", "path": "/oidc/token", "headers": headers},
            receive,
            send,
        )
    )

    assert responses[0]["status"] == status
    if status == 200:
        assert bytes(received_body) == b"".join(chunks)


@pytest.mark.parametrize("provider", ("jwks", "token"))
def test_oidc_provider_transport_rejects_redirects_and_timeouts(monkeypatch, provider) -> None:
    if provider == "jwks":

        class FakeJWKOpener:
            def open(self, request, timeout):
                raise URLError("redirect or timeout")

        monkeypatch.setattr("app.auth._jwks_opener", FakeJWKOpener())
        from app.auth import _SecureJWKClient

        with pytest.raises(jwt.PyJWKClientError):
            _SecureJWKClient("https://issuer.example/jwks", timeout=5).fetch_data()
        return

    class FakeTokenOpener:
        def open(self, request, timeout):
            raise URLError("redirect or timeout")

    monkeypatch.setattr("app.auth_api.settings.demo_mode", False)
    monkeypatch.setattr("app.auth_api.settings.auth_token_url", "https://issuer.example/token")
    monkeypatch.setattr("app.auth_api.settings.auth_client_id", "carrier-pool")
    monkeypatch.setattr("app.auth_api._token_opener", FakeTokenOpener())
    with TestClient(create_app()) as client:
        response = client.post(
            "/oidc/token",
            json={"code": "authorization-code", "code_verifier": "v" * 43},
        )
    assert response.status_code == 502


@pytest.mark.parametrize(
    "body",
    (
        b"{}",
        b'{"access_token":"token","token_type":"MAC"}',
        b'{"access_token":"   ","token_type":"Bearer"}',
        b"not-json",
        b"x" * 1_048_577,
    ),
)
def test_oidc_code_exchange_rejects_invalid_provider_bodies(monkeypatch, body) -> None:
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, limit=None):
            del limit
            return body

    class FakeOpener:
        def open(self, request, timeout):
            return FakeResponse()

    monkeypatch.setattr("app.auth_api.settings.demo_mode", False)
    monkeypatch.setattr("app.auth_api.settings.auth_token_url", "https://issuer.example/token")
    monkeypatch.setattr("app.auth_api.settings.auth_client_id", "carrier-pool")
    monkeypatch.setattr("app.auth_api.settings.auth_redirect_uri", "https://app.example.com/login")
    monkeypatch.setattr("app.auth_api._token_opener", FakeOpener())

    with TestClient(create_app()) as client:
        response = client.post(
            "/oidc/token",
            json={"code": "authorization-code", "code_verifier": "v" * 43},
        )

    assert response.status_code == 502


@pytest.mark.parametrize(
    "field", ("AUTH_ISSUER", "AUTH_JWKS_URL", "AUTH_LOGIN_URL", "AUTH_TOKEN_URL")
)
def test_production_oidc_urls_require_https(monkeypatch, field) -> None:
    _set_settings_env(monkeypatch, **{field: "http://issuer.example/value"})

    with pytest.raises(ValueError, match="HTTPS"):
        Settings(_env_file=None)


def _set_settings_env(monkeypatch, **overrides: str) -> None:
    values = {
        "DATABASE_URL": "postgresql+psycopg://user:password@localhost:5432/carrier_pool?sslmode=require",
        "DEMO_MODE": "false",
        "AUTH_MODE": "oidc",
        "ALLOW_MOCK_AUTH": "false",
        "AUTH_ISSUER": "https://issuer.example/",
        "AUTH_AUDIENCE": "carrier-pool",
        "AUTH_TENANT_CLAIM": "tenant_id",
        "AUTH_JWKS_URL": "https://issuer.example/jwks",
        "AUTH_TOKEN_URL": "https://issuer.example/token",
        "AUTH_CLIENT_ID": "carrier-pool",
        "AUTH_REDIRECT_URI": "https://app.example.com/login",
        "ALLOWED_HOSTS": "app.example.com",
        "AUTH_LOGIN_URL": "https://issuer.example/authorize",
        "AUTH_TOKEN_TTL_SECONDS": "3600",
        "AUTH_SECRET": "",
        "SHARED_POOL_READ_ENABLED": "false",
        "SHARED_POOL_ID_SECRET": "",
    }
    values.update(overrides)
    for name, value in values.items():
        monkeypatch.setenv(name, value)
