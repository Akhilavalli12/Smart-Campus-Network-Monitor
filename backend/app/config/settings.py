"""Application settings, loaded from environment variables / .env.

Secrets and deployment-specific values (database URI, allowed origins) live in
the environment, never in source code.
"""
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Smart Campus Network Monitor"
    app_version: str = "0.1.0"
    app_env: str = "development"

    mongodb_uri: str = "mongodb://localhost:27017"
    mongodb_db_name: str = "campus_noc"
    # Fail fast when MongoDB is down instead of hanging for the 30 s driver default.
    mongodb_server_selection_timeout_ms: int = 2000

    # Create MongoDB indexes in the background at startup (retries until the database is reachable).
    ensure_indexes_on_startup: bool = True

    # --- Probing (Stage 2) ---
    probe_count: int = Field(default=5, ge=1, le=20)  # echo requests per probe cycle
    probe_timeout_s: float = Field(default=1.0, ge=0.2, le=10.0)  # wait per echo request
    probe_interval_s: float = Field(default=0.2, ge=0.2, le=5.0)  # gap between echo requests
    icmp_backend: str = Field(default="auto", pattern="^(auto|icmplib|system)$")
    simulator_seed: int = 42
    # --- Monitoring engine (Stage 3) ---
    monitoring_enabled: bool = True  # run the polling loop inside the API process
    poll_interval_s: float = Field(default=5.0, ge=2.0, le=300.0)  # minimum time between cycle starts
    failure_confirmations: int = Field(default=3, ge=1, le=10)  # consecutive failed cycles before OFFLINE
    recovery_confirmations: int = Field(default=2, ge=1, le=10)  # consecutive good cycles before back ONLINE
    window_cycles: int = Field(default=5, ge=2, le=30)  # cycles used to judge DEGRADED
    measurement_retention_hours: int = Field(default=26, ge=1, le=24 * 30)  # TTL of stored measurements
    # --- Traffic engine (Stage 4) ---
    traffic_enabled: bool = True
    traffic_interval_s: float = Field(default=5.0, ge=2.0, le=300.0)
    host_nic: str = ""  # network interface of THIS computer to report as REAL traffic ("" = all non-loopback interfaces)
    # --- Alerts / simulation (Stages 5-6) ---
    alerts_enabled: bool = True
    simulation_enabled: bool = True  # allow fault injection through the API (turn off for a read-only deployment)
    # Device the monitoring station is plugged into (its vantage point in the topology).
    monitor_attached_to: str = "core-switch"

    # Stored as a plain comma-separated string; use `cors_origin_list` to consume it.
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
