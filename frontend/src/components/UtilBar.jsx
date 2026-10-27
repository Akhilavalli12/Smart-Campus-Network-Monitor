import { barWidth, stateStyle } from "../traffic.js";

export default function UtilBar({ utilPct, state }) {
  const style = stateStyle(state);
  return (
    <div className="flex items-center gap-2">
      <div className="h-2 w-full min-w-16 overflow-hidden rounded bg-slate-800" role="progressbar" aria-valuenow={Math.round(utilPct ?? 0)} aria-valuemin={0} aria-valuemax={100}>
        <div className={`h-full ${style.bar}`} style={{ width: `${barWidth(utilPct)}%` }} />
      </div>
      <span className={`w-12 text-right font-mono text-xs ${style.text}`}>{utilPct === null || utilPct === undefined ? "-" : `${utilPct.toFixed(0)}%`}</span>
    </div>
  );
}
