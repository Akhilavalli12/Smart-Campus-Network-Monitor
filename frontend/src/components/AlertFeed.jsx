import { SEVERITY_STYLES, TYPE_LABELS, alertDuration } from "../alertsUi.js";

export function SeverityPill({ severity }) {
  return <span className={`inline-block rounded border px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wider ${SEVERITY_STYLES[severity] ?? SEVERITY_STYLES.warning}`}>{severity}</span>;
}

/** Compact list of alerts for the dashboard. */
export default function AlertFeed({ alerts, onSelectDevice, now = new Date() }) {
  return (
    <section className="rounded-lg border border-slate-800 bg-slate-900">
      <h2 className="border-b border-slate-800 px-3 py-2 text-sm font-semibold uppercase tracking-wider text-slate-400">Recent alerts</h2>
      {alerts.length === 0 && <p className="p-3 text-sm text-slate-500">No alerts. The network is healthy.</p>}
      <ul className="divide-y divide-slate-800">
        {alerts.map((a) => (
          <li key={a.id} className="px-3 py-2">
            <button className="block w-full text-left" onClick={() => a.device_id && onSelectDevice?.(a.device_id)}>
              <div className="flex items-center justify-between gap-2">
                <span className="flex items-center gap-2">
                  <SeverityPill severity={a.severity} />
                  <span className="text-sm font-medium">{TYPE_LABELS[a.type] ?? a.type}</span>
                </span>
                <span className={`text-xs ${a.state === "open" ? "text-red-300" : "text-emerald-400"}`}>{a.state === "open" ? "ACTIVE" : "resolved"}</span>
              </div>
              <div className="mt-0.5 text-xs text-slate-300">{a.message}</div>
              <div className="mt-0.5 text-[11px] text-slate-500">
                {new Date(a.opened_at).toLocaleTimeString()} · {a.state === "open" ? "open for" : "lasted"} {alertDuration(a, now)}
              </div>
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
