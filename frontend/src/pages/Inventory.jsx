import Badge from "../components/Badge.jsx";
import SubnetCalculator from "../components/SubnetCalculator.jsx";
import { useLoad } from "../hooks/useLoad.js";
import { getDevices, getSubnets } from "../services/api.js";

const th = "px-3 py-2 text-left text-xs font-semibold uppercase tracking-wider text-slate-400";
const td = "px-3 py-2 text-sm";

function Panel({ title, children }) {
  return (
    <section className="rounded-lg border border-slate-800 bg-slate-900">
      <h2 className="border-b border-slate-800 px-3 py-2 text-sm font-semibold uppercase tracking-wider text-slate-400">{title}</h2>
      <div className="overflow-x-auto">{children}</div>
    </section>
  );
}

function Problem({ loading, error }) {
  if (loading) return <p className="p-3 text-sm text-slate-400">Loading…</p>;
  return <p className="p-3 text-sm text-red-300">{error}</p>;
}

export default function Inventory() {
  const subnets = useLoad(getSubnets);
  const devices = useLoad(getDevices);
  const nameById = Object.fromEntries((devices.data ?? []).map((d) => [d.id, d.name]));

  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <div className="space-y-4 lg:col-span-2">
        <Panel title="Subnets">
          {subnets.state !== "ready" ? (
            <Problem loading={subnets.state === "loading"} error={subnets.error} />
          ) : (
            <table className="w-full">
              <thead>
                <tr>{["Name", "CIDR", "Mask", "Broadcast", "Usable range", "Gateway"].map((h) => <th key={h} className={th}>{h}</th>)}</tr>
              </thead>
              <tbody className="font-mono">
                {subnets.data.map((s) => (
                  <tr key={s.id} className="border-t border-slate-800">
                    <td className={`${td} font-sans`}>{s.name}</td>
                    <td className={td}>{s.info.cidr}</td>
                    <td className={td}>{s.info.netmask}</td>
                    <td className={td}>{s.info.broadcast_address ?? "-"}</td>
                    <td className={td}>{s.info.first_host} - {s.info.last_host}</td>
                    <td className={td}>{s.gateway ?? "-"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Panel>

        <Panel title={`Devices${devices.data ? ` (${devices.data.length})` : ""}`}>
          {devices.state !== "ready" ? (
            <Problem loading={devices.state === "loading"} error={devices.error} />
          ) : (
            <table className="w-full">
              <thead>
                <tr>{["Name", "Type", "IP", "Block", "Upstream", "Monitoring", "Status"].map((h) => <th key={h} className={th}>{h}</th>)}</tr>
              </thead>
              <tbody>
                {devices.data.map((d) => (
                  <tr key={d.id} className="border-t border-slate-800">
                    <td className={td}>{d.name}</td>
                    <td className={`${td} text-slate-400`}>{d.type.replace("_", " ")}</td>
                    <td className={`${td} font-mono`}>{d.ip}</td>
                    <td className={`${td} text-slate-400`}>{d.block}</td>
                    <td className={`${td} text-slate-400`}>{d.parent_id ? nameById[d.parent_id] ?? d.parent_id : "-"}</td>
                    <td className={td}><Badge source={d.monitoring_mode} /></td>
                    <td className={`${td} text-slate-500`}>{d.status}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Panel>
        <p className="text-xs text-slate-500">
          Status stays &quot;unknown&quot; until the monitoring engine exists (Stage 3). SIMULATED devices are modelled, not physical.
        </p>
      </div>
      <SubnetCalculator />
    </div>
  );
}
