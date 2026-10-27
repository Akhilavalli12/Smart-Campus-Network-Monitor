import { useCallback, useEffect, useRef, useState } from "react";

/**
 * Call `loader({ signal })` now and then every `intervalMs`.
 * Keeps showing the last good data while a refresh fails, and reports the failure,
 * so a brief backend hiccup does not blank the dashboard.
 * `deps` restarts polling (and refetches at once) when they change, for example a chosen time range.
 * state: "loading" (nothing yet) | "ready" | "error" (last refresh failed). `refresh()` fetches immediately.
 */
export function usePolling(loader, intervalMs = 3000, deps = []) {
  const [state, setState] = useState("loading");
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const loaderRef = useRef(loader);
  loaderRef.current = loader;
  const refreshRef = useRef(() => {});

  useEffect(() => {
    const controller = new AbortController();
    async function refresh() {
      try {
        const result = await loaderRef.current({ signal: controller.signal });
        setData(result);
        setError(null);
        setState("ready");
      } catch (err) {
        if (err.name === "AbortError") return;
        setError(err.message);
        setState("error");
      }
    }
    refreshRef.current = refresh;
    refresh();
    const timer = setInterval(refresh, intervalMs);
    return () => {
      controller.abort();
      clearInterval(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [intervalMs, ...deps]);

  const refresh = useCallback(() => refreshRef.current(), []);
  return { state, data, error, refresh };
}
