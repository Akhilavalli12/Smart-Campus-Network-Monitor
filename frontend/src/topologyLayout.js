/** Pure helpers that turn devices + links into React Flow nodes and edges. */
import { statusHex } from "./status.js";

export const TYPE_ICONS = { internet: "🌐", edge_router: "📡", core_switch: "🔀", switch: "🔌", access_point: "📶", server: "🗄️", pc: "💻" };
export const TYPE_LABELS = { internet: "Internet", edge_router: "Edge router", core_switch: "Core L3 switch", switch: "L2 switch", access_point: "Access point", server: "Server", pc: "PC" };

export const LINK_COLORS = { up: "#475569", busy: "#f59e0b", congested: "#ef4444", down: "#ef4444", unknown: "#334155" };

/**
 * Tree layout: leaves are spread left to right, every parent is centred over its children,
 * depth sets the row. Deterministic (children keep the order of `devices`).
 */
export function layoutTree(devices, { xGap = 150, yGap = 130 } = {}) {
  const children = {};
  for (const d of devices) {
    if (d.parent_id) (children[d.parent_id] ??= []).push(d.id);
  }
  const positions = {};
  let nextLeaf = 0;
  function place(id, depth) {
    const kids = children[id] ?? [];
    let x;
    if (kids.length === 0) {
      x = nextLeaf * xGap;
      nextLeaf += 1;
    } else {
      const xs = kids.map((kid) => place(kid, depth + 1));
      x = (xs[0] + xs[xs.length - 1]) / 2;
    }
    positions[id] = { x, y: depth * yGap };
    return x;
  }
  for (const root of devices.filter((d) => !d.parent_id)) place(root.id, 0);
  return positions;
}

export function linkIdFor(device) {
  return device.parent_id ? `${device.parent_id}--${device.id}` : null;
}

/** Nodes and edges for React Flow. `links` come from /api/traffic/links (they carry utilization and state). */
export function buildFlow(devices, links = [], selectedId = null) {
  const positions = layoutTree(devices);
  const nodes = devices.map((device) => ({
    id: device.id,
    type: "device",
    position: positions[device.id] ?? { x: 0, y: 0 },
    data: { device },
    selected: device.id === selectedId,
    draggable: false,
  }));
  const linkById = Object.fromEntries(links.map((l) => [l.id, l]));
  const edges = devices
    .filter((d) => d.parent_id)
    .map((device) => {
      const link = linkById[linkIdFor(device)];
      const state = link?.state ?? "unknown";
      const util = link?.util_pct;
      return {
        id: linkIdFor(device),
        source: device.parent_id,
        target: device.id,
        label: util === null || util === undefined ? undefined : `${util.toFixed(0)}%`,
        animated: state === "congested",
        style: {
          stroke: LINK_COLORS[state] ?? LINK_COLORS.unknown,
          strokeWidth: 1.5 + Math.min(100, Math.max(0, util ?? 0)) / 100 * 3,
          strokeDasharray: state === "down" ? "6 4" : undefined,
        },
        labelStyle: { fill: "#cbd5e1", fontSize: 11 },
        labelBgStyle: { fill: "#0f172a" },
        data: { link },
      };
    });
  return { nodes, edges };
}

export const nodeBorder = (status) => statusHex(status);
