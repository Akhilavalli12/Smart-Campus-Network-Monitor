import { useState } from "react";
import { usePolling } from "../hooks/usePolling.js";
import { clearAllFaults, clearFault, getMonitoringStatus, getSimulationState, injectFault, runScenario } from "../services/api.js";

const FAULT_LABELS = { offline: "Device OFFLINE", high_latency: "High latency", packet_loss: "Packet loss", congestion: "Network congestion" };
const PARAM_LABELS = { rtt_ms: "Target RTT (ms)", loss_pct: "Loss (%)", utilization_pct: "Utilization (%)" };
export const PARAM_DEFAULTS = { rtt_ms: 180, loss_pct: 12, utilization_pct: 95 };

/** Build the request body for the inject form: only the parameters the fault takes, as numbers. */
export function buildFaultRequest(deviceId, fault, values, catalog) {
  const params = {};
  for (const name of Object.keys(catalog[fault] ?? {})) {
    const raw = values[name];
    params[name] = raw === undefined || raw === "" ? PARAM_DEFAULTS[name] : Number(raw);
  }
  return { device_id: deviceId, fault, params };
}

export function groupByBlock(devices) {
  const groups = {};
  for (const d of devices) (groups[d.block] ??= []).push(d);
  return groups;
}

export function ScenarioCard({ scenario, onRun, busy }) {
  return (
    <div className="flex flex-col justify-between rounded-lg border border-slate-800 bg-slate-900 p-3">
      <div>
        <h3 className="font-semibold">{scenario.name}</h3>
        <p className="mt-1 text-sm text-slate-400">{scenario.description}</p>
        <p className="mt-2 text-xs text-slate-500"><span className="font-semibold text-slate-400">Expect:</span> {scenario.expect}</p>
      </div>
      <button disabled={busy} onClick={() => onRun(scenario.id)} className="mt-3 rounded bg-amber-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-amber-500 disabled:opacity-50">Run scenario</button>
    </div>
  );
}

