from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = Field(validation_alias="DATABASE_URL")
    demo_mode: bool = Field(False, validation_alias="DEMO_MODE")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
