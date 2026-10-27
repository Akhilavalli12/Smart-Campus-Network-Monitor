import { RANGES } from "../charts.js";

export default function RangeSelect({ hours, onChange }) {
  return (
    <div className="inline-flex gap-1 rounded bg-slate-950 p-0.5" role="group" aria-label="time range">
      {RANGES.map((r) => (
        <button key={r.hours} onClick={() => onChange(r.hours)} className={`rounded px-2 py-0.5 text-xs ${hours === r.hours ? "bg-slate-700 text-white" : "text-slate-400 hover:text-white"}`}>
          {r.label}
        </button>
      ))}
    </div>
  );
}
