/** Presentation helpers for device status and metric formatting. */

const COLORS = { online: "green", degraded: "amber", offline: "red", unreachable: "grey", unknown: "grey" };
const LABELS = {
  online: "ONLINE",
  degraded: "DEGRADED",
  offline: "OFFLINE",
  unreachable: "UNREACHABLE",
  unknown: "UNKNOWN",
};

export const statusColor = (status) => COLORS[status] ?? "grey";
export const statusLabel = (status) => LABELS[status] ?? String(status ?? "").toUpperCase();

export function formatMs(value) {
  if (value === null || value === undefined) return "-";
  return value < 10 ? `${value.toFixed(2)} ms` : `${value.toFixed(1)} ms`;
}

export function formatPct(value) {
  if (value === null || value === undefined) return "-";
  return `${value.toFixed(1)}%`;
}

/** 3725 -> "1h 02m", 75 -> "1m 15s", 8 -> "8s" */
export function formatDuration(totalSeconds) {
  if (totalSeconds === null || totalSeconds === undefined || totalSeconds < 0) return "-";
  const s = Math.floor(totalSeconds);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ${String(s % 60).padStart(2, "0")}s`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ${String(m % 60).padStart(2, "0")}m`;
  return `${Math.floor(h / 24)}d ${String(h % 24).padStart(2, "0")}h`;
}

/** Seconds elapsed between an ISO timestamp and `now` (a Date), or null. */
export function secondsSince(iso, now = new Date()) {
  if (!iso) return null;
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return null;
  return Math.max(0, (now.getTime() - then) / 1000);
}

export function formatAgo(iso, now = new Date()) {
  const seconds = secondsSince(iso, now);
  return seconds === null ? "never" : `${formatDuration(seconds)} ago`;
}

/** Why a device deserves a second look, in plain words (empty string when nothing to say). */
export function deviceNote(device, nameById, failureConfirmations = 3) {
  if (device.monitoring_error) return `monitor error: ${device.monitoring_error}`;
  if (device.status === "unreachable" && device.caused_by) {
    return `cut off by ${nameById[device.caused_by] ?? device.caused_by}`;
  }
  if (device.consecutive_failures > 0 && !["offline", "unreachable"].includes(device.status)) {
    return `no reply ${device.consecutive_failures}/${failureConfirmations} cycles`;
  }
  return "";
}

export const STATUS_HEX = { online: "#22c55e", degraded: "#f59e0b", offline: "#ef4444", unreachable: "#64748b", unknown: "#475569" };
export const statusHex = (status) => STATUS_HEX[status] ?? STATUS_HEX.unknown;
