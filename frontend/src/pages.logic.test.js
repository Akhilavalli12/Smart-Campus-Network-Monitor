import { describe, expect, it } from "vitest";
import { alertDuration, peakText } from "./alertsUi.js";
import { RANGES, blockRows, bucketFor, formatClock, latencyRows, outageSpans, trafficRows } from "./charts.js";
import { CAMPUS, LINKS, linkFor } from "./fixtures.js";
import { buildFlow, layoutTree, linkIdFor, LINK_COLORS } from "./topologyLayout.js";
import { kpiTiles } from "./pages/Dashboard.jsx";
import { PARAM_DEFAULTS, buildFaultRequest, groupByBlock } from "./pages/Simulation.jsx";

describe("topology layout", () => {
  const pos = layoutTree(CAMPUS);

  it("places every device exactly once, one row per depth", () => {
    expect(Object.keys(pos)).toHaveLength(17);
    expect(pos.internet.y).toBe(0);
    expect(pos["edge-router"].y).toBe(130);
    expect(pos["core-switch"].y).toBe(260);
    expect(pos["cse-switch"].y).toBe(390);
    expect(pos["cse-pc-1"].y).toBe(520);
  });

  it("centres each parent over its children and never overlaps nodes on a row", () => {
    const kids = CAMPUS.filter((d) => d.parent_id === "cse-switch").map((d) => pos[d.id].x);
    expect(pos["cse-switch"].x).toBeCloseTo((Math.min(...kids) + Math.max(...kids)) / 2);
    const rows = {};
    for (const d of CAMPUS) (rows[pos[d.id].y] ??= []).push(pos[d.id].x);
    for (const xs of Object.values(rows)) expect(new Set(xs).size).toBe(xs.length);
  });

  it("keeps the three campus blocks side by side in order", () => {
    expect(pos["cse-switch"].x).toBeLessThan(pos["library-switch"].x);
    expect(pos["library-switch"].x).toBeLessThan(pos["admin-switch"].x);
  });
});

describe("flow building", () => {
  it("creates a node per device and an edge per link", () => {
    const { nodes, edges } = buildFlow(CAMPUS, LINKS, "cse-switch");
    expect(nodes).toHaveLength(17);
    expect(edges).toHaveLength(16);
    expect(nodes.find((n) => n.id === "cse-switch").selected).toBe(true);
    expect(nodes.every((n) => n.type === "device" && n.draggable === false)).toBe(true);
    expect(edges.find((e) => e.id === "core-switch--cse-switch")).toMatchObject({ source: "core-switch", target: "cse-switch", label: "20%" });
  });

  it("colours edges by link state and thickens them with utilization", () => {
    const sw = CAMPUS.find((d) => d.id === "admin-switch");
    const cong = buildFlow(CAMPUS, [linkFor(sw, "congested", 96)]).edges.find((e) => e.id === linkIdFor(sw));
    const idle = buildFlow(CAMPUS, [linkFor(sw, "up", 5)]).edges.find((e) => e.id === linkIdFor(sw));
    const down = buildFlow(CAMPUS, [linkFor(sw, "down", 0)]).edges.find((e) => e.id === linkIdFor(sw));
    expect(cong.style.stroke).toBe(LINK_COLORS.congested);
    expect(cong.animated).toBe(true);
    expect(cong.style.strokeWidth).toBeGreaterThan(idle.style.strokeWidth);
    expect(down.style.strokeDasharray).toBeTruthy();
    expect(idle.animated).toBe(false);
  });

  it("copes with missing link data", () => {
    const { edges } = buildFlow(CAMPUS, []);
    expect(edges).toHaveLength(16);
    expect(edges[0].label).toBeUndefined();
    expect(edges[0].style.stroke).toBe(LINK_COLORS.unknown);
  });
});

describe("chart helpers", () => {
  it("chooses buckets so a chart stays under about 240 points", () => {
    expect(bucketFor(1)).toBe(15);
    expect(bucketFor(24)).toBe(360);
    expect(bucketFor(0.01)).toBeGreaterThanOrEqual(1);
    expect(RANGES.map((r) => r.hours)).toEqual([1, 6, 24]);
  });

  it("converts API points to chart rows and keeps gaps as null", () => {
    const rows = latencyRows([{ ts: "2026-01-01T00:00:00Z", rtt_avg_ms: 8.123, rtt_max_ms: 9, loss_pct: 0, jitter_ms: 1, status: "online" }, { ts: "2026-01-01T00:01:00Z", rtt_avg_ms: null, rtt_max_ms: null, loss_pct: 100, jitter_ms: null, status: "offline" }]);
    expect(rows[0]).toMatchObject({ avg: 8.12, max: 9, loss: 0 });
    expect(rows[1]).toMatchObject({ avg: null, loss: 100, status: "offline" });
    expect(rows[1].t - rows[0].t).toBe(60000);
    expect(trafficRows([{ ts: "2026-01-01T00:00:00Z", rx_mbps: 12.345, tx_mbps: 1, util_pct: 12.34 }])[0]).toMatchObject({ down: 12.35, up: 1, util: 12.3 });
    expect(blockRows([{ ts: "2026-01-01T00:00:00Z", blocks: { cse: { total_mbps: 40 }, admin: { total_mbps: 9 } } }])[0]).toMatchObject({ cse: 40, library: null, admin: 9 });
  });

  it("finds outage spans, including one that is still going on", () => {
    const rows = [{ t: 1, status: "online" }, { t: 2, status: "offline" }, { t: 3, status: "unreachable" }, { t: 4, status: "online" }, { t: 5, status: "offline" }];
    expect(outageSpans(rows)).toEqual([{ from: 2, to: 3 }, { from: 5, to: 5 }]);
    expect(outageSpans([])).toEqual([]);
  });

  it("formats clock labels", () => {
    expect(formatClock(new Date(2026, 0, 2, 9, 5).getTime())).toBe("09:05");
    expect(formatClock(new Date(2026, 0, 2, 9, 5).getTime(), 48)).toBe("1/2 09:05");
  });
});

