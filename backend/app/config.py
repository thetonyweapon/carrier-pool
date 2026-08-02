from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = Field(validation_alias="DATABASE_URL")
    demo_mode: bool = Field(False, validation_alias="DEMO_MODE")
    auth_secret: Optional[str] = Field(None, validation_alias="AUTH_SECRET")
    auth_token_ttl_seconds: int = Field(3600, validation_alias="AUTH_TOKEN_TTL_SECONDS")
    shared_pool_read_enabled: bool = Field(False, validation_alias="SHARED_POOL_READ_ENABLED")
    shared_pool_id_secret: Optional[str] = Field(None, validation_alias="SHARED_POOL_ID_SECRET")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
