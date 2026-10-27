import { renderToString } from "react-dom/server";
import { describe, expect, it } from "vitest";
import AlertFeed from "./components/AlertFeed.jsx";
import { DeviceInfo } from "./components/DeviceDrawer.jsx";
import KpiCard from "./components/KpiCard.jsx";
import { TopologyLegend } from "./components/TopologyView.jsx";
import { AlertTable } from "./pages/Alerts.jsx";
import { KpiStrip } from "./pages/Dashboard.jsx";
import { ScenarioCard } from "./pages/Simulation.jsx";
import { CAMPUS } from "./fixtures.js";

const alert = (over = {}) => ({
  id: "a1", type: "DEVICE_OFFLINE", severity: "critical", state: "open", device_id: "cse-switch", acknowledged: false, affected_device_ids: ["cse-ap", "cse-pc-1"],
  message: "CSE Switch is unreachable. Packet loss: 100%. Last response: 14:32:08.", opened_at: "2026-01-01T10:00:00Z", resolved_at: null, metrics: { peak: 100 }, ...over,
});

describe("alerts UI", () => {
  it("AlertTable shows the spec's example alert, the root-cause note and an acknowledge button", () => {
    const html = renderToString(<AlertTable alerts={[alert()]} onAcknowledge={() => {}} now={new Date("2026-01-01T10:05:00Z")} />).replace(/<!-- -->/g, "");
    for (const text of ["CSE Switch is unreachable", "Packet loss: 100%", "Root cause of 2 unreachable", "Device offline", "critical", "ACTIVE", "Acknowledge", "5m 00s"]) expect(html).toContain(text);
  });

  it("resolved and acknowledged alerts show no acknowledge button", () => {
    const html = renderToString(<AlertTable alerts={[alert({ state: "resolved", resolved_at: "2026-01-01T10:12:00Z", acknowledged: true })]} onAcknowledge={() => {}} />);
    expect(html).toContain("resolved");
    expect(html).not.toContain(">Acknowledge<");
  });

  it("empty states are friendly", () => {
    expect(renderToString(<AlertTable alerts={[]} />)).toContain("No alerts in this view");
    expect(renderToString(<AlertFeed alerts={[]} />)).toContain("The network is healthy");
  });

  it("AlertFeed lists warnings and criticals", () => {
    const html = renderToString(<AlertFeed alerts={[alert(), alert({ id: "a2", type: "HIGH_LATENCY", severity: "warning", message: "Library Access Point latency is 120 ms" })]} />);
    expect(html).toContain("High latency");
    expect(html).toContain("warning");
  });
});

describe("dashboard parts", () => {
  const summary = {
    devices: { total: 17, online: 17, degraded: 0, offline: 0, unreachable: 0, unknown: 0, real: 1, simulated: 16 }, active_alerts: 0, critical_alerts: 0, warning_alerts: 0,
    avg_latency_ms: 9.2, avg_packet_loss_pct: 0.1, avg_utilization_pct: 14, utilization_state: "up", busiest_link_name: "Edge Router to Core L3 Switch", busiest_link_util_pct: 31,
  };
  it("KpiStrip renders all eight KPIs with SIMULATED badges on the measured ones", () => {
    const html = renderToString(<KpiStrip summary={summary} />);
    for (const text of ["Total devices", "Online", "Degraded", "Offline", "Active alerts", "Avg latency", "Avg packet loss", "Network utilization", "9.20 ms", "all clear"]) expect(html).toContain(text);
    expect(html.match(/SIMULATED/g)).toHaveLength(3);
  });
  it("KpiCard renders value and sub text", () => {
    expect(renderToString(<KpiCard label="Online" value={17} sub="all good" tone="good" />)).toContain("all good");
  });
  it("legend explains the colours", () => {
    const html = renderToString(<TopologyLegend />);
    for (const text of ["Online", "Degraded", "Offline", "Unreachable", "utilization"]) expect(html).toContain(text);
  });
});

describe("device details and simulation cards", () => {
  it("DeviceInfo shows every field the spec lists", () => {
    const device = { ...CAMPUS[3], latest: { source: "simulated", rtt_avg_ms: 8.4, rtt_min_ms: 7.1, rtt_max_ms: 9.9, jitter_ms: 0.8, loss_pct: 0, window_loss_pct: 0.5, sent: 5, received: 5 } };
    const html = renderToString(<DeviceInfo device={device} parentName="core-switch" now={new Date("2026-01-01T01:02:00Z")} />);
    for (const text of ["192.168.10.2", "L2 switch", "SIMULATED", "8.40 ms", "7.10 ms", "9.90 ms", "5 sent / 5 received", "1h 02m", "core-switch"]) expect(html.replace(/<!-- -->/g, "")).toContain(text);
  });
  it("DeviceInfo names the root cause for an unreachable device", () => {
    const html = renderToString(<DeviceInfo device={{ ...CAMPUS[6], status: "unreachable", caused_by: "cse-switch", up_since: null }} />);
    expect(html).toContain("Cut off by (root cause)");
    expect(html).toContain("cse-switch");
  });
  it("ScenarioCard shows what to expect", () => {
    const html = renderToString(<ScenarioCard scenario={{ id: "switch-failure", name: "CSE switch fails", description: "The CSE block switch goes down.", expect: "ONE critical alert." }} onRun={() => {}} />);
    expect(html).toContain("CSE switch fails");
    expect(html).toContain("Expect:");
    expect(html).toContain("Run scenario");
  });
});
