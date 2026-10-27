const STYLES = {
  real: "border-emerald-500/40 bg-emerald-500/10 text-emerald-300",
  simulated: "border-sky-500/40 bg-sky-500/10 text-sky-300",
};

/**
 * Data-provenance badge: every metric in the UI states whether it was
 * measured on a real network (REAL) or produced by the simulator (SIMULATED).
 */
export default function Badge({ source }) {
  const key = source === "real" ? "real" : "simulated";
  return (
    <span className={`inline-block rounded border px-1.5 py-0.5 text-[10px] font-semibold tracking-wider ${STYLES[key]}`}>
      {key.toUpperCase()}
    </span>
  );
}
