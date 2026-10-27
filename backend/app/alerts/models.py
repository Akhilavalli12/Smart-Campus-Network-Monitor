"""Alert model. An alert is OPEN while its condition holds and RESOLVED automatically when it clears."""
import uuid
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from app.network_model.models import utcnow


class AlertType(StrEnum):
    DEVICE_OFFLINE = "DEVICE_OFFLINE"
    HIGH_LATENCY = "HIGH_LATENCY"
    HIGH_PACKET_LOSS = "HIGH_PACKET_LOSS"
    HIGH_UTILIZATION = "HIGH_UTILIZATION"


class Severity(StrEnum):
    WARNING = "warning"
    CRITICAL = "critical"


class Alert(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    type: AlertType
    severity: Severity
    state: str = "open"  # open | resolved
    dedupe_key: str  # one OPEN alert per key, e.g. "DEVICE_OFFLINE:cse-switch"
    device_id: str | None = None
    device_name: str | None = None
    link_id: str | None = None
    title: str
    message: str
    metrics: dict[str, float | str | None] = Field(default_factory=dict)  # snapshot taken when the alert last changed
    affected_device_ids: list[str] = Field(default_factory=list)  # downstream devices hidden behind a root-cause alert
    last_response_at: datetime | None = None
    opened_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    resolved_at: datetime | None = None
    acknowledged: bool = False
    acknowledged_at: datetime | None = None
    quiet_cycles: int = 0  # consecutive checks in which the condition was absent (clear delay)
