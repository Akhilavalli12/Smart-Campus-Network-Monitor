"""Pydantic models for the network model (API schemas and stored documents)."""
from datetime import datetime, timezone
from ipaddress import IPv4Address

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.network_model.addressing import SubnetInfo
from app.network_model.enums import (
    CampusBlock,
    DeviceStatus,
    DeviceType,
    FaultType,
    LinkKind,
    MonitoringMode,
)

SLUG_PATTERN = r"^[a-z0-9][a-z0-9-]{1,39}$"
MAC_PATTERN = r"^([0-9a-f]{2}:){5}[0-9a-f]{2}$"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class _Base(BaseModel):
    # use_enum_values stores plain strings, which MongoDB can encode directly.
    model_config = ConfigDict(use_enum_values=True)


class SimState(_Base):
    """Fault currently injected into a SIMULATED device (used from Stage 6)."""

    fault: FaultType = FaultType.NONE
    params: dict[str, float] = Field(default_factory=dict)


class Subnet(_Base):
    id: str = Field(pattern=SLUG_PATTERN)
    name: str = Field(min_length=1, max_length=64)
    cidr: str
    block: CampusBlock
    gateway: str | None = None
    gateway_device_id: str | None = None
    purpose: str = Field(default="", max_length=200)


class SubnetOut(Subnet):
    info: SubnetInfo


class LatestMetrics(_Base):
    """Most recent probe cycle of a device, plus the windowed numbers its status was judged on."""

    at: datetime
    source: str  # "real" | "simulated"
    backend: str = ""
    target: str = ""
    sent: int
    received: int
    loss_pct: float | None = None
    rtt_min_ms: float | None = None
    rtt_avg_ms: float | None = None
    rtt_max_ms: float | None = None
    jitter_ms: float | None = None
    window_loss_pct: float | None = None
    window_rtt_avg_ms: float | None = None
    window_sent: int | None = None  # echoes sent / received over the status window (lets rules require real evidence)
    window_received: int | None = None


class Device(_Base):
    id: str
    name: str
    type: DeviceType
    ip: str
    subnet_id: str | None = None
    block: CampusBlock
    location: str = ""
    parent_id: str | None = None
    monitoring_mode: MonitoringMode
    probe_target: str | None = None  # real host to ping when monitoring_mode == real
    mac: str | None = None  # simulated, locally administered
    base_rtt_ms: float | None = None  # simulator parameter, not a measurement
    status: DeviceStatus = DeviceStatus.UNKNOWN
    last_seen: datetime | None = None
    up_since: datetime | None = None
    sim_state: SimState = Field(default_factory=SimState)
    created_at: datetime = Field(default_factory=utcnow)
    # --- written by the monitoring engine ---
    consecutive_failures: int = 0
    caused_by: str | None = None  # root-cause device id while status == unreachable
    monitoring_error: str | None = None  # the PROBE could not run (not the same as the device being down)
    latest: LatestMetrics | None = None


class DeviceCreate(_Base):
    """Body of POST /api/devices. Syntax is validated here; networking rules in the service."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, use_enum_values=True)

    id: str | None = Field(default=None, pattern=SLUG_PATTERN)
    name: str = Field(min_length=1, max_length=64)
    type: DeviceType
    ip: str
    subnet_id: str | None = None
    block: CampusBlock
    location: str = Field(default="", max_length=120)
    parent_id: str | None = None
    monitoring_mode: MonitoringMode = MonitoringMode.SIMULATED
    probe_target: str | None = None
    mac: str | None = Field(default=None, pattern=MAC_PATTERN)
    base_rtt_ms: float | None = Field(default=None, gt=0, le=5000)
    uplink_capacity_mbps: float | None = Field(default=None, gt=0, le=1_000_000)

    @field_validator("ip", "probe_target")
    @classmethod
    def _must_be_ipv4(cls, value: str | None) -> str | None:
        if value is None:
            return value
        try:
            return str(IPv4Address(value))  # normalised dotted-quad
        except ValueError:
            raise ValueError(f"{value!r} is not a valid IPv4 address") from None


class LinkLatest(_Base):
    """Newest traffic reading of a link. Direction is from the downstream device's point of view:
    rx = download (upstream device -> downstream device), tx = upload (downstream -> upstream)."""

    ts: datetime
    source: str  # "simulated" | "real"
    rx_mbps: float
    tx_mbps: float
    rx_pps: float
    tx_pps: float
    util_pct: float | None = None  # max(rx, tx) / capacity: a full-duplex link has capacity in EACH direction


class Link(_Base):
    id: str
    a_id: str  # upstream device
    b_id: str  # downstream device
    kind: LinkKind
    capacity_mbps: float = Field(gt=0)
    latest: LinkLatest | None = None


class TopologyNode(_Base):
    id: str
    name: str
    type: DeviceType
    block: CampusBlock
    ip: str
    status: DeviceStatus
    monitoring_mode: MonitoringMode
    parent_id: str | None
    depth: int


class TopologyEdge(_Base):
    id: str
    source: str
    target: str
    kind: LinkKind
    capacity_mbps: float


class Topology(_Base):
    nodes: list[TopologyNode]
    edges: list[TopologyEdge]


class PathHop(_Base):
    id: str
    name: str
    type: DeviceType
    ip: str


class DevicePath(_Base):
    device_id: str
    hops: list[PathHop]  # device first, Internet last
