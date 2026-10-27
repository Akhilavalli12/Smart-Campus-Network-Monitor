import { describe, expect, it } from "vitest";
import { deviceNote, formatAgo, formatDuration, formatMs, formatPct, secondsSince, statusColor, statusLabel } from "./status.js";

describe("status helpers", () => {
  it("maps each status to the colour the topology will use", () => {
    expect(statusColor("online")).toBe("green");
    expect(statusColor("degraded")).toBe("amber");
    expect(statusColor("offline")).toBe("red");
    expect(statusColor("unreachable")).toBe("grey");
    expect(statusColor("unknown")).toBe("grey");
    expect(statusColor("something-new")).toBe("grey");
    expect(statusLabel("unreachable")).toBe("UNREACHABLE");
  });

  it("formats metrics and missing values", () => {
    expect(formatMs(null)).toBe("-");
    expect(formatMs(8.123)).toBe("8.12 ms");
    expect(formatMs(180.04)).toBe("180.0 ms");
    expect(formatPct(undefined)).toBe("-");
    expect(formatPct(12)).toBe("12.0%");
  });

  it("formats durations", () => {
    expect(formatDuration(8)).toBe("8s");
    expect(formatDuration(75)).toBe("1m 15s");
    expect(formatDuration(3725)).toBe("1h 02m");
    expect(formatDuration(90000)).toBe("1d 01h");
    expect(formatDuration(null)).toBe("-");
    expect(formatDuration(-3)).toBe("-");
  });

  it("computes elapsed time and never goes negative", () => {
    const now = new Date("2026-01-01T00:01:00Z");
    expect(secondsSince("2026-01-01T00:00:00Z", now)).toBe(60);
    expect(secondsSince("2026-01-01T00:02:00Z", now)).toBe(0);
    expect(secondsSince(null, now)).toBeNull();
    expect(secondsSince("garbage", now)).toBeNull();
    expect(formatAgo("2026-01-01T00:00:50Z", now)).toBe("10s ago");
    expect(formatAgo(null, now)).toBe("never");
  });

  it("explains devices that need attention", () => {
    const names = { sw: "CSE Switch" };
    expect(deviceNote({ status: "unreachable", caused_by: "sw", consecutive_failures: 4 }, names)).toBe("cut off by CSE Switch");
    expect(deviceNote({ status: "online", consecutive_failures: 2 }, names, 3)).toBe("no reply 2/3 cycles");
    expect(deviceNote({ status: "offline", consecutive_failures: 5 }, names)).toBe("");
    expect(deviceNote({ status: "online", monitoring_error: "no permission" }, names)).toBe("monitor error: no permission");
    expect(deviceNote({ status: "online", consecutive_failures: 0 }, names)).toBe("");
  });
});
