const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000").replace(/\/$/, "");

/** Pull a readable message out of a FastAPI error body ({"detail": string | [{msg}]}). */
export function extractDetail(body) {
  const detail = body?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail) && detail.length > 0) {
    return detail.map((item) => item.msg ?? String(item)).join("; ");
  }
  return null;
}

/** Thin wrapper around fetch: JSON in/out, throws Error with a readable message on failure. */
export async function apiGet(path, { signal } = {}) {
  const response = await fetch(`${API_BASE_URL}${path}`, { signal });
  if (!response.ok) {
    let detail = null;
    try {
      detail = extractDetail(await response.json());
    } catch {
      /* body was not JSON */
    }
    throw new Error(`${path} failed (HTTP ${response.status})${detail ? `: ${detail}` : ""}`);
  }
  return response.json();
}

export const getHealth = (options) => apiGet("/api/health", options);
export const getSubnets = (options) => apiGet("/api/subnets", options);
export const getDevices = (options) => apiGet("/api/devices", options);
export const calculateSubnet = (cidr, options) =>
  apiGet(`/api/subnets/calculate?cidr=${encodeURIComponent(cidr)}`, options);
export const getMonitoringStatus = (options) => apiGet("/api/monitoring/status", options);
export const getEvents = (limit = 15, options) => apiGet(`/api/events?limit=${limit}`, options);
export const getTrafficStatus = (options) => apiGet("/api/traffic/status", options);
export const getTrafficSummary = (options) => apiGet("/api/traffic/summary", options);
export const getTrafficLinks = (options) => apiGet("/api/traffic/links", options);
export const getProtocols = (minutes = 5, options) => apiGet(`/api/traffic/protocols?minutes=${minutes}`, options);

/** POST/DELETE/PUT with an optional JSON body; throws with the server's validation message on failure. */
export async function apiSend(method, path, body) {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method,
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) {
    let detail = null;
    try {
      detail = extractDetail(await response.json());
    } catch {
      /* body was not JSON */
    }
    throw new Error(detail ?? `${method} ${path} failed (HTTP ${response.status})`);
  }
  return response.status === 204 ? null : response.json();
}

export const getDashboard = (options) => apiGet("/api/dashboard/summary", options);
export const getDevice = (id, options) => apiGet(`/api/devices/${encodeURIComponent(id)}`, options);
export const getAlerts = (state, limit = 100, options) => apiGet(`/api/alerts?limit=${limit}${state ? `&state=${state}` : ""}`, options);
export const getAlertSummary = (options) => apiGet("/api/alerts/summary", options);
export const acknowledgeAlert = (id) => apiSend("POST", `/api/alerts/${id}/acknowledge`);
export const getSimulationState = (options) => apiGet("/api/simulation/state", options);
export const injectFault = (body) => apiSend("POST", "/api/simulation/faults", body);
export const clearFault = (deviceId) => apiSend("DELETE", `/api/simulation/faults/${encodeURIComponent(deviceId)}`);
export const clearAllFaults = () => apiSend("DELETE", "/api/simulation/faults");
export const runScenario = (id) => apiSend("POST", `/api/simulation/scenarios/${id}/run`);
export const getDeviceHistory = (id, hours, bucketS, options) => apiGet(`/api/devices/${encodeURIComponent(id)}/history?hours=${hours}&bucket_s=${bucketS}`, options);
export const getLinkHistory = (linkId, hours, bucketS, options) => apiGet(`/api/traffic/links/${encodeURIComponent(linkId)}/history?hours=${hours}&bucket_s=${bucketS}`, options);
export const getBlocksHistory = (hours, bucketS, options) => apiGet(`/api/traffic/blocks/history?hours=${hours}&bucket_s=${bucketS}`, options);