export default function Simulation() {
  const sim = usePolling(getSimulationState, 3000);
  const engine = usePolling(getMonitoringStatus, 10000);
  const [deviceId, setDeviceId] = useState("cse-switch");
  const [fault, setFault] = useState("offline");
  const [values, setValues] = useState({});
  const [message, setMessage] = useState(null);
  const [busy, setBusy] = useState(false);

  const state = sim.data;
  const detection = engine.data?.detection_time_s;
  const hint = detection ? ` The monitoring engine should detect it within about ${detection} s.` : "";

  async function act(fn, okText) {
    setBusy(true);
    try {
      await fn();
      setMessage({ ok: true, text: okText + hint });
      sim.refresh();
    } catch (err) {
      setMessage({ ok: false, text: err.message });
    } finally {
      setBusy(false);
    }
  }

  if (!state) return <p className="text-sm text-slate-400">{sim.error ?? "Loading…"}</p>;
  const catalog = state.fault_catalog;
  const groups = groupByBlock(state.devices);
  const params = Object.keys(catalog[fault] ?? {});

  return (
    <div className="space-y-5">
      <p className="rounded border border-amber-500/40 bg-amber-500/10 p-3 text-sm text-amber-200">
        <strong>Simulation control (demo tool).</strong> Faults are injected into SIMULATED devices only; real measurements are never altered. The monitoring and alert engines detect each fault by themselves, exactly as they would a real one.
        {!state.enabled && " Fault injection is currently disabled (SIMULATION_ENABLED=false)."}
      </p>

      {message && <p className={`rounded border p-2 text-sm ${message.ok ? "border-emerald-500/40 text-emerald-300" : "border-red-500/40 text-red-300"}`}>{message.text}</p>}

      <section className="grid gap-4 lg:grid-cols-3">
        <form
          className="space-y-3 rounded-lg border border-slate-800 bg-slate-900 p-4 lg:col-span-2"
          onSubmit={(e) => {
            e.preventDefault();
            act(() => injectFault(buildFaultRequest(deviceId, fault, values, catalog)), `Injected ${FAULT_LABELS[fault]} into ${deviceId}.`);
          }}
        >
          <h2 className="text-sm font-semibold uppercase tracking-wider text-slate-400">Inject a fault</h2>
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="text-sm">
              <span className="mb-1 block text-xs text-slate-400">Device</span>
              <select value={deviceId} onChange={(e) => setDeviceId(e.target.value)} className="w-full rounded border border-slate-700 bg-slate-950 px-2 py-1.5">
                {Object.entries(groups).map(([block, devices]) => (
                  <optgroup key={block} label={block.toUpperCase()}>
                    {devices.map((d) => <option key={d.id} value={d.id}>{d.name} ({d.ip}){d.fault !== "none" ? ` — ${d.fault}` : ""}</option>)}
                  </optgroup>
                ))}
              </select>
            </label>
            <label className="text-sm">
              <span className="mb-1 block text-xs text-slate-400">Fault</span>
              <select value={fault} onChange={(e) => { setFault(e.target.value); setValues({}); }} className="w-full rounded border border-slate-700 bg-slate-950 px-2 py-1.5">
                {Object.keys(catalog).map((f) => <option key={f} value={f}>{FAULT_LABELS[f] ?? f}</option>)}
              </select>
            </label>
          </div>
          {params.map((name) => (
            <label key={name} className="block text-sm">
              <span className="mb-1 block text-xs text-slate-400">{PARAM_LABELS[name] ?? name} (allowed {catalog[fault][name][0]}–{catalog[fault][name][1]})</span>
              <input type="number" step="any" min={catalog[fault][name][0]} max={catalog[fault][name][1]} placeholder={String(PARAM_DEFAULTS[name])} value={values[name] ?? ""}
                onChange={(e) => setValues({ ...values, [name]: e.target.value })} className="w-40 rounded border border-slate-700 bg-slate-950 px-2 py-1.5" />
            </label>
          ))}
          <button disabled={busy || !state.enabled} className="rounded bg-red-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-red-500 disabled:opacity-50">Inject fault</button>
        </form>

        <section className="rounded-lg border border-slate-800 bg-slate-900 p-4">
          <h2 className="mb-2 text-sm font-semibold uppercase tracking-wider text-slate-400">Active faults ({state.active.length})</h2>
          {state.active.length === 0 && <p className="text-sm text-slate-500">None. The simulated network is healthy.</p>}
          <ul className="space-y-2">
            {state.active.map((d) => (
              <li key={d.id} className="flex items-center justify-between gap-2 text-sm">
                <span>{d.name}<span className="ml-2 text-xs text-red-300">{FAULT_LABELS[d.fault] ?? d.fault}{Object.keys(d.params).length ? ` ${JSON.stringify(d.params)}` : ""}</span></span>
                <button disabled={busy} onClick={() => act(() => clearFault(d.id), `Cleared the fault on ${d.name}. It should recover after a few cycles.`)} className="rounded border border-slate-600 px-2 py-0.5 text-xs hover:bg-slate-800">Clear</button>
              </li>
            ))}
          </ul>
          <button disabled={busy || state.active.length === 0} onClick={() => act(clearAllFaults, "Cleared all faults. Devices recover after a few cycles and alerts resolve by themselves.")} className="mt-3 w-full rounded bg-emerald-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-emerald-500 disabled:opacity-40">Recover everything</button>
        </section>
      </section>

      <section>
        <h2 className="mb-2 text-sm font-semibold uppercase tracking-wider text-slate-400">Demo scenarios (each clears the previous faults first)</h2>
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {state.scenarios.map((s) => <ScenarioCard key={s.id} scenario={s} busy={busy || !state.enabled} onRun={(id) => act(() => runScenario(id), `Scenario "${s.name}" started.`)} />)}
        </div>
      </section>
    </div>
  );
}
