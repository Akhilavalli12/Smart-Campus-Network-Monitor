export default function Row({ label, children }) {
  return (
    <div className="flex items-center justify-between border-b border-slate-800 py-2 text-sm last:border-0">
      <span className="text-slate-400">{label}</span>
      <span className="font-mono text-slate-100">{children}</span>
    </div>
  );
}
