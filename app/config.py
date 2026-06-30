from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Local SQLite — auth/login + app-internal data (machines, floors, breakdowns, utility).
    local_database_url: str = "sqlite:///./factoryops.db"

    # RDS Postgres — maintenance tables visible in pgAdmin (assets, runs, daily-kWh).
    # Reuses the existing `.env` DATABASE_URL value.
    rds_database_url: str = Field(validation_alias="DATABASE_URL")

    jwt_secret: str = "change-me-in-production-please"
    jwt_algorithm: str = "HS256"
    jwt_expires_hours: int = 8
    dev_bypass_token: str = "dev-bypass-token"
    cost_per_kwh: float = 8.5
    power_factor: float = 0.99  # fixed; used for kWh = rated_kw * hours * power_factor
    # A run open longer than this is treated as an orphan (operator forgot to STOP);
    # /energy/runs/active auto-closes it, capping its duration/kWh at this many hours.
    max_run_hours: float = 16.0

    # AWS S3 — proof-photo / image storage (reuses the existing .env AWS_* keys).
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    aws_region: str = "ap-south-1"
    aws_s3_bucket_name: str = ""


settings = Settings()
