import ipaddress
from typing import Optional
from urllib.parse import urlparse

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

DEMO_AUTH_SECRET_FALLBACK = "carrier-pool-compose-demo-auth-secret"
DEMO_SHARED_POOL_ID_SECRET_FALLBACK = "carrier-pool-compose-demo-shared-secret"
SUPPORTED_AUTH_MODES = frozenset({"mock", "oidc"})
MAX_AUTH_TOKEN_TTL_SECONDS = 86400


def _is_forbidden_host(value: str) -> bool:
    host = value.strip().casefold().rstrip(".")
    if "*" in host:
        return True
    if host.startswith("[") and "]" in host:
        closing = host.index("]")
        port = host[closing + 1 :]
        if port:
            return True
        host = host[1:closing]
    elif host.count(":") == 1:
        return True
    elif ":" in host and not _is_ip_address(host):
        return True
    host = host.rstrip(".")
    if host in {"localhost", "testserver"}:
        return True
    return _is_ip_address(host)


def _is_ip_address(host: str) -> bool:
    try:
        address = ipaddress.ip_address(host)
        return (
            address.is_loopback
            or address.is_unspecified
            or getattr(address, "ipv4_mapped", None) is not None
            and address.ipv4_mapped.is_loopback
        )
    except ValueError:
        return False


