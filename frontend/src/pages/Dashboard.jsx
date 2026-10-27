import { useState } from "react";
import AlertFeed from "../components/AlertFeed.jsx";
import Badge from "../components/Badge.jsx";
import KpiCard from "../components/KpiCard.jsx";
import RangeSelect from "../components/RangeSelect.jsx";
import TimeChart from "../components/TimeChart.jsx";
import TopologyView, { TopologyLegend } from "../components/TopologyView.jsx";
import { blockRows, bucketFor } from "../charts.js";
import { usePolling } from "../hooks/usePolling.js";
import { getAlerts, getBlocksHistory, getDashboard, getDevices, getProtocols, getTrafficLinks } from "../services/api.js";
import { formatMs, formatPct } from "../status.js";
import { DeviceTable } from "./Monitoring.jsx";
import { ProtocolCard } from "./Traffic.jsx";

export function kpiTiles(s) {
  const d = s.devices;
  return [
    { label: "Total devices", value: d.total, sub: `${d.simulated} simulated · ${d.real} real`, tone: "neutral" },
    { label: "Online", value: d.online, sub: d.unknown ? `${d.unknown} not measured yet` : "", tone: "good" },
    { label: "Degraded", value: d.degraded, sub: "slow or lossy", tone: d.degraded ? "warn" : "muted" },
    { label: "Offline", value: d.offline, sub: d.unreachable ? `+ ${d.unreachable} unreachable behind it` : "", tone: d.offline ? "bad" : "muted" },
    { label: "Active alerts", value: s.active_alerts, sub: s.active_alerts ? `${s.critical_alerts} critical · ${s.warning_alerts} warning` : "all clear", tone: s.critical_alerts ? "bad" : s.active_alerts ? "warn" : "good" },
    { label: "Avg latency", value: formatMs(s.avg_latency_ms), sub: "reachable devices, windowed", tone: s.avg_latency_ms >= 100 ? "warn" : "neutral" },
    { label: "Avg packet loss", value: formatPct(s.avg_packet_loss_pct), sub: "all devices, windowed", tone: s.avg_packet_loss_pct >= 5 ? "warn" : "neutral" },
    {
      label: "Network utilization",
      value: formatPct(s.avg_utilization_pct),
      sub: s.busiest_link_name ? `busiest: ${s.busiest_link_name} ${formatPct(s.busiest_link_util_pct)}` : "no traffic yet",
      tone: s.utilization_state === "congested" ? "bad" : s.utilization_state === "busy" ? "warn" : "neutral",
    },
  ];
}

export function KpiStrip({ summary }) {
  if (!summary) return <p className="text-sm text-slate-400">Loading…</p>;
  const tiles = kpiTiles(summary);
  return (
    <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 xl:grid-cols-8">
      {tiles.map((t, i) => <KpiCard key={t.label} {...t} badge={i >= 5 && i <= 7 ? <Badge source="simulated" /> : null} />)}
    </div>
  );
}

export default function Dashboard({ onSelect, selectedId }) {
  const [hours, setHours] = useState(6);
  const summary = usePolling(getDashboard, 3000);
  const devices = usePolling(getDevices, 3000);
  const links = usePolling(getTrafficLinks, 3000);
  const alerts = usePolling((o) => getAlerts(null, 8, o), 4000);
  const blocks = usePolling((o) => getBlocksHistory(hours, bucketFor(hours), o), 15000, [hours]);
  const protocols = usePolling((o) => getProtocols(5, o), 10000);

  const rows = blockRows(blocks.data ?? []);
  return (
    <div className="space-y-4">
      {summary.error && !summary.data && <p className="rounded border border-red-500/40 bg-red-500/10 p-3 text-sm text-red-300">Cannot reach the backend: {summary.error}</p>}
      {summary.data?.demo_history_loaded_at && (
        <p className="rounded border border-sky-500/30 bg-sky-500/5 px-3 py-1.5 text-xs text-sky-200">
          Demo history loaded at {new Date(summary.data.demo_history_loaded_at).toLocaleString()}: the charts before that moment show generated demo data. Everything after it is live.
        </p>
      )}
      <KpiStrip summary={summary.data} />

      <div className="grid gap-4 xl:grid-cols-3">
        <div className="space-y-2 xl:col-span-2">
          <h2 className="text-sm font-semibold uppercase tracking-wider text-slate-400">Campus network topology</h2>
          {devices.data ? <TopologyView devices={devices.data} links={links.data ?? []} selectedId={selectedId} onSelect={onSelect} height={500} /> : <p className="text-sm text-slate-400">Loading topology…</p>}
          <TopologyLegend />
        </div>
        <AlertFeed alerts={alerts.data ?? []} onSelectDevice={onSelect} />
      </div>

      <div className="grid gap-4 xl:grid-cols-3">
        <section className="rounded-lg border border-slate-800 bg-slate-900 p-3 xl:col-span-2">
          <div className="mb-2 flex items-center justify-between">
            <h2 className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wider text-slate-400">Traffic by campus block (Mbps) <Badge source="simulated" /></h2>
            <RangeSelect hours={hours} onChange={setHours} />
          </div>
          <TimeChart data={rows} hours={hours} unit="Mbps" area stacked height={220} series={[{ key: "cse", label: "CSE Block", color: "#38bdf8" }, { key: "library", label: "Library", color: "#22c55e" }, { key: "admin", label: "Admin Block", color: "#a78bfa" }]} />
        </section>
        <ProtocolCard data={protocols.data} />
      </div>

      {devices.data && (
        <section className="space-y-2">
          <h2 className="text-sm font-semibold uppercase tracking-wider text-slate-400">Devices (click one for details and history)</h2>
          <DeviceTable devices={devices.data} failureConfirmations={3} onSelect={onSelect} />
        </section>
      )}
    </div>
  );
}
