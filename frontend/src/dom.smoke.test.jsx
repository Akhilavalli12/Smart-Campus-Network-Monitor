// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { beforeAll, describe, expect, it } from "vitest";
import TimeChart from "./components/TimeChart.jsx";
import TopologyView from "./components/TopologyView.jsx";
import { CAMPUS, LINKS } from "./fixtures.js";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

beforeAll(() => {
  // jsdom has no layout engine: give the libraries the few browser APIs they probe.
  globalThis.ResizeObserver ??= class { observe() {} unobserve() {} disconnect() {} };
  globalThis.DOMMatrixReadOnly ??= class { constructor() { this.m22 = 1; } };
  Object.defineProperty(HTMLElement.prototype, "offsetWidth", { configurable: true, value: 800 });
  Object.defineProperty(HTMLElement.prototype, "offsetHeight", { configurable: true, value: 600 });
});

async function mount(element) {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  await act(async () => root.render(element));
  return { container, root };
}

describe("real components mount in a DOM", () => {
  it("TopologyView renders one React Flow node per device with its name, IP and status", async () => {
    const devices = CAMPUS.map((d) => (d.id === "cse-switch" ? { ...d, status: "offline" } : d));
    const { container } = await mount(<div style={{ width: 800, height: 600 }}><TopologyView devices={devices} links={LINKS} height={600} /></div>);
    const nodes = container.querySelectorAll(".react-flow__node");
    expect(nodes.length).toBe(17);
    const text = container.textContent;
    for (const t of ["Internet (ISP)", "Core L3 Switch", "CSE Switch", "192.168.10.2", "OFFLINE", "ONLINE", "REAL", "SIMULATED"]) expect(text).toContain(t);
  });

  it("TimeChart shows its empty message without data and mounts with data", async () => {
    const empty = await mount(<TimeChart data={[]} series={[{ key: "a", label: "a", color: "#fff" }]} empty="Nothing yet" />);
    expect(empty.container.textContent).toContain("Nothing yet");
    const data = Array.from({ length: 10 }, (_, i) => ({ t: 1_700_000_000_000 + i * 60000, a: i }));
    const full = await mount(<div style={{ width: 600, height: 200 }}><TimeChart data={data} series={[{ key: "a", label: "a", color: "#fff" }]} height={180} /></div>);
    expect(full.container.querySelector("[role='img']")).not.toBeNull();
  });
});
