/** The 17-device campus as the API returns it (used by tests). */
const base = { monitoring_error: null, consecutive_failures: 0, caused_by: null, last_seen: "2026-01-01T00:00:00Z", up_since: "2026-01-01T00:00:00Z", status: "online", monitoring_mode: "simulated", latest: null, subnet_id: "x", block: "cse", location: "", mac: "02:00:00:00:00:01" };
const d = (id, name, type, ip, parent, extra = {}) => ({ ...base, id, name, type, ip, parent_id: parent, ...extra });

export const CAMPUS = [
  d("internet", "Internet (ISP)", "internet", "1.1.1.1", null, { monitoring_mode: "real", block: "backbone" }),
  d("edge-router", "Edge Router", "edge_router", "10.0.0.1", "internet", { block: "backbone" }),
  d("core-switch", "Core L3 Switch", "core_switch", "10.0.0.2", "edge-router", { block: "backbone" }),
  d("cse-switch", "CSE Switch", "switch", "192.168.10.2", "core-switch"),
  d("cse-ap", "CSE Access Point", "access_point", "192.168.10.3", "cse-switch"),
  d("cse-server", "CSE Lab Server", "server", "192.168.10.10", "cse-switch"),
  d("cse-pc-1", "CSE PC 1", "pc", "192.168.10.101", "cse-switch"),
  d("cse-pc-2", "CSE PC 2", "pc", "192.168.10.102", "cse-switch"),
  d("cse-pc-3", "CSE PC 3", "pc", "192.168.10.103", "cse-switch"),
  d("library-switch", "Library Switch", "switch", "192.168.20.2", "core-switch", { block: "library" }),
  d("library-ap", "Library Access Point", "access_point", "192.168.20.3", "library-switch", { block: "library" }),
  d("library-pc-1", "Library PC 1", "pc", "192.168.20.101", "library-switch", { block: "library" }),
  d("library-pc-2", "Library PC 2", "pc", "192.168.20.102", "library-switch", { block: "library" }),
  d("admin-switch", "Admin Switch", "switch", "192.168.30.2", "core-switch", { block: "admin" }),
  d("admin-ap", "Admin Access Point", "access_point", "192.168.30.3", "admin-switch", { block: "admin" }),
  d("admin-pc-1", "Admin PC 1", "pc", "192.168.30.101", "admin-switch", { block: "admin" }),
  d("admin-pc-2", "Admin PC 2", "pc", "192.168.30.102", "admin-switch", { block: "admin" }),
];

export const linkFor = (device, state = "up", util = 20) => ({ id: `${device.parent_id}--${device.id}`, a_id: device.parent_id, b_id: device.id, state, util_pct: util, capacity_mbps: 100 });
export const LINKS = CAMPUS.filter((x) => x.parent_id).map((x) => linkFor(x));
