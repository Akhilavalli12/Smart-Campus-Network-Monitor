import { renderToString } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { DeviceTable, EngineBar, EventFeed, Summary } from "./pages/Monitoring.jsx";

const NOW = new Date().toISOString();
const base = { monitoring_error: null, consecutive_failures: 0, caused_by: null, last_seen: NOW, up_since: NOW };
const devices = [
  { ...base, id: "sw", name: "CSE Switch", ip: "192.168.10.2", status: "offline", monitoring_mode: "simulated", last_seen: null, up_since: null, consecutive_failures: 4,
    latest: { source: "simulated", rtt_avg_ms: null, loss_pct: 100, jitter_ms: null } },
  { ...base, id: "pc", name: "CSE PC 1", ip: "192.168.10.101", status: "unreachable", caused_by: "sw", up_since: null, monitoring_mode: "simulated",
    latest: { source: "simulated", rtt_avg_ms: null, loss_pct: 100, jitter_ms: null } },
  { ...base, id: "ap", name: "CSE Access Point", ip: "192.168.10.3", status: "degraded", monitoring_mode: "simulated",
    latest: { source: "simulated", rtt_avg_ms: 180.2, loss_pct: 0, jitter_ms: 7.5 } },
  { ...base, id: "internet", name: "Internet (ISP)", ip: "1.1.1.1", status: "online", monitoring_mode: "real",
    latest: { source: "real", rtt_avg_ms: 12.34, loss_pct: 0, jitter_ms: 0.8 } },
  { ...base, id: "new", name: "Fresh PC", ip: "192.168.10.150", status: "unknown", monitoring_mode: "simulated", last_seen: null, up_since: null, latest: null },
];

describe("monitoring page parts", () => {
  it("DeviceTable shows every status, REAL/SIMULATED badges and the root cause", () => {
    const html = renderToString(<DeviceTable devices={devices} failureConfirmations={3} />);
    for (const label of ["OFFLINE", "UNREACHABLE", "DEGRADED", "ONLINE", "UNKNOWN"]) expect(html).toContain(label);
    expect(html).toContain("REAL");
    expect(html).toContain("SIMULATED");
    expect(html).toContain("cut off by CSE Switch");
    expect(html).toContain("180.2 ms");
    expect(html).toContain("12.3 ms");
    expect(html).toContain("100.0%");
  });

  it("DeviceTable copes with a device that has never been measured", () => {
    const html = renderToString(<DeviceTable devices={[devices[4]]} failureConfirmations={3} />);
    expect(html).toContain("Fresh PC");
    expect(html).toContain("never");
  });

  it("Summary counts each state", () => {
    const html = renderToString(<Summary devices={devices} />);
    expect(html).toContain("Unreachable");
    expect(html.match(/text-2xl/g)).toHaveLength(5);
  });

  it("EventFeed lists the reason for each change", () => {
    const events = [{ id: "1", ts: NOW, device_name: "CSE Switch", from_status: "online", to_status: "offline", reason: "no reply for 3 consecutive probe cycles" }];
    const html = renderToString(<EventFeed events={events} />);
    expect(html).toContain("no reply for 3 consecutive probe cycles");
    expect(renderToString(<EventFeed events={[]} />)).toContain("No status changes yet");
  });

  it("EngineBar distinguishes running, disabled and unreachable backend", () => {
    const running = { enabled: true, running: true, cycles_completed: 12, poll_interval_s: 5, failure_confirmations: 3, detection_time_s: 15, last_cycle_at: NOW, last_cycle_duration_ms: 880, last_error: null };
    expect(renderToString(<EngineBar status={running} error={null} />)).toContain("Engine running");
    expect(renderToString(<EngineBar status={{ enabled: false }} error={null} />)).toContain("disabled");
    expect(renderToString(<EngineBar status={null} error="HTTP 500" />)).toContain("Cannot reach the backend");
    const stale = { ...running, last_cycle_at: new Date(Date.now() - 10 * 60 * 1000).toISOString() };
    expect(renderToString(<EngineBar status={stale} error={null} />)).toContain("Engine stalled");
  });
});
