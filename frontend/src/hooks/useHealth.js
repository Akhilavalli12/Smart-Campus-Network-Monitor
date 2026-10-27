import { useEffect, useState } from "react";
import { getHealth } from "../services/api.js";

/**
 * Polls GET /api/health.
 * state: "loading" (first request), "connected" (API answered), "unreachable" (request failed).
 * "connected" only means the API answered; check data.status for database health.
 */
export function useHealth(intervalMs = 5000) {
  const [state, setState] = useState("loading");
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    const controller = new AbortController();

    async function poll() {
      try {
        const health = await getHealth({ signal: controller.signal });
        setData(health);
        setError(null);
        setState("connected");
      } catch (err) {
        if (err.name === "AbortError") return;
        setError(err.message);
        setState("unreachable");
      }
    }

    poll();
    const timer = setInterval(poll, intervalMs);
    return () => {
      controller.abort();
      clearInterval(timer);
    };
  }, [intervalMs]);

  return { state, data, error };
}
