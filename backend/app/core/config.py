from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Control Tower"
    client_name: str = ""  # SPV / client name applied to uploads; empty = fall back to the name in the document
    mongodb_uri: str = "mongodb://localhost:27017"
    mongodb_db: str = "control_tower"

    jwt_secret: str = "dev-only-change-me"
    jwt_expire_minutes: int = 480

    admin_email: str = "admin@example.com"
    admin_password: str = "ChangeMe123!"
    admin_name: str = "Administrator"
    allow_self_registration: bool = True

    cors_origins: list[str] = ["http://localhost:5173"]

    storage_backend: str = "local"  # local | s3
    storage_local_dir: str = "./storage"
    s3_bucket: str = ""

    max_upload_mb: int = 250
    max_uncompressed_mb: int = 1000
    parse_timeout_seconds: int = 300


@lru_cache
def get_settings() -> Settings:
    return Settings()
