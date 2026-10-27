import Badge from "../components/Badge.jsx";
import StatusBadge from "../components/StatusBadge.jsx";
import { usePolling } from "../hooks/usePolling.js";
import { getDevices, getEvents, getMonitoringStatus } from "../services/api.js";
import { deviceNote, formatAgo, formatDuration, formatMs, formatPct, secondsSince, statusColor } from "../status.js";

const th = "px-3 py-2 text-left text-xs font-semibold uppercase tracking-wider text-slate-400";
const td = "px-3 py-2 text-sm";
const REFRESH_MS = 3000;

export function EngineBar({ status, error }) {
  if (error && !status) return <p className="rounded border border-red-500/40 bg-red-500/10 p-3 text-sm text-red-300">Cannot reach the backend: {error}</p>;
  if (!status) return <p className="text-sm text-slate-400">Loading…</p>;
  if (!status.enabled) {
    return <p className="rounded border border-amber-500/40 bg-amber-500/10 p-3 text-sm text-amber-200">The monitoring engine is disabled (MONITORING_ENABLED=false). Data below is whatever was stored last.</p>;
  }
  const stalled = status.last_cycle_at && secondsSince(status.last_cycle_at) > Math.max(30, (status.poll_interval_s ?? 5) * 4);
  return (
    <div className="flex flex-wrap items-center gap-x-6 gap-y-1 rounded border border-slate-800 bg-slate-900 px-3 py-2 text-sm">
      <span className={status.running && !stalled ? "text-emerald-300" : "text-red-300"}>
        {status.running && !stalled ? "Engine running" : stalled ? "Engine stalled" : "Engine stopped"}
      </span>
      <span className="text-slate-400">cycle #{status.cycles_completed}</span>
      <span className="text-slate-400">every {status.poll_interval_s}s</span>
      <span className="text-slate-400">last cycle {formatAgo(status.last_cycle_at)} ({status.last_cycle_duration_ms ?? "-"} ms)</span>
      <span className="text-slate-400">failure detected within {status.detection_time_s}s ({status.failure_confirmations} cycles)</span>
      {status.last_error && <span className="text-amber-300">last error: {status.last_error}</span>}
      {error && <span className="text-amber-300">refresh failed: {error}</span>}
    </div>
  );
}

export function Summary({ devices }) {
  const count = (s) => devices.filter((d) => d.status === s).length;
  const tiles = [
    ["Total", devices.length, "text-slate-100"],
    ["Online", count("online"), "text-emerald-300"],
    ["Degraded", count("degraded"), "text-amber-300"],
    ["Offline", count("offline"), "text-red-400"],
    ["Unreachable", count("unreachable"), "text-slate-400"],
  ];
  return (
    <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
      {tiles.map(([label, value, color]) => (
        <div key={label} className="rounded border border-slate-800 bg-slate-900 px-3 py-2">
          <div className="text-xs uppercase tracking-wider text-slate-400">{label}</div>
          <div className={`text-2xl font-semibold ${color}`}>{value}</div>
        </div>
      ))}
    </div>
  );
}

export function DeviceTable({ devices, failureConfirmations, onSelect }) {
  const nameById = Object.fromEntries(devices.map((d) => [d.id, d.name]));
  const now = new Date();
  return (
    <div className="overflow-x-auto rounded-lg border border-slate-800 bg-slate-900">
      <table className="w-full">
        <thead>
          <tr>{["Status", "Device", "IP", "Latency", "Loss", "Jitter", "Source", "Last seen", "Up for", "Note"].map((h) => <th key={h} className={th}>{h}</th>)}</tr>
        </thead>
        <tbody>
          {devices.map((d) => {
            const metrics = d.latest;
            const up = ["online", "degraded"].includes(d.status) ? secondsSince(d.up_since, now) : null;
            return (
              <tr key={d.id} className={`border-t border-slate-800 ${onSelect ? "cursor-pointer hover:bg-slate-800/60" : ""}`} data-status={d.status} onClick={() => onSelect?.(d.id)}>
                <td className={td}><StatusBadge status={d.status} /></td>
                <td className={td}>{d.name}</td>
                <td className={`${td} font-mono`}>{d.ip}</td>
                <td className={`${td} font-mono`} title="Average RTT of the latest probe cycle">{formatMs(metrics?.rtt_avg_ms)}</td>
                <td className={`${td} font-mono`} title="Packet loss of the latest probe cycle">{formatPct(metrics?.loss_pct)}</td>
                <td className={`${td} font-mono`}>{formatMs(metrics?.jitter_ms)}</td>
                <td className={td}><Badge source={metrics?.source ?? d.monitoring_mode} /></td>
                <td className={`${td} text-slate-400`}>{formatAgo(d.last_seen, now)}</td>
                <td className={`${td} text-slate-400`}>{up === null ? "-" : formatDuration(up)}</td>
                <td className={`${td} text-xs ${d.monitoring_error ? "text-amber-300" : "text-slate-400"}`}>{deviceNote(d, nameById, failureConfirmations)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export function EventFeed({ events }) {
  return (
    <section className="rounded-lg border border-slate-800 bg-slate-900">
      <h2 className="border-b border-slate-800 px-3 py-2 text-sm font-semibold uppercase tracking-wider text-slate-400">Status changes</h2>
      {events.length === 0 && <p className="p-3 text-sm text-slate-500">No status changes yet.</p>}
      <ul className="divide-y divide-slate-800">
        {events.map((e) => (
          <li key={e.id} className="px-3 py-2 text-sm">
            <div className="flex items-center justify-between gap-2">
              <span className="font-medium">{e.device_name}</span>
              <time className="text-xs text-slate-500">{new Date(e.ts).toLocaleTimeString()}</time>
            </div>
            <div className="flex items-center gap-2 text-xs text-slate-400">
              <span>{e.from_status}</span>
              <span aria-hidden="true">→</span>
              <span className={{ green: "text-emerald-300", amber: "text-amber-300", red: "text-red-400", grey: "text-slate-300" }[statusColor(e.to_status)]}>{e.to_status}</span>
            </div>
            <div className="text-xs text-slate-500">{e.reason}</div>
          </li>
        ))}
      </ul>
    </section>
  );
}

export default function Monitoring({ onSelect }) {
  const engine = usePolling(getMonitoringStatus, REFRESH_MS);
  const devices = usePolling(getDevices, REFRESH_MS);
  const events = usePolling((options) => getEvents(15, options), REFRESH_MS);

  return (
    <div className="space-y-4">
      <EngineBar status={engine.data} error={engine.error} />
      {devices.state === "loading" && <p className="text-sm text-slate-400">Loading devices…</p>}
      {devices.state === "error" && !devices.data && <p className="text-sm text-red-300">{devices.error}</p>}
      {devices.data && (
        <>
          <Summary devices={devices.data} />
          <div className="grid gap-4 xl:grid-cols-4">
            <div className="xl:col-span-3">
              <DeviceTable devices={devices.data} failureConfirmations={engine.data?.failure_confirmations ?? 3} onSelect={onSelect} />
            </div>
            <EventFeed events={events.data ?? []} />
          </div>
          <p className="text-xs text-slate-500">
            REAL = measured with genuine ICMP echo requests. SIMULATED = produced by the educational simulator. Click a device for details and history. Latency, loss and jitter are from the latest probe
            cycle; status is judged over a rolling window of cycles. Refreshes every {REFRESH_MS / 1000}s.
          </p>
        </>
      )}
    </div>
  );
}