class Settings(BaseSettings):
    database_url: str = Field(validation_alias="DATABASE_URL")
    demo_mode: bool = Field(False, validation_alias="DEMO_MODE")
    auth_mode: str = Field("mock", validation_alias="AUTH_MODE")
    allow_mock_auth: bool = Field(False, validation_alias="ALLOW_MOCK_AUTH")
    auth_secret: Optional[str] = Field(None, validation_alias="AUTH_SECRET")
    auth_issuer: str = Field("carrier-pool-mock", validation_alias="AUTH_ISSUER")
    auth_audience: str = Field("carrier-pool-api", validation_alias="AUTH_AUDIENCE")
    auth_jwks_url: Optional[str] = Field(None, validation_alias="AUTH_JWKS_URL")
    auth_login_url: Optional[str] = Field(None, validation_alias="AUTH_LOGIN_URL")
    auth_token_url: Optional[str] = Field(None, validation_alias="AUTH_TOKEN_URL")
    auth_client_id: Optional[str] = Field(None, validation_alias="AUTH_CLIENT_ID")
    auth_redirect_uri: Optional[str] = Field(None, validation_alias="AUTH_REDIRECT_URI")
    auth_tenant_claim: str = Field("tenant_id", validation_alias="AUTH_TENANT_CLAIM")
    allowed_hosts: str = Field("*", validation_alias="ALLOWED_HOSTS")
    auth_token_ttl_seconds: int = Field(
        3600,
        validation_alias="AUTH_TOKEN_TTL_SECONDS",
        gt=0,
        le=MAX_AUTH_TOKEN_TTL_SECONDS,
    )
    shared_pool_read_enabled: bool = Field(False, validation_alias="SHARED_POOL_READ_ENABLED")
    shared_pool_id_secret: Optional[str] = Field(None, validation_alias="SHARED_POOL_ID_SECRET")
    db_pool_size: int = Field(5, validation_alias="DB_POOL_SIZE", ge=1)
    db_max_overflow: int = Field(10, validation_alias="DB_MAX_OVERFLOW", ge=0)
    db_pool_timeout_seconds: int = Field(30, validation_alias="DB_POOL_TIMEOUT_SECONDS", ge=1)
    db_pool_recycle_seconds: int = Field(1800, validation_alias="DB_POOL_RECYCLE_SECONDS", ge=0)
    db_statement_timeout_ms: int = Field(30000, validation_alias="DB_STATEMENT_TIMEOUT_MS", ge=0)
    db_idle_transaction_timeout_ms: int = Field(
        60000, validation_alias="DB_IDLE_TRANSACTION_TIMEOUT_MS", ge=0
    )
    ingestion_max_file_bytes: int = Field(
        10 * 1024 * 1024, validation_alias="INGESTION_MAX_FILE_BYTES", ge=1
    )
    ingestion_max_records: int = Field(1000, validation_alias="INGESTION_MAX_RECORDS", ge=1)

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @model_validator(mode="after")
    def validate_auth_boundary(self) -> "Settings":
        if self.auth_mode not in SUPPORTED_AUTH_MODES:
            raise ValueError(f"AUTH_MODE must be one of: {', '.join(sorted(SUPPORTED_AUTH_MODES))}")
        if not self.auth_issuer.strip():
            raise ValueError("AUTH_ISSUER must be non-empty")
        if not self.auth_audience.strip():
            raise ValueError("AUTH_AUDIENCE must be non-empty")
        if not self.auth_tenant_claim.strip():
            raise ValueError("AUTH_TENANT_CLAIM must be non-empty")

        if self.demo_mode:
            if self.auth_mode != "mock" or not self.allow_mock_auth:
                raise ValueError("DEMO_MODE requires AUTH_MODE=mock and ALLOW_MOCK_AUTH=true")
            return self

        if self.allow_mock_auth:
            raise ValueError("mock authentication is only permitted when DEMO_MODE=true")
        if self.auth_secret == DEMO_AUTH_SECRET_FALLBACK:
            raise ValueError("the demo AUTH_SECRET fallback is not allowed outside DEMO_MODE")
        if self.shared_pool_id_secret == DEMO_SHARED_POOL_ID_SECRET_FALLBACK:
            raise ValueError(
                "the demo SHARED_POOL_ID_SECRET fallback is not allowed outside DEMO_MODE"
            )
        if self.auth_mode != "oidc":
            raise ValueError("non-demo mode requires AUTH_MODE=oidc")
        hosts = [host.strip() for host in self.allowed_hosts.split(",") if host.strip()]
        if not hosts or any(_is_forbidden_host(host) for host in hosts):
            raise ValueError("non-demo mode requires an explicit ALLOWED_HOSTS list")
        if not self.auth_jwks_url or not self.auth_jwks_url.strip():
            raise ValueError("non-demo mode requires AUTH_JWKS_URL")
        for name, value in (
            ("AUTH_ISSUER", self.auth_issuer),
            ("AUTH_JWKS_URL", self.auth_jwks_url),
            ("AUTH_LOGIN_URL", self.auth_login_url),
            ("AUTH_TOKEN_URL", self.auth_token_url),
            ("AUTH_REDIRECT_URI", self.auth_redirect_uri),
        ):
            parsed = urlparse(value or "")
            try:
                hostname = parsed.hostname
                parsed.port
            except ValueError:
                hostname = None
            if parsed.scheme != "https" or not hostname:
                raise ValueError(f"non-demo mode requires a valid HTTPS {name}")
        if not self.auth_client_id:
            raise ValueError("non-demo mode requires AUTH_CLIENT_ID")
        if self.shared_pool_read_enabled and (
            not self.shared_pool_id_secret or len(self.shared_pool_id_secret.strip()) < 32
        ):
            raise ValueError(
                "SHARED_POOL_READ_ENABLED requires a non-blank SHARED_POOL_ID_SECRET "
                "of at least 32 characters"
            )
        try:
            database_url = make_url(self.database_url)
        except (ArgumentError, AttributeError, TypeError, ValueError) as exc:
            raise ValueError("non-demo mode requires a valid PostgreSQL DATABASE_URL") from exc
        if database_url.get_backend_name() != "postgresql":
            raise ValueError("non-demo mode requires a PostgreSQL DATABASE_URL")
        if database_url.drivername != "postgresql+psycopg":
            raise ValueError("non-demo mode requires DATABASE_URL=postgresql+psycopg://...")
        if database_url.query.get("sslmode") not in {"require", "verify-ca", "verify-full"}:
            raise ValueError("non-demo mode requires DATABASE_URL sslmode=require or stronger")
        return self


settings = Settings()
