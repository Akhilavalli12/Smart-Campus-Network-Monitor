const COLORS = {
  green: "bg-emerald-400",
  amber: "bg-amber-400",
  red: "bg-red-500",
  grey: "bg-slate-500",
};

export default function StatusDot({ color = "grey" }) {
  return <span className={`inline-block h-2.5 w-2.5 rounded-full ${COLORS[color]}`} aria-hidden="true" />;
}
