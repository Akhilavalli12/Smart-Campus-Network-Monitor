"""Models for stored traffic samples and the API views built from them."""
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class _Base(BaseModel):
    model_config = ConfigDict(use_enum_values=True)


class TrafficSample(_Base):
    """One interval of one interface (a campus link, or the monitoring host's own NIC)."""

    scope: str  # "link" | "host"
    ref_id: str  # link id, or "host"
    ts: datetime
    source: str  # "simulated" | "real"
    label: str | None = None  # host: which interface(s) were read
    dt_s: float
    capacity_mbps: float | None = None
    # Raw cumulative counters at the end of the interval (they may have wrapped):
    rx_bytes: int
    tx_bytes: int
    rx_packets: int
    tx_packets: int
    # Derived from the counter DIFFERENCE and the elapsed time:
    rx_mbps: float
    tx_mbps: float
    rx_pps: float
    tx_pps: float
    util_pct: float | None = None
    wrapped: bool = False
    proto_bytes: dict[str, int] | None = None  # SIMULATED protocol split of this interval's bytes


class Rate(_Base):
    rx_mbps: float
    tx_mbps: float
    total_mbps: float
    capacity_mbps: float | None = None
    util_pct: float | None = None
    source: str


class BlockTraffic(Rate):
    block: str
    name: str
    link_ids: list[str]
    state: str  # up | busy | congested (utilization against the configured thresholds)


class LinkTraffic(_Base):
    id: str
    a_id: str
    b_id: str
    a_name: str
    b_name: str
    kind: str
    capacity_mbps: float
    state: str  # up | busy | congested | down | unknown
    ts: datetime | None = None
    rx_mbps: float | None = None
    tx_mbps: float | None = None
    rx_pps: float | None = None
    tx_pps: float | None = None
    util_pct: float | None = None
    source: str | None = None


class HostTraffic(Rate):
    label: str | None = None
    ts: datetime
    rx_pps: float
    tx_pps: float


class TrafficSummary(_Base):
    as_of: datetime | None
    blocks: list[BlockTraffic]
    wan: LinkTraffic | None
    backbone: LinkTraffic | None
    busiest_link: LinkTraffic | None
    campus_total_mbps: float
    host: HostTraffic | None


class ProtocolShare(_Base):
    name: str
    bytes: int
    pct: float


class ProtocolDistribution(_Base):
    source: str  # always "simulated" here
    window_minutes: float
    total_bytes: int
    protocols: list[ProtocolShare]
    note: str


class SeriesPoint(_Base):
    ts: datetime
    rx_mbps: float
    tx_mbps: float
    util_pct: float | None = None


class BlockSeriesPoint(_Base):
    ts: datetime
    blocks: dict[str, dict[str, float]]  # block -> {"rx_mbps", "tx_mbps", "total_mbps"}