describe("alert helpers", () => {
  const alert = { type: "DEVICE_OFFLINE", opened_at: "2026-01-01T10:00:00Z", resolved_at: "2026-01-01T10:12:30Z", metrics: { peak: 100 } };
  it("computes duration for resolved and open alerts", () => {
    expect(alertDuration(alert)).toBe("12m 30s");
    expect(alertDuration({ ...alert, resolved_at: null }, new Date("2026-01-01T10:00:45Z"))).toBe("45s");
  });
  it("describes the peak with its unit", () => {
    expect(peakText(alert)).toBe("100 % loss");
    expect(peakText({ type: "HIGH_LATENCY", metrics: { peak: 226.54 } })).toBe("227 ms");
    expect(peakText({ type: "HIGH_UTILIZATION", metrics: {} })).toBe("-");
  });
});

describe("dashboard KPIs", () => {
  const summary = {
    devices: { total: 17, online: 11, degraded: 0, offline: 1, unreachable: 5, unknown: 0, real: 1, simulated: 16 },
    active_alerts: 1, critical_alerts: 1, warning_alerts: 0, avg_latency_ms: 9.4, avg_packet_loss_pct: 32.1, avg_utilization_pct: 12, utilization_state: "up",
    busiest_link_name: "Edge Router to Core L3 Switch", busiest_link_util_pct: 40,
  };
  it("produces the eight tiles the spec asks for, with honest sub-text", () => {
    const tiles = kpiTiles(summary);
    expect(tiles.map((t) => t.label)).toEqual(["Total devices", "Online", "Degraded", "Offline", "Active alerts", "Avg latency", "Avg packet loss", "Network utilization"]);
    expect(tiles[0].sub).toBe("16 simulated · 1 real");
    expect(tiles[3]).toMatchObject({ value: 1, tone: "bad", sub: "+ 5 unreachable behind it" });
    expect(tiles[4]).toMatchObject({ value: 1, tone: "bad", sub: "1 critical · 0 warning" });
    expect(tiles[6].tone).toBe("warn");
  });
  it("shows a calm healthy state", () => {
    const tiles = kpiTiles({ ...summary, devices: { ...summary.devices, online: 17, offline: 0, unreachable: 0 }, active_alerts: 0, critical_alerts: 0, avg_packet_loss_pct: 0 });
    expect(tiles[4]).toMatchObject({ tone: "good", sub: "all clear" });
    expect(tiles[3].tone).toBe("muted");
  });
});

describe("simulation form logic", () => {
  const catalog = { offline: {}, high_latency: { rtt_ms: [1, 10000] }, packet_loss: { loss_pct: [0, 100] }, congestion: { utilization_pct: [0, 100] } };
  it("builds the request with only the parameters the fault takes", () => {
    expect(buildFaultRequest("cse-switch", "offline", { rtt_ms: "5" }, catalog)).toEqual({ device_id: "cse-switch", fault: "offline", params: {} });
    expect(buildFaultRequest("cse-ap", "high_latency", { rtt_ms: "250" }, catalog)).toEqual({ device_id: "cse-ap", fault: "high_latency", params: { rtt_ms: 250 } });
  });
  it("falls back to the defaults when a field is left empty", () => {
    expect(buildFaultRequest("x", "packet_loss", {}, catalog).params).toEqual({ loss_pct: PARAM_DEFAULTS.loss_pct });
    expect(buildFaultRequest("x", "congestion", { utilization_pct: "" }, catalog).params).toEqual({ utilization_pct: 95 });
  });
  it("groups devices by campus block", () => {
    const groups = groupByBlock(CAMPUS.filter((d) => d.monitoring_mode === "simulated"));
    expect(Object.keys(groups).sort()).toEqual(["admin", "backbone", "cse", "library"]);
    expect(groups.cse).toHaveLength(6);
  });
});
