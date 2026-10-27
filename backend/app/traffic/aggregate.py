"""Pure functions that turn stored link readings into the views the dashboard needs."""
from collections import defaultdict
from datetime import datetime, timezone

from app.monitoring.models import Thresholds
from app.network_model.enums import DeviceType, LinkKind
from app.network_model.models import Device, Link
from app.traffic.models import (
    BlockSeriesPoint,
    BlockTraffic,
    HostTraffic,
    LinkTraffic,
    ProtocolDistribution,
    ProtocolShare,
    SeriesPoint,
    TrafficSample,
    TrafficSummary,
)

CAMPUS_BLOCKS = {"cse": "CSE Block", "library": "Library", "admin": "Admin Block"}
PROTOCOL_ORDER = ("tcp", "udp", "dns", "icmp", "other")
DOWN_STATUSES = ("offline", "unreachable")


def block_uplinks(links: list[Link], devices: list[Device]) -> dict[str, list[Link]]:
    """The links that carry each campus block's traffic: core switch -> that block's devices."""
    by_id = {d.id: d for d in devices}
    result: dict[str, list[Link]] = {block: [] for block in CAMPUS_BLOCKS}
    for link in links:
        parent, child = by_id.get(link.a_id), by_id.get(link.b_id)
        if parent is None or child is None:
            continue
        if parent.type == DeviceType.CORE_SWITCH.value and child.block in CAMPUS_BLOCKS:
            result[child.block].append(link)
    return result


def util_state(util_pct: float | None, thresholds: Thresholds) -> str:
    if util_pct is None:
        return "unknown"
    if util_pct >= thresholds.util_crit_pct:
        return "congested"
    if util_pct >= thresholds.util_warn_pct:
        return "busy"
    return "up"


def link_state(link: Link, by_id: dict[str, Device], thresholds: Thresholds) -> str:
    """down: an end is OFFLINE/UNREACHABLE. congested/busy: utilization above the critical/warning threshold."""
    ends = [by_id.get(link.a_id), by_id.get(link.b_id)]
    if any(d is not None and d.status in DOWN_STATUSES for d in ends):
        return "down"
    return util_state(link.latest.util_pct if link.latest else None, thresholds)


def link_view(link: Link, by_id: dict[str, Device], thresholds: Thresholds) -> LinkTraffic:
    latest = link.latest
    a, b = by_id.get(link.a_id), by_id.get(link.b_id)
    return LinkTraffic(
        id=link.id,
        a_id=link.a_id,
        b_id=link.b_id,
        a_name=a.name if a else link.a_id,
        b_name=b.name if b else link.b_id,
        kind=link.kind,
        capacity_mbps=link.capacity_mbps,
        state=link_state(link, by_id, thresholds),
        ts=latest.ts if latest else None,
        rx_mbps=latest.rx_mbps if latest else None,
        tx_mbps=latest.tx_mbps if latest else None,
        rx_pps=latest.rx_pps if latest else None,
        tx_pps=latest.tx_pps if latest else None,
        util_pct=latest.util_pct if latest else None,
        source=latest.source if latest else None,
    )


def _combine(links: list[Link]) -> tuple[float, float, float, float | None] | None:
    """(rx, tx, capacity, util%) summed over links that have a reading; None if none has."""
    measured = [l for l in links if l.latest is not None]
    if not measured:
        return None
    rx = sum(l.latest.rx_mbps for l in measured)
    tx = sum(l.latest.tx_mbps for l in measured)
    capacity = sum(l.capacity_mbps for l in measured)
    return rx, tx, capacity, max(rx, tx) / capacity * 100.0 if capacity else None


def summarize(links: list[Link], devices: list[Device], thresholds: Thresholds, host: HostTraffic | None = None) -> TrafficSummary:
    by_id = {d.id: d for d in devices}
    blocks: list[BlockTraffic] = []
    for block, block_links in block_uplinks(links, devices).items():
        combined = _combine(block_links)
        if combined is None:
            continue
        rx, tx, capacity, util = combined
        blocks.append(
            BlockTraffic(block=block, name=CAMPUS_BLOCKS[block], link_ids=[l.id for l in block_links], rx_mbps=rx, tx_mbps=tx,
                         total_mbps=rx + tx, capacity_mbps=capacity, util_pct=util, source="simulated", state=util_state(util, thresholds))
        )

    def first(kind: LinkKind) -> LinkTraffic | None:
        link = next((l for l in links if l.kind == kind.value), None)
        return link_view(link, by_id, thresholds) if link else None

    measured = [l for l in links if l.latest is not None and l.latest.util_pct is not None]
    busiest = max(measured, key=lambda l: l.latest.util_pct, default=None)
    times = [l.latest.ts for l in links if l.latest]
    return TrafficSummary(
        as_of=max(times) if times else None,
        blocks=blocks,
        wan=first(LinkKind.WAN),
        backbone=first(LinkKind.BACKBONE),
        busiest_link=link_view(busiest, by_id, thresholds) if busiest else None,
        campus_total_mbps=sum(b.total_mbps for b in blocks),
        host=host,
    )


