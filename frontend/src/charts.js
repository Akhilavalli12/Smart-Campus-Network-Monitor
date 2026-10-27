/** Data preparation for the time-series charts. */

export const RANGES = [
  { hours: 1, label: "1 h" },
  { hours: 6, label: "6 h" },
  { hours: 24, label: "24 h" },
];

/** Average samples into buckets so a chart never has to draw more than about `target` points. */
export function bucketFor(hours, target = 240) {
  return Math.max(0, Math.ceil((hours * 3600) / target));
}

export const toMs = (iso) => new Date(iso).getTime();

export function formatClock(ms, hours = 1) {
  const d = new Date(ms);
  const hh = String(d.getHours()).padStart(2, "0");
  const mm = String(d.getMinutes()).padStart(2, "0");
  return hours > 24 ? `${d.getMonth() + 1}/${d.getDate()} ${hh}:${mm}` : `${hh}:${mm}`;
}

const rounded = (v, digits = 2) => (v === null || v === undefined ? null : Number(v.toFixed(digits)));

/** Device history points -> rows for the latency and loss charts. */
export function latencyRows(points) {
  return points.map((p) => ({ t: toMs(p.ts), avg: rounded(p.rtt_avg_ms), max: rounded(p.rtt_max_ms), jitter: rounded(p.jitter_ms), loss: rounded(p.loss_pct, 1), status: p.status }));
}

/** Link history points -> rows for the traffic and utilization charts. */
export function trafficRows(points) {
  return points.map((p) => ({ t: toMs(p.ts), down: rounded(p.rx_mbps), up: rounded(p.tx_mbps), util: rounded(p.util_pct, 1) }));
}

/** Per-block history -> one row per time with a total per block. */
export function blockRows(points) {
  return points.map((p) => ({
    t: toMs(p.ts),
    cse: rounded(p.blocks.cse?.total_mbps ?? null),
    library: rounded(p.blocks.library?.total_mbps ?? null),
    admin: rounded(p.blocks.admin?.total_mbps ?? null),
  }));
}

/** Time ranges where the device was not reachable, for shading outages on a chart. */
export function outageSpans(rows) {
  const spans = [];
  let start = null;
  rows.forEach((row, i) => {
    const down = row.status === "offline" || row.status === "unreachable";
    if (down && start === null) start = row.t;
    if (!down && start !== null) {
      spans.push({ from: start, to: rows[i - 1].t });
      start = null;
    }
  });
  if (start !== null) spans.push({ from: start, to: rows[rows.length - 1].t });
  return spans;
}
