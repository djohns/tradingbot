import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

export default function PerformancePanel({ performance }) {
  const data = (performance?.equity_curve || [0]).map((value, index) => ({ index, value }));
  const stats = [
    ["Win rate", `${performance?.win_rate || 0}%`],
    ["PnL neto", `$${performance?.net_pnl_usd || 0}`],
    ["Costes", `$${performance?.total_costs_usd || 0}`],
    ["Drawdown máx.", `${performance?.max_drawdown_r || 0} R`],
  ];
  return (
    <section className="panel performance-panel">
      <div className="panel-heading">
        <div><p className="eyebrow">Desempeño observado</p><h2>Curva de equity</h2></div>
        <span className="muted">
          {performance?.settled_signals || 0} resueltas · muestra {performance?.sample_status || "insuficiente"}
        </span>
      </div>
      <div className="metric-grid">
        {stats.map(([label, value]) => <div key={label}><small>{label}</small><strong>{value}</strong></div>)}
      </div>
      <div className="equity-chart">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={data}>
            <defs>
              <linearGradient id="equityFill" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#43dbaf" stopOpacity={0.35} />
                <stop offset="100%" stopColor="#43dbaf" stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid stroke="#1d242c" vertical={false} />
            <XAxis dataKey="index" hide />
            <YAxis domain={["auto", "auto"]} axisLine={false} tickLine={false} width={36} />
            <Tooltip formatter={(value) => [`${value} R`, "Equity neta"]} labelFormatter={(value) => `Operación ${value}`} />
            <Area dataKey="value" stroke="#43dbaf" fill="url(#equityFill)" strokeWidth={2} />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </section>
  );
}
