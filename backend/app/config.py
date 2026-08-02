from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = Field(validation_alias="DATABASE_URL")
    demo_mode: bool = Field(False, validation_alias="DEMO_MODE")
    auth_mode: str = Field("mock", validation_alias="AUTH_MODE")
    allow_mock_auth: bool = Field(False, validation_alias="ALLOW_MOCK_AUTH")
    auth_secret: Optional[str] = Field(None, validation_alias="AUTH_SECRET")
    auth_issuer: str = Field("carrier-pool-mock", validation_alias="AUTH_ISSUER")
    auth_audience: str = Field("carrier-pool-api", validation_alias="AUTH_AUDIENCE")
    auth_token_ttl_seconds: int = Field(3600, validation_alias="AUTH_TOKEN_TTL_SECONDS")
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


settings = Settings()
