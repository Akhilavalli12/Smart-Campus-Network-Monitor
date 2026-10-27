import Badge from "../components/Badge.jsx";
import UtilBar from "../components/UtilBar.jsx";
import { usePolling } from "../hooks/usePolling.js";
import { getProtocols, getTrafficLinks, getTrafficStatus, getTrafficSummary } from "../services/api.js";
import { formatAgo } from "../status.js";
import { PROTOCOL_COLORS, PROTOCOL_LABELS, formatBytes, formatMbps, formatPps, stateStyle } from "../traffic.js";

const REFRESH_MS = 3000;
const th = "px-3 py-2 text-left text-xs font-semibold uppercase tracking-wider text-slate-400";
const td = "px-3 py-2 text-sm";

function Card({ title, badge, children }) {
  return (
    <section className="rounded-lg border border-slate-800 bg-slate-900 p-4">
      <h2 className="mb-3 flex items-center justify-between text-sm font-semibold uppercase tracking-wider text-slate-400">
        <span>{title}</span>
        {badge}
      </h2>
      {children}
    </section>
  );
}

export function EngineBar({ status, error }) {
  if (error && !status) return <p className="rounded border border-red-500/40 bg-red-500/10 p-3 text-sm text-red-300">Cannot reach the backend: {error}</p>;
  if (!status) return <p className="text-sm text-slate-400">Loading…</p>;
  if (!status.enabled) return <p className="rounded border border-amber-500/40 bg-amber-500/10 p-3 text-sm text-amber-200">The traffic engine is disabled (TRAFFIC_ENABLED=false).</p>;
  return (
    <div className="flex flex-wrap items-center gap-x-6 gap-y-1 rounded border border-slate-800 bg-slate-900 px-3 py-2 text-sm">
      <span className={status.running ? "text-emerald-300" : "text-red-300"}>{status.running ? "Traffic engine running" : "Traffic engine stopped"}</span>
      <span className="text-slate-400">sample #{status.cycles_completed}</span>
      <span className="text-slate-400">every {status.interval_s}s</span>
      <span className="text-slate-400">last {formatAgo(status.last_cycle_at)}</span>
      <span className="text-slate-400">simulated counters: {status.counter_bits}-bit (they wrap)</span>
      {status.last_error && <span className="text-amber-300">last error: {status.last_error}</span>}
    </div>
  );
}

export function BlockCard({ block }) {
  const style = stateStyle(block.state);
  return (
    <Card title={block.name} badge={<Badge source={block.source} />}>
      <div className="mb-1 flex items-baseline justify-between">
        <span className="text-3xl font-semibold">{formatMbps(block.total_mbps)}</span>
        <span className={`text-xs font-semibold ${style.text}`}>{style.label}</span>
      </div>
      <div className="mb-2 flex gap-4 text-xs text-slate-400">
        <span>↓ {formatMbps(block.rx_mbps)}</span>
        <span>↑ {formatMbps(block.tx_mbps)}</span>
        <span>link {block.capacity_mbps} Mbps</span>
      </div>
      <UtilBar utilPct={block.util_pct} state={block.state} />
    </Card>
  );
}

export function LinkCard({ title, link }) {
  if (!link) return null;
  const style = stateStyle(link.state);
  return (
    <Card title={title} badge={link.source ? <Badge source={link.source} /> : null}>
      <div className="mb-1 flex items-baseline justify-between">
        <span className="text-2xl font-semibold">{formatMbps((link.rx_mbps ?? 0) + (link.tx_mbps ?? 0))}</span>
        <span className={`text-xs font-semibold ${style.text}`}>{style.label}</span>
      </div>
      <div className="mb-2 text-xs text-slate-400">
        {link.a_name} ↔ {link.b_name} · {link.capacity_mbps} Mbps
      </div>
      <UtilBar utilPct={link.util_pct} state={link.state} />
    </Card>
  );
}

export function HostCard({ host, status }) {
  return (
    <Card title="This computer's network interface" badge={<Badge source="real" />}>
      {host ? (
        <>
          <div className="mb-1 text-3xl font-semibold">{formatMbps(host.total_mbps)}</div>
          <div className="mb-2 flex flex-wrap gap-4 text-xs text-slate-400">
            <span>↓ {formatMbps(host.rx_mbps)}</span>
            <span>↑ {formatMbps(host.tx_mbps)}</span>
            <span>{formatPps(host.rx_pps)} in</span>
            <span>{formatPps(host.tx_pps)} out</span>
          </div>
          <p className="text-xs text-slate-500">
            {host.label}
            {host.capacity_mbps ? ` · ${host.capacity_mbps} Mbps` : " · link speed unknown, so no utilization"}
          </p>
          {host.util_pct !== null && host.util_pct !== undefined && <UtilBar utilPct={host.util_pct} state={host.util_pct >= 90 ? "congested" : host.util_pct >= 80 ? "busy" : "up"} />}
        </>
      ) : (
        <p className="text-sm text-slate-500">{status?.host_error ?? "Waiting for the first two readings…"}</p>
      )}
      <p className="mt-3 text-xs text-slate-500">Real operating-system counters (psutil) of the machine running the monitor. Not campus traffic.</p>
    </Card>
  );
}

