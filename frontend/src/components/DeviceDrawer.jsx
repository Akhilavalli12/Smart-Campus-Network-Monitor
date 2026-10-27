import { useState } from "react";
import { bucketFor, latencyRows, outageSpans, trafficRows } from "../charts.js";
import { usePolling } from "../hooks/usePolling.js";
import { getAlerts, getDevice, getDeviceHistory, getLinkHistory, getTrafficLinks } from "../services/api.js";
import { deviceNote, formatAgo, formatDuration, formatMs, formatPct, secondsSince } from "../status.js";
import { TYPE_LABELS } from "../topologyLayout.js";
import { formatMbps, formatPps } from "../traffic.js";
import { linkIdFor } from "../topologyLayout.js";
import { SeverityPill } from "./AlertFeed.jsx";
import Badge from "./Badge.jsx";
import RangeSelect from "./RangeSelect.jsx";
import StatusBadge from "./StatusBadge.jsx";
import TimeChart from "./TimeChart.jsx";
import UtilBar from "./UtilBar.jsx";

function Field({ label, children }) {
  return (
    <div>
      <dt className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">{label}</dt>
      <dd className="font-mono text-sm text-slate-100">{children ?? "-"}</dd>
    </div>
  );
}

function ChartBox({ title, children }) {
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-950 p-2">
      <div className="mb-1 text-xs font-semibold uppercase tracking-wider text-slate-400">{title}</div>
      {children}
    </div>
  );
}

export function DeviceInfo({ device, parentName, now = new Date() }) {
  const m = device.latest;
  const up = ["online", "degraded"].includes(device.status) ? secondsSince(device.up_since, now) : null;
  return (
    <dl className="grid grid-cols-2 gap-x-4 gap-y-2 sm:grid-cols-3">
      <Field label="IP address">{device.ip}</Field>
      <Field label="Type">{TYPE_LABELS[device.type] ?? device.type}</Field>
      <Field label="Subnet">{device.subnet_id}</Field>
      <Field label="Campus block">{device.block}</Field>
      <Field label="Location">{device.location}</Field>
      <Field label="Upstream device">{parentName}</Field>
      <Field label="MAC (simulated)">{device.mac}</Field>
      <Field label="Monitoring">
        <Badge source={m?.source ?? device.monitoring_mode} />
        {device.probe_target ? <span className="ml-2 text-xs text-slate-400">probing {device.probe_target}</span> : null}
      </Field>
      <Field label="Uptime">{up === null ? "-" : formatDuration(up)}</Field>
      <Field label="Last seen">{formatAgo(device.last_seen, now)}</Field>
      <Field label="Latency (avg / min / max)">{m ? `${formatMs(m.rtt_avg_ms)} / ${formatMs(m.rtt_min_ms)} / ${formatMs(m.rtt_max_ms)}` : "-"}</Field>
      <Field label="Jitter">{formatMs(m?.jitter_ms)}</Field>
      <Field label="Packet loss (cycle / window)">{m ? `${formatPct(m.loss_pct)} / ${formatPct(m.window_loss_pct)}` : "-"}</Field>
      <Field label="Packets (last cycle)">{m ? `${m.sent} sent / ${m.received} received` : "-"}</Field>
      {device.caused_by ? <Field label="Cut off by (root cause)">{device.caused_by}</Field> : null}
    </dl>
  );
}

