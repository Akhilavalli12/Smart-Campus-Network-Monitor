/** Formatting and colour helpers for the Traffic page. */

export function formatMbps(value) {
  if (value === null || value === undefined) return "-";
  if (value >= 100) return `${value.toFixed(0)} Mbps`;
  if (value >= 10) return `${value.toFixed(1)} Mbps`;
  if (value >= 0.01) return `${value.toFixed(2)} Mbps`;
  return value === 0 ? "0 Mbps" : `${(value * 1000).toFixed(1)} kbps`;
}

export function formatPps(value) {
  if (value === null || value === undefined) return "-";
  return value >= 1000 ? `${(value / 1000).toFixed(1)}k pkt/s` : `${value.toFixed(0)} pkt/s`;
}

export function formatBytes(value) {
  if (value === null || value === undefined) return "-";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let v = value;
  let i = 0;
  while (v >= 1000 && i < units.length - 1) {
    v /= 1000;
    i += 1;
  }
  return `${v.toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
}

const STATE_STYLES = {
  up: { bar: "bg-emerald-500", text: "text-emerald-300", label: "NORMAL" },
  busy: { bar: "bg-amber-400", text: "text-amber-300", label: "BUSY" },
  congested: { bar: "bg-red-500", text: "text-red-400", label: "CONGESTED" },
  down: { bar: "bg-slate-600", text: "text-slate-400", label: "DOWN" },
  unknown: { bar: "bg-slate-700", text: "text-slate-500", label: "NO DATA" },
};

export const stateStyle = (state) => STATE_STYLES[state] ?? STATE_STYLES.unknown;

/** Bar width: utilization clamped to 0-100 (a measured value above 100 is shown full, not overflowing). */
export const barWidth = (utilPct) => (utilPct === null || utilPct === undefined ? 0 : Math.max(0, Math.min(100, utilPct)));

export const PROTOCOL_COLORS = { tcp: "bg-sky-500", udp: "bg-violet-500", dns: "bg-teal-400", icmp: "bg-amber-400", other: "bg-slate-500" };
export const PROTOCOL_LABELS = { tcp: "TCP", udp: "UDP", dns: "DNS", icmp: "ICMP", other: "Other" };
