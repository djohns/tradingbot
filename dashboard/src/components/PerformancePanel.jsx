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
  const v2 = performance?.v2 || {};
  const validation = performance?.validation_v2 || {};
  const data = (v2.equity_curve || [0]).map((value, index) => ({ index, value }));
  const stats = [
    ["Win rate V2", `${v2.win_rate || 0}%`],
    ["Expectativa", `${v2.expectancy || 0} R`],
    ["Profit factor", `${v2.profit_factor || 0}`],
    ["Drawdown V2", `${v2.max_drawdown_r || 0} R`],
  ];
  return (
    <section className="panel performance-panel">
      <div className="panel-heading">
        <div><p className="eyebrow">Desempeño aislado</p><h2>Validación V2</h2></div>
        <span className="muted">
          {v2.settled_signals || 0} resueltas · {validation.status === "validated" ? "validada" : "modo sombra"}
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
      <div className="validation-grid">
        {Object.entries(validation.gates || {}).map(([gate, passed]) => (
          <div className={passed ? "passed" : "pending"} key={gate}>
            <i />{gate.replaceAll("_", " ")}
          </div>
        ))}
      </div>
      <p className="legacy-note">
        Historial V1: {performance?.legacy?.settled_signals || 0} operaciones · {performance?.legacy?.expectancy || 0} R de expectativa. No se mezcla con la V2.
      </p>
    </section>
  );
}
