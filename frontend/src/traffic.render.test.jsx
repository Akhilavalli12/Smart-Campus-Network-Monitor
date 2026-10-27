import { renderToString } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { BlockCard, EngineBar, HostCard, LinkCard, LinkTable, ProtocolCard } from "./pages/Traffic.jsx";

const block = { block: "cse", name: "CSE Block", rx_mbps: 19.2, tx_mbps: 14.3, total_mbps: 33.5, capacity_mbps: 100, util_pct: 19.2, source: "simulated", state: "up" };
const link = { id: "a--b", a_name: "Core L3 Switch", b_name: "CSE Switch", kind: "uplink", capacity_mbps: 100, state: "congested", rx_mbps: 95, tx_mbps: 38, rx_pps: 13000, tx_pps: 5000, util_pct: 95, source: "simulated", ts: new Date().toISOString() };

describe("traffic page parts", () => {
  it("BlockCard shows total, direction split, utilization and the SIMULATED badge", () => {
    const html = renderToString(<BlockCard block={block} />);
    for (const text of ["CSE Block", "33.5 Mbps", "19.2 Mbps", "14.3 Mbps", "SIMULATED", "NORMAL", "19%"]) expect(html).toContain(text);
  });

  it("LinkCard flags a congested link", () => {
    const html = renderToString(<LinkCard title="WAN" link={link} />);
    expect(html).toContain("CONGESTED");
    expect(html).toContain("Core L3 Switch");
    expect(renderToString(<LinkCard title="x" link={null} />)).toBe("");
  });

  it("HostCard is labelled REAL and explains missing speed or missing data", () => {
    const host = { rx_mbps: 1.2, tx_mbps: 0.3, total_mbps: 1.5, rx_pps: 900, tx_pps: 300, label: "eth0", capacity_mbps: null, util_pct: null };
    const html = renderToString(<HostCard host={host} status={null} />);
    expect(html).toContain("REAL");
    expect(html).toContain("link speed unknown");
    expect(renderToString(<HostCard host={null} status={{ host_error: "interface 'x' not found" }} />)).toContain("not found");
  });

  it("ProtocolCard lists every protocol, is labelled SIMULATED and carries the honesty note", () => {
    const data = {
      total_bytes: 2_000_000, window_minutes: 5, note: "No packets are captured or inspected.",
      protocols: [["tcp", 70], ["udp", 17], ["dns", 5], ["icmp", 1], ["other", 7]].map(([name, pct]) => ({ name, pct, bytes: pct * 1000 })),
    };
    const html = renderToString(<ProtocolCard data={data} />);
    for (const text of ["TCP", "UDP", "DNS", "ICMP", "Other", "SIMULATED", "No packets are captured"]) expect(html).toContain(text);
    expect(renderToString(<ProtocolCard data={{ total_bytes: 0, protocols: [] }} />)).toContain("Collecting");
  });

  it("LinkTable shows a row per link with state and source", () => {
    const html = renderToString(<LinkTable links={[link, { ...link, id: "c--d", state: "unknown", rx_mbps: null, tx_mbps: null, util_pct: null, source: null }]} />);
    expect(html).toContain("CONGESTED");
    expect(html).toContain("NO DATA");
    expect(html.match(/<tr/g)).toHaveLength(3);
  });

  it("EngineBar covers running, disabled and unreachable backend", () => {
    const running = { enabled: true, running: true, cycles_completed: 9, interval_s: 5, last_cycle_at: new Date().toISOString(), counter_bits: 32 };
    const html = renderToString(<EngineBar status={running} error={null} />).replace(/<!-- -->/g, "");
    expect(html).toContain("32-bit");
    expect(renderToString(<EngineBar status={{ enabled: false }} error={null} />)).toContain("disabled");
    expect(renderToString(<EngineBar status={null} error="HTTP 500" />)).toContain("Cannot reach the backend");
  });
});
