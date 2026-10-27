import { renderToString } from "react-dom/server";
import { describe, expect, it } from "vitest";
import App from "./App.jsx";
import Badge from "./components/Badge.jsx";
import StatusBadge from "./components/StatusBadge.jsx";

describe("render smoke tests", () => {
  it("Badge labels provenance and defaults to SIMULATED", () => {
    expect(renderToString(<Badge source="real" />)).toContain("REAL");
    expect(renderToString(<Badge source="simulated" />)).toContain("SIMULATED");
    expect(renderToString(<Badge />)).toContain("SIMULATED");
  });

  it("App renders the shell and the Monitoring page in its loading state", () => {
    const html = renderToString(<App />);
    expect(html).toContain("Smart Campus Network Monitoring System");
    expect(html).toContain("Dashboard");
    expect(html).toContain("Loading");
  });

  it("StatusBadge shows the label for each state", () => {
    for (const status of ["online", "degraded", "offline", "unreachable", "unknown"]) {
      expect(renderToString(<StatusBadge status={status} />)).toContain(status.toUpperCase());
    }
  });
});