export default function DeviceDrawer({ deviceId, onClose }) {
  const [hours, setHours] = useState(1);
  const bucket = bucketFor(hours);
  const device = usePolling((o) => getDevice(deviceId, o), 3000, [deviceId]);
  const links = usePolling(getTrafficLinks, 3000);
  const alerts = usePolling((o) => getAlerts("open", 100, o), 5000);
  const history = usePolling((o) => getDeviceHistory(deviceId, hours, bucket, o), 10000, [deviceId, hours]);
  const parentId = device.data?.parent_id;
  const linkId = device.data ? linkIdFor(device.data) : null;
  const traffic = usePolling((o) => (linkId ? getLinkHistory(linkId, hours, bucket, o) : Promise.resolve([])), 10000, [linkId, hours]);

  const d = device.data;
  const link = links.data?.find((l) => l.id === linkId);
  const mine = (alerts.data ?? []).filter((a) => a.device_id === deviceId || (a.affected_device_ids ?? []).includes(deviceId));
  const lat = latencyRows(history.data ?? []);
  const traf = trafficRows(traffic.data ?? []);

  return (
    <aside className="fixed inset-y-0 right-0 z-40 w-full max-w-3xl overflow-y-auto border-l border-slate-700 bg-slate-900 p-4 shadow-2xl" aria-label="Device details">
      <div className="mb-3 flex items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold">{d?.name ?? deviceId}</h2>
          {d && <StatusBadge status={d.status} />}
          {d && <span className="ml-3 text-xs text-amber-300">{deviceNote(d, { [d.caused_by ?? ""]: d.caused_by }, 3)}</span>}
        </div>
        <button onClick={onClose} className="rounded border border-slate-700 px-2 py-1 text-sm text-slate-300 hover:bg-slate-800" aria-label="Close details">Close ✕</button>
      </div>

      {device.state === "loading" && <p className="text-sm text-slate-400">Loading…</p>}
      {device.state === "error" && !d && <p className="text-sm text-red-300">{device.error}</p>}
      {d && (
        <div className="space-y-4">
          {mine.length > 0 && (
            <div className="space-y-1 rounded border border-red-500/30 bg-red-500/5 p-2">
              {mine.map((a) => (
                <div key={a.id} className="flex items-start gap-2 text-sm">
                  <SeverityPill severity={a.severity} />
                  <span className="text-slate-200">{a.message}</span>
                </div>
              ))}
            </div>
          )}

          <DeviceInfo device={d} parentName={parentId} />

          {link && (
            <div className="rounded-lg border border-slate-800 bg-slate-950 p-3">
              <div className="mb-1 flex items-center justify-between text-xs font-semibold uppercase tracking-wider text-slate-400">
                <span>Uplink bandwidth ({link.a_name})</span>
                {link.source && <Badge source={link.source} />}
              </div>
              <div className="mb-2 flex flex-wrap gap-x-6 gap-y-1 text-sm">
                <span>↓ {formatMbps(link.rx_mbps)}</span>
                <span>↑ {formatMbps(link.tx_mbps)}</span>
                <span className="text-slate-400">{formatPps(link.rx_pps)} in · {formatPps(link.tx_pps)} out</span>
                <span className="text-slate-400">capacity {link.capacity_mbps} Mbps</span>
              </div>
              <UtilBar utilPct={link.util_pct} state={link.state} />
            </div>
          )}

          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-400">History</h3>
            <RangeSelect hours={hours} onChange={setHours} />
          </div>
          <div className="grid gap-3 md:grid-cols-2">
            <ChartBox title="Latency (ms)"><TimeChart data={lat} hours={hours} unit="ms" spans={outageSpans(lat)} series={[{ key: "avg", label: "average", color: "#38bdf8" }, { key: "max", label: "max", color: "#64748b" }]} /></ChartBox>
            <ChartBox title="Packet loss (%)"><TimeChart data={lat} hours={hours} unit="%" yMax={100} area spans={outageSpans(lat)} series={[{ key: "loss", label: "loss", color: "#f59e0b" }]} /></ChartBox>
            {linkId && <ChartBox title="Uplink traffic (Mbps)"><TimeChart data={traf} hours={hours} unit="Mbps" series={[{ key: "down", label: "download", color: "#22c55e" }, { key: "up", label: "upload", color: "#a78bfa" }]} /></ChartBox>}
            {linkId && <ChartBox title="Uplink utilization (%)"><TimeChart data={traf} hours={hours} unit="%" yMax={100} area series={[{ key: "util", label: "utilization", color: "#ef4444" }]} /></ChartBox>}
          </div>
          <p className="text-xs text-slate-500">
            Shaded red = the device was OFFLINE or UNREACHABLE. {d.monitoring_mode === "simulated" ? "All values for this device are SIMULATED." : "Latency and loss are REAL ICMP measurements."} History
            from before the demo loader ran is generated demo data.
          </p>
        </div>
      )}
    </aside>
  );
}