def host_view(sample: TrafficSample | None) -> HostTraffic | None:
    if sample is None:
        return None
    return HostTraffic(rx_mbps=sample.rx_mbps, tx_mbps=sample.tx_mbps, total_mbps=sample.rx_mbps + sample.tx_mbps,
                       capacity_mbps=sample.capacity_mbps, util_pct=sample.util_pct, source=sample.source,
                       label=sample.label, ts=sample.ts, rx_pps=sample.rx_pps, tx_pps=sample.tx_pps)


def protocol_distribution(samples: list[TrafficSample], window_minutes: float) -> ProtocolDistribution:
    """Share of bytes per protocol over the samples given. SIMULATED: no packet is ever inspected."""
    totals: dict[str, int] = defaultdict(int)
    for sample in samples:
        for name, value in (sample.proto_bytes or {}).items():
            totals[name] += value
    grand = sum(totals.values())
    shares = [
        ProtocolShare(name=name, bytes=totals.get(name, 0), pct=(totals.get(name, 0) / grand * 100.0) if grand else 0.0)
        for name in PROTOCOL_ORDER
    ]
    return ProtocolDistribution(
        source="simulated",
        window_minutes=window_minutes,
        total_bytes=grand,
        protocols=shares,
        note="Simulated split of the campus block uplinks. No packets are captured or inspected. DNS = port 53 (UDP or TCP); TCP and UDP exclude DNS.",
    )


def _bucket_start(ts: datetime, bucket_s: int) -> datetime:
    epoch = ts.astimezone(timezone.utc).timestamp()
    return datetime.fromtimestamp(epoch - epoch % bucket_s, tz=timezone.utc)


def series(samples: list[TrafficSample], bucket_s: int = 0) -> list[SeriesPoint]:
    """Time series of one interface; with bucket_s > 0 samples are averaged per time bucket (keeps charts light)."""
    if bucket_s <= 0:
        return [SeriesPoint(ts=s.ts, rx_mbps=s.rx_mbps, tx_mbps=s.tx_mbps, util_pct=s.util_pct) for s in samples]
    buckets: dict[datetime, list[TrafficSample]] = defaultdict(list)
    for s in samples:
        buckets[_bucket_start(s.ts, bucket_s)].append(s)
    points = []
    for start in sorted(buckets):
        group = buckets[start]
        utils = [s.util_pct for s in group if s.util_pct is not None]
        points.append(SeriesPoint(ts=start, rx_mbps=sum(s.rx_mbps for s in group) / len(group), tx_mbps=sum(s.tx_mbps for s in group) / len(group),
                                  util_pct=sum(utils) / len(utils) if utils else None))
    return points


def blocks_series(samples: list[TrafficSample], link_to_block: dict[str, str], bucket_s: int = 0) -> list[BlockSeriesPoint]:
    """Per-block traffic over time: samples of a block's links taken in the same cycle are summed, then averaged per bucket."""
    per_cycle: dict[datetime, dict[str, list[float]]] = defaultdict(lambda: defaultdict(lambda: [0.0, 0.0]))
    for s in samples:
        block = link_to_block.get(s.ref_id)
        if block is None:
            continue
        acc = per_cycle[s.ts][block]
        acc[0] += s.rx_mbps
        acc[1] += s.tx_mbps
    grouped: dict[datetime, list[dict[str, list[float]]]] = defaultdict(list)
    for ts in sorted(per_cycle):
        grouped[_bucket_start(ts, bucket_s) if bucket_s > 0 else ts].append(per_cycle[ts])
    points = []
    for ts in sorted(grouped):
        cycles = grouped[ts]
        blocks: dict[str, dict[str, float]] = {}
        for block in {b for c in cycles for b in c}:
            rx = sum(c[block][0] for c in cycles if block in c) / len(cycles)
            tx = sum(c[block][1] for c in cycles if block in c) / len(cycles)
            blocks[block] = {"rx_mbps": rx, "tx_mbps": tx, "total_mbps": rx + tx}
        points.append(BlockSeriesPoint(ts=ts, blocks=blocks))
    return points
