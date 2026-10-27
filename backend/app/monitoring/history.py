"""Compact, chart-ready device history (averaged into time buckets)."""
from collections import defaultdict
from datetime import datetime, timezone

from pydantic import BaseModel

from app.monitoring.models import Measurement

STATUS_RANK = {"unknown": 0, "online": 1, "degraded": 2, "unreachable": 3, "offline": 4}


class HistoryPoint(BaseModel):
    ts: datetime
    rtt_avg_ms: float | None = None
    rtt_max_ms: float | None = None
    loss_pct: float | None = None
    jitter_ms: float | None = None
    status: str
    source: str


def _bucket_start(ts: datetime, bucket_s: int) -> datetime:
    epoch = ts.astimezone(timezone.utc).timestamp()
    return datetime.fromtimestamp(epoch - epoch % bucket_s, tz=timezone.utc)


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def history_points(rows: list[Measurement], bucket_s: int = 0) -> list[HistoryPoint]:
    """Raw points, or averages per bucket. A bucket reports the WORST status seen in it, so a short outage is never averaged away."""
    usable = [m for m in rows if m.error is None]
    groups: dict[datetime, list[Measurement]] = defaultdict(list)
    for m in usable:
        groups[_bucket_start(m.ts, bucket_s) if bucket_s > 0 else m.ts].append(m)
    points = []
    for ts in sorted(groups):
        g = groups[ts]
        worst = max(g, key=lambda m: STATUS_RANK.get(m.status, 0)).status
        points.append(
            HistoryPoint(
                ts=ts,
                rtt_avg_ms=_mean([m.rtt_avg_ms for m in g if m.rtt_avg_ms is not None]),
                rtt_max_ms=max((m.rtt_max_ms for m in g if m.rtt_max_ms is not None), default=None),
                loss_pct=_mean([m.loss_pct for m in g if m.loss_pct is not None]),
                jitter_ms=_mean([m.jitter_ms for m in g if m.jitter_ms is not None]),
                status=worst,
                source=g[-1].source,
            )
        )
    return points
