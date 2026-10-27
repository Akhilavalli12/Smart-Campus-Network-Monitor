const TONES = { neutral: "text-slate-100", good: "text-emerald-300", warn: "text-amber-300", bad: "text-red-400", muted: "text-slate-400" };

export default function KpiCard({ label, value, sub, tone = "neutral", badge }) {
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900 px-3 py-2">
      <div className="flex items-center justify-between text-[11px] font-semibold uppercase tracking-wider text-slate-400">
        <span>{label}</span>
        {badge}
      </div>
      <div className={`text-2xl font-semibold ${TONES[tone] ?? TONES.neutral}`}>{value}</div>
      <div className="min-h-4 truncate text-xs text-slate-500">{sub}</div>
    </div>
  );
}
