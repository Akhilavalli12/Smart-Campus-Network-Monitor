import { Background, Controls, Handle, Position, ReactFlow } from "@xyflow/react";
import { useMemo } from "react";
import Badge from "./Badge.jsx";
import { statusLabel } from "../status.js";
import { TYPE_ICONS, TYPE_LABELS, buildFlow, nodeBorder } from "../topologyLayout.js";

function DeviceNode({ data, selected }) {
  const d = data.device;
  const border = nodeBorder(d.status);
  return (
    <div
      className={`w-32 rounded-lg bg-slate-900 px-2 py-1.5 text-center shadow ${selected ? "ring-2 ring-sky-400" : ""}`}
      style={{ border: `2px solid ${border}`, opacity: d.status === "unreachable" ? 0.7 : 1 }}
      title={`${d.name} · ${statusLabel(d.status)}`}
    >
      <Handle type="target" position={Position.Top} style={{ opacity: 0 }} />
      <div className="text-lg leading-none" aria-hidden="true">{TYPE_ICONS[d.type] ?? "▫️"}</div>
      <div className="truncate text-xs font-semibold text-slate-100">{d.name}</div>
      <div className="font-mono text-[10px] text-slate-400">{d.ip}</div>
      <div className="mt-0.5 flex items-center justify-center gap-1">
        <span className="text-[9px] font-bold tracking-wider" style={{ color: border }}>{statusLabel(d.status)}</span>
      </div>
      <div className="mt-0.5"><Badge source={d.latest?.source ?? d.monitoring_mode} /></div>
      <Handle type="source" position={Position.Bottom} style={{ opacity: 0 }} />
    </div>
  );
}

const nodeTypes = { device: DeviceNode };

/**
 * Interactive campus topology. Node colour = device status (green online, amber degraded, red offline,
 * grey unreachable because an upstream device failed). Edge colour/width/label = link utilization and state.
 */
export default function TopologyView({ devices, links, selectedId, onSelect, height = 520 }) {
  const { nodes, edges } = useMemo(() => buildFlow(devices, links, selectedId), [devices, links, selectedId]);
  return (
    <div style={{ height }} className="overflow-hidden rounded-lg border border-slate-800 bg-slate-950" data-testid="topology">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        colorMode="dark"
        fitView
        fitViewOptions={{ padding: 0.12 }}
        nodesDraggable={false}
        nodesConnectable={false}
        onNodeClick={(_, node) => onSelect?.(node.id)}
        minZoom={0.2}
      >
        <Background gap={24} color="#1e293b" />
        <Controls showInteractive={false} />
      </ReactFlow>
    </div>
  );
}

export function TopologyLegend() {
  const items = [["#22c55e", "Online"], ["#f59e0b", "Degraded"], ["#ef4444", "Offline"], ["#64748b", "Unreachable (upstream failure)"]];
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-slate-400">
      {items.map(([color, label]) => (
        <span key={label} className="inline-flex items-center gap-1.5">
          <span className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: color }} aria-hidden="true" />
          {label}
        </span>
      ))}
      <span>Link colour/width/label = utilization (amber busy, red congested, dashed = down)</span>
    </div>
  );
}

export { TYPE_LABELS };
