from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file="../.env", extra="ignore")

    database_url: str = "postgresql+psycopg://kb:kb@localhost:5432/kb"
    test_database_url: str = "postgresql+psycopg://kb:kb@localhost:5432/kb_test"

    jwt_secret: str = "change-me"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 480


@lru_cache
def get_settings() -> Settings:
    return Settings()
