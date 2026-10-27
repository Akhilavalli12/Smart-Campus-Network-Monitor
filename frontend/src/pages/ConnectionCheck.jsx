import Row from "../components/Row.jsx";
import StatusDot from "../components/StatusDot.jsx";
import { useHealth } from "../hooks/useHealth.js";

function summarize(state, data) {
  if (state === "loading") return { color: "grey", text: "Checking backend…" };
  if (state === "unreachable") return { color: "red", text: "Backend unreachable" };
  if (data.status === "ok") return { color: "green", text: "Backend and database online" };
  return { color: "amber", text: "Backend online, database unreachable" };
}

export default function ConnectionCheck() {
  const { state, data, error } = useHealth();
  const summary = summarize(state, data);

  return (
    <main className="mx-auto max-w-xl">

      <section className="rounded-lg border border-slate-800 bg-slate-900 p-5">
        <div className="mb-3 flex items-center gap-2 font-medium">
          <StatusDot color={summary.color} />
          {summary.text}
        </div>

        {state === "unreachable" && (
          <p className="text-sm text-red-300">
            {error}. Is the backend running at the URL in <code>VITE_API_BASE_URL</code>?
          </p>
        )}

        {data && (
          <div>
            <Row label="Service">{data.service}</Row>
            <Row label="Version">{data.version}</Row>
            <Row label="Environment">{data.environment}</Row>
            <Row label="API uptime">{data.uptime_seconds} s</Row>
            <Row label="MongoDB">{data.database.status}</Row>
            {data.database.latency_ms != null && <Row label="MongoDB ping">{data.database.latency_ms} ms</Row>}
            {data.database.error && <Row label="MongoDB error">{data.database.error}</Row>}
          </div>
        )}
      </section>
      <p className="mt-3 text-xs text-slate-500">Refreshes every 5 seconds.</p>
    </main>
  );
}
