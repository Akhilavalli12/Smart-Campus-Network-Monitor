"""Models for monitoring configuration, stored measurements and status-change events."""
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.network_model.enums import DeviceStatus
from app.network_model.models import utcnow


class _Base(BaseModel):
    model_config = ConfigDict(use_enum_values=True)


class Thresholds(_Base):
    """Alert/degradation thresholds. These are configurable system defaults, NOT networking standards."""

    model_config = ConfigDict(extra="forbid", use_enum_values=True)

    latency_warn_ms: float = Field(default=100.0, gt=0, le=60_000)
    latency_crit_ms: float = Field(default=250.0, gt=0, le=60_000)
    loss_warn_pct: float = Field(default=5.0, gt=0, le=100)
    loss_crit_pct: float = Field(default=20.0, gt=0, le=100)
    util_warn_pct: float = Field(default=80.0, gt=0, le=100)
    util_crit_pct: float = Field(default=90.0, gt=0, le=100)

    @model_validator(mode="after")
    def _warn_below_crit(self) -> "Thresholds":
        for name in ("latency", "loss", "util"):
            warn, crit = getattr(self, f"{name}_warn_{'ms' if name == 'latency' else 'pct'}"), getattr(
                self, f"{name}_crit_{'ms' if name == 'latency' else 'pct'}"
            )
            if warn >= crit:
                raise ValueError(f"{name} warning threshold must be lower than its critical threshold")
        return self


class MonitoringConfig(_Base):
    """Runtime-adjustable monitoring behaviour (stored in the `settings` collection)."""

    model_config = ConfigDict(extra="forbid", use_enum_values=True)

    poll_interval_s: float = Field(default=5.0, ge=2.0, le=300.0)
    failure_confirmations: int = Field(default=3, ge=1, le=10)
    recovery_confirmations: int = Field(default=2, ge=1, le=10)
    window_cycles: int = Field(default=5, ge=2, le=30)
    alert_clear_cycles: int = Field(default=3, ge=1, le=20)  # checks a latency/loss/utilization condition must stay gone before its alert resolves
    alert_hysteresis_pct: float = Field(default=10.0, ge=0, le=50)  # an alert clears only below threshold x (1 - this %)
    thresholds: Thresholds = Field(default_factory=Thresholds)


class Measurement(_Base):
    """One device, one probe cycle."""

    device_id: str
    ts: datetime
    source: str
    backend: str = ""
    target: str = ""
    sent: int
    received: int
    loss_pct: float | None = None
    rtt_min_ms: float | None = None
    rtt_avg_ms: float | None = None
    rtt_max_ms: float | None = None
    jitter_ms: float | None = None
    error: str | None = None
    status: DeviceStatus  # device status after this cycle was evaluated


class StatusEvent(_Base):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    ts: datetime = Field(default_factory=utcnow)
    device_id: str
    device_name: str
    from_status: DeviceStatus
    to_status: DeviceStatus
    reason: str
    caused_by: str | None = None