export function ProtocolCard({ data }) {
  return (
    <Card title="Protocol distribution" badge={<Badge source="simulated" />}>
      {!data || data.total_bytes === 0 ? (
        <p className="text-sm text-slate-500">Collecting samples…</p>
      ) : (
        <>
          <div className="mb-3 flex h-4 overflow-hidden rounded bg-slate-800" role="img" aria-label="Protocol distribution">
            {data.protocols.map((p) => (
              <div key={p.name} className={PROTOCOL_COLORS[p.name]} style={{ width: `${p.pct}%` }} title={`${PROTOCOL_LABELS[p.name]} ${p.pct.toFixed(1)}%`} />
            ))}
          </div>
          <ul className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm sm:grid-cols-5">
            {data.protocols.map((p) => (
              <li key={p.name} className="flex items-center gap-2">
                <span className={`inline-block h-2.5 w-2.5 rounded-sm ${PROTOCOL_COLORS[p.name]}`} aria-hidden="true" />
                <span>{PROTOCOL_LABELS[p.name]}</span>
                <span className="font-mono text-slate-300">{p.pct.toFixed(1)}%</span>
              </li>
            ))}
          </ul>
          <p className="mt-3 text-xs text-slate-500">
            {formatBytes(data.total_bytes)} over the last {data.window_minutes} min. {data.note}
          </p>
        </>
      )}
    </Card>
  );
}

export function LinkTable({ links }) {
  return (
    <div className="overflow-x-auto rounded-lg border border-slate-800 bg-slate-900">
      <table className="w-full">
        <thead>
          <tr>{["Link", "Kind", "Capacity", "Download ↓", "Upload ↑", "Packets/s", "Utilization", "State", "Source"].map((h) => <th key={h} className={th}>{h}</th>)}</tr>
        </thead>
        <tbody>
          {links.map((l) => {
            const style = stateStyle(l.state);
            return (
              <tr key={l.id} className="border-t border-slate-800">
                <td className={td}>{l.a_name} → {l.b_name}</td>
                <td className={`${td} text-slate-400`}>{l.kind}</td>
                <td className={`${td} font-mono`}>{l.capacity_mbps} Mbps</td>
                <td className={`${td} font-mono`}>{formatMbps(l.rx_mbps)}</td>
                <td className={`${td} font-mono`}>{formatMbps(l.tx_mbps)}</td>
                <td className={`${td} font-mono text-slate-400`}>{formatPps((l.rx_pps ?? 0) + (l.tx_pps ?? 0))}</td>
                <td className={`${td} w-48`}><UtilBar utilPct={l.util_pct} state={l.state} /></td>
                <td className={`${td} text-xs font-semibold ${style.text}`}>{style.label}</td>
                <td className={td}>{l.source ? <Badge source={l.source} /> : "-"}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export default function Traffic() {
  const status = usePolling(getTrafficStatus, REFRESH_MS);
  const summary = usePolling(getTrafficSummary, REFRESH_MS);
  const links = usePolling(getTrafficLinks, REFRESH_MS);
  const protocols = usePolling((options) => getProtocols(5, options), REFRESH_MS);

  const blocks = summary.data?.blocks ?? [];
  return (
    <div className="space-y-4">
      <EngineBar status={status.data} error={status.error} />
      {summary.state === "loading" && <p className="text-sm text-slate-400">Loading traffic…</p>}
      {summary.state === "error" && !summary.data && <p className="text-sm text-red-300">{summary.error}</p>}
      {summary.data && blocks.length === 0 && (
        <p className="rounded border border-slate-800 bg-slate-900 p-3 text-sm text-slate-400">
          No traffic readings yet. A rate needs two counter readings, so the first numbers appear one sample interval after the engine starts.
        </p>
      )}
      {blocks.length > 0 && (
        <>
          <div className="grid gap-4 md:grid-cols-3">
            {blocks.map((b) => <BlockCard key={b.block} block={b} />)}
          </div>
          <div className="grid gap-4 md:grid-cols-3">
            <LinkCard title="WAN link (Internet)" link={summary.data.wan} />
            <LinkCard title="Backbone (edge router ↔ core)" link={summary.data.backbone} />
            <HostCard host={summary.data.host} status={status.data} />
          </div>
          <ProtocolCard data={protocols.data} />
        </>
      )}
      {links.data && <LinkTable links={links.data} />}
      <p className="text-xs text-slate-500">
        Rates come from interface-counter differences: rate = (counter now − counter before) × 8 ÷ seconds. Utilization = the busier direction ÷ link capacity.
        SIMULATED = educational traffic model; REAL = this computer's own counters. Refreshes every {REFRESH_MS / 1000}s.
      </p>
    </div>
  );
}
