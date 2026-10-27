import TopologyView, { TopologyLegend } from "../components/TopologyView.jsx";
import { usePolling } from "../hooks/usePolling.js";
import { getDevices, getTrafficLinks } from "../services/api.js";

export default function TopologyPage({ onSelect, selectedId }) {
  const devices = usePolling(getDevices, 2500);
  const links = usePolling(getTrafficLinks, 2500);
  return (
    <div className="space-y-2">
      <p className="text-sm text-slate-400">Live view. Click any device for its details and charts. Use the mouse wheel to zoom and drag to pan.</p>
      {devices.data ? <TopologyView devices={devices.data} links={links.data ?? []} selectedId={selectedId} onSelect={onSelect} height={680} /> : <p className="text-sm text-slate-400">Loading…</p>}
      <TopologyLegend />
    </div>
  );
}
