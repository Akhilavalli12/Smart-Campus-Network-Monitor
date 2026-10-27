import { Area, AreaChart, CartesianGrid, Legend, Line, LineChart, ReferenceArea, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { formatClock } from "../charts.js";

const GRID = "#1e293b";
const AXIS = "#64748b";

/**
 * Generic time-series chart.
 *   series: [{ key, label, color }]   data rows: { t: epoch ms, [key]: number | null }
 *   area / stacked draw filled areas; spans shade outage periods.
 */
export default function TimeChart({ data, series, unit = "", height = 180, area = false, stacked = false, yMax, hours = 1, spans = [], empty = "No history yet" }) {
  if (!data || data.length === 0) {
    return <div className="flex items-center justify-center text-sm text-slate-500" style={{ height }}>{empty}</div>;
  }
  const Chart = area ? AreaChart : LineChart;
  const tooltipFormatter = (value) => (value === null || value === undefined ? "-" : `${value}${unit ? ` ${unit}` : ""}`);
  return (
    <div style={{ height }} role="img" aria-label="time series chart">
      <ResponsiveContainer width="100%" height="100%">
        <Chart data={data} margin={{ top: 6, right: 12, bottom: 0, left: 0 }}>
          <CartesianGrid stroke={GRID} strokeDasharray="3 3" />
          <XAxis dataKey="t" type="number" scale="time" domain={["dataMin", "dataMax"]} tickFormatter={(ms) => formatClock(ms, hours)} stroke={AXIS} fontSize={11} minTickGap={40} />
          <YAxis stroke={AXIS} fontSize={11} width={42} domain={[0, yMax ?? "auto"]} allowDataOverflow={yMax !== undefined} />
          <Tooltip
            labelFormatter={(ms) => new Date(ms).toLocaleString()}
            formatter={tooltipFormatter}
            contentStyle={{ background: "#0f172a", border: "1px solid #334155", borderRadius: 6, fontSize: 12 }}
          />
          {series.length > 1 && <Legend wrapperStyle={{ fontSize: 11 }} />}
          {spans.map((s) => <ReferenceArea key={`${s.from}-${s.to}`} x1={s.from} x2={s.to} fill="#ef4444" fillOpacity={0.15} />)}
          {series.map((s) =>
            area ? (
              <Area key={s.key} type="monotone" dataKey={s.key} name={s.label} stroke={s.color} fill={s.color} fillOpacity={0.3} strokeWidth={1.5} stackId={stacked ? "stack" : undefined} isAnimationActive={false} dot={false} connectNulls={false} />
            ) : (
              <Line key={s.key} type="monotone" dataKey={s.key} name={s.label} stroke={s.color} strokeWidth={1.8} dot={false} isAnimationActive={false} connectNulls={false} />
            ),
          )}
        </Chart>
      </ResponsiveContainer>
    </div>
  );
}
