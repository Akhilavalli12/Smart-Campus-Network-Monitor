import { formatDuration } from "./status.js";

export const SEVERITY_STYLES = {
  critical: "border-red-500/40 bg-red-500/10 text-red-300",
  warning: "border-amber-500/40 bg-amber-500/10 text-amber-200",
};

export const TYPE_LABELS = {
  DEVICE_OFFLINE: "Device offline",
  HIGH_LATENCY: "High latency",
  HIGH_PACKET_LOSS: "High packet loss",
  HIGH_UTILIZATION: "High utilization",
};

export const PEAK_UNITS = { DEVICE_OFFLINE: "% loss", HIGH_LATENCY: "ms", HIGH_PACKET_LOSS: "% loss", HIGH_UTILIZATION: "% utilization" };

/** How long an alert lasted (resolved) or has been open (active). */
export function alertDuration(alert, now = new Date()) {
  const end = alert.resolved_at ? new Date(alert.resolved_at) : now;
  return formatDuration(Math.max(0, (end.getTime() - new Date(alert.opened_at).getTime()) / 1000));
}

export function peakText(alert) {
  const peak = alert.metrics?.peak;
  if (peak === null || peak === undefined) return "-";
  return `${Number(peak).toFixed(peak >= 100 ? 0 : 1)} ${PEAK_UNITS[alert.type] ?? ""}`.trim();
}
