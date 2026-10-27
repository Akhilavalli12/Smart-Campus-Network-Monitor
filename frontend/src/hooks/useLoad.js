import { useCallback, useEffect, useState } from "react";

/** Load data once on mount; `reload` fetches again. state: loading | ready | error. */
export function useLoad(loader) {
  const [state, setState] = useState("loading");
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  const reload = useCallback(() => {
    const controller = new AbortController();
    setState("loading");
    loader({ signal: controller.signal })
      .then((result) => {
        setData(result);
        setError(null);
        setState("ready");
      })
      .catch((err) => {
        if (err.name === "AbortError") return;
        setError(err.message);
        setState("error");
      });
    return () => controller.abort();
  }, [loader]);

  useEffect(() => reload(), [reload]);

  return { state, data, error, reload };
}
