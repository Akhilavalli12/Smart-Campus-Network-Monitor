import { describe, expect, it } from "vitest";
import { barWidth, formatBytes, formatMbps, formatPps, stateStyle } from "./traffic.js";

describe("traffic helpers", () => {
  it("formats rates at sensible precision", () => {
    expect(formatMbps(null)).toBe("-");
    expect(formatMbps(0)).toBe("0 Mbps");
    expect(formatMbps(0.004)).toBe("4.0 kbps");
    expect(formatMbps(0.42)).toBe("0.42 Mbps");
    expect(formatMbps(42.37)).toBe("42.4 Mbps");
    expect(formatMbps(412.6)).toBe("413 Mbps");
    expect(formatPps(950)).toBe("950 pkt/s");
    expect(formatPps(12500)).toBe("12.5k pkt/s");
    expect(formatPps(undefined)).toBe("-");
  });

  it("formats byte totals", () => {
    expect(formatBytes(999)).toBe("999 B");
    expect(formatBytes(1500)).toBe("1.5 KB");
    expect(formatBytes(2_500_000_000)).toBe("2.5 GB");
    expect(formatBytes(null)).toBe("-");
  });

  it("maps link states to styles and falls back safely", () => {
    expect(stateStyle("congested").label).toBe("CONGESTED");
    expect(stateStyle("busy").text).toContain("amber");
    expect(stateStyle("up").label).toBe("NORMAL");
    expect(stateStyle("who-knows").label).toBe("NO DATA");
  });

  it("clamps the utilization bar", () => {
    expect(barWidth(42)).toBe(42);
    expect(barWidth(140)).toBe(100);
    expect(barWidth(-5)).toBe(0);
    expect(barWidth(null)).toBe(0);
  });
});
