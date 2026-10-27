import { useState } from "react";
import { SeverityPill } from "../components/AlertFeed.jsx";
import { usePolling } from "../hooks/usePolling.js";
import { acknowledgeAlert, getAlertSummary, getAlerts } from "../services/api.js";
import { TYPE_LABELS, alertDuration, peakText } from "../alertsUi.js";

const th = "px-3 py-2 text-left text-xs font-semibold uppercase tracking-wider text-slate-400";
const td = "px-3 py-2 text-sm align-top";
const FILTERS = [["open", "Active"], ["resolved", "Resolved"], [null, "All"]];

export function AlertTable({ alerts, onAcknowledge, onSelectDevice, now = new Date() }) {
  if (alerts.length === 0) return <p className="rounded-lg border border-slate-800 bg-slate-900 p-4 text-sm text-slate-400">No alerts in this view.</p>;
  return (
    <div className="overflow-x-auto rounded-lg border border-slate-800 bg-slate-900">
      <table className="w-full">
        <thead>
          <tr>{["Severity", "Type", "Message", "Opened", "Duration", "Peak", "State", ""].map((h) => <th key={h} className={th}>{h}</th>)}</tr>
        </thead>
        <tbody>
          {alerts.map((a) => (
            <tr key={a.id} className="border-t border-slate-800" data-state={a.state}>
              <td className={td}><SeverityPill severity={a.severity} /></td>
              <td className={`${td} whitespace-nowrap`}>{TYPE_LABELS[a.type] ?? a.type}</td>
              <td className={td}>
                <button className="text-left hover:underline" onClick={() => a.device_id && onSelectDevice?.(a.device_id)}>{a.message}</button>
                {a.affected_device_ids?.length > 0 && <div className="mt-0.5 text-xs text-slate-500">Root cause of {a.affected_device_ids.length} unreachable device(s)</div>}
              </td>
              <td className={`${td} whitespace-nowrap text-slate-400`}>{new Date(a.opened_at).toLocaleString()}</td>
              <td className={`${td} whitespace-nowrap font-mono text-slate-300`}>{alertDuration(a, now)}</td>
              <td className={`${td} whitespace-nowrap font-mono text-slate-300`}>{peakText(a)}</td>
              <td className={`${td} whitespace-nowrap`}>
                <span className={a.state === "open" ? "text-red-300" : "text-emerald-400"}>{a.state === "open" ? "ACTIVE" : `resolved ${new Date(a.resolved_at).toLocaleTimeString()}`}</span>
              </td>
              <td className={td}>
                {a.state === "open" && !a.acknowledged && <button onClick={() => onAcknowledge(a.id)} className="rounded border border-slate-600 px-2 py-0.5 text-xs hover:bg-slate-800">Acknowledge</button>}
                {a.acknowledged && <span className="text-xs text-slate-500">acknowledged</span>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function Alerts({ onSelect }) {
  const [filter, setFilter] = useState("open");
  const alerts = usePolling((o) => getAlerts(filter, 200, o), 3000, [filter]);
  const summary = usePolling(getAlertSummary, 3000);
  const s = summary.data;

  async function acknowledge(id) {
    await acknowledgeAlert(id);
    alerts.refresh();
    summary.refresh();
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="inline-flex gap-1 rounded-lg bg-slate-900 p-1">
          {FILTERS.map(([value, label]) => (
            <button key={label} onClick={() => setFilter(value)} className={`rounded px-3 py-1 text-sm ${filter === value ? "bg-slate-700 text-white" : "text-slate-400 hover:text-white"}`}>{label}</button>
          ))}
        </div>
        {s && <p className="text-sm text-slate-400">{s.active} active · {s.critical} critical · {s.warning} warning · {s.unacknowledged} unacknowledged</p>}
      </div>
      {alerts.error && !alerts.data && <p className="text-sm text-red-300">{alerts.error}</p>}
      {alerts.data && <AlertTable alerts={alerts.data} onAcknowledge={acknowledge} onSelectDevice={onSelect} />}
      <p className="text-xs text-slate-500">
        Alerts open and resolve by themselves. One alert per problem: devices cut off behind a failed switch are listed on the switch's alert instead of raising their own.
        Thresholds are configurable settings (not standards), and an alert only clears once the value is clearly back below its threshold (hysteresis).
      </p>
    </div>
  );
}
