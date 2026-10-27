import { useState } from "react";
import DeviceDrawer from "./components/DeviceDrawer.jsx";
import { usePolling } from "./hooks/usePolling.js";
import Alerts from "./pages/Alerts.jsx";
import ConnectionCheck from "./pages/ConnectionCheck.jsx";
import Dashboard from "./pages/Dashboard.jsx";
import Inventory from "./pages/Inventory.jsx";
import Monitoring from "./pages/Monitoring.jsx";
import Simulation from "./pages/Simulation.jsx";
import Topology from "./pages/TopologyPage.jsx";
import Traffic from "./pages/Traffic.jsx";
import { getAlertSummary } from "./services/api.js";

const TABS = [
  { id: "dashboard", label: "Dashboard", component: Dashboard },
  { id: "topology", label: "Topology", component: Topology },
  { id: "alerts", label: "Alerts", component: Alerts },
  { id: "traffic", label: "Traffic", component: Traffic },
  { id: "devices", label: "Devices", component: Monitoring },
  { id: "simulation", label: "Simulation", component: Simulation },
  { id: "inventory", label: "Inventory", component: Inventory },
  { id: "connection", label: "Connection", component: ConnectionCheck },
];

export default function App() {
  const [active, setActive] = useState("dashboard");
  const [selected, setSelected] = useState(null);
  const alertSummary = usePolling(getAlertSummary, 4000);
  const Page = TABS.find((t) => t.id === active).component;
  const activeAlerts = alertSummary.data?.active ?? 0;

  return (
    <div className="mx-auto max-w-[1600px] px-4 py-4">
      <header className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Smart Campus Network Monitoring System</h1>
          <p className="text-xs text-slate-400">Mini Network Operations Center · REAL = measured on a real network · SIMULATED = educational model</p>
        </div>
        <nav className="flex flex-wrap gap-1 rounded-lg bg-slate-900 p-1" aria-label="Pages">
          {TABS.map((t) => (
            <button key={t.id} onClick={() => setActive(t.id)} className={`flex items-center gap-1.5 rounded px-3 py-1 text-sm ${active === t.id ? "bg-slate-700 text-white" : "text-slate-400 hover:text-white"}`}>
              {t.label}
              {t.id === "alerts" && activeAlerts > 0 && <span className="rounded-full bg-red-600 px-1.5 text-[10px] font-bold text-white">{activeAlerts}</span>}
            </button>
          ))}
        </nav>
      </header>
      <Page onSelect={setSelected} selectedId={selected} />
      {selected && <DeviceDrawer deviceId={selected} onClose={() => setSelected(null)} />}
    </div>
  );
}
