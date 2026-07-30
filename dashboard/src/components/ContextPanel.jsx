export default function ContextPanel({ context }) {
  const score = context?.score || 0;
  const position = Math.max(0, Math.min(100, (score + 100) / 2));
  const fg = context?.fear_greed;
  const global = context?.global_market;
  const cards = [
    ["Fear & Greed", fg ? `${fg.value} · ${fg.classification}` : "No disponible"],
    ["Dominancia BTC", global ? `${global.btc_dominance.toFixed(1)}%` : "No disponible"],
    ["Macro FRED", `${context?.macro_score || 0} / 100`],
    ["Hashrate 7d", context?.onchain ? `${context.onchain.hashrate_7d_change_pct >= 0 ? "+" : ""}${context.onchain.hashrate_7d_change_pct.toFixed(1)}%` : "No disponible"],
  ];
  return (
    <section className="panel context-panel">
      <div className="panel-heading">
        <div><p className="eyebrow">Régimen de riesgo</p><h2>Contexto compuesto</h2></div>
        <span className={`context-label ${context?.label || "neutral"}`}>{context?.label || "neutral"}</span>
      </div>
      <div className="context-score">
        <strong>{score > 0 ? "+" : ""}{score}</strong><span>/ 100</span>
      </div>
      <div className="score-track"><i style={{ left: `${position}%` }} /></div>
      <div className="score-labels"><span>Restrictivo</span><span>Neutral</span><span>Expansivo</span></div>
      <div className="context-grid">
        {cards.map(([label, value]) => <div key={label}><small>{label}</small><strong>{value}</strong></div>)}
      </div>
      {(context?.missing_sources || []).length > 0 && (
        <p className="data-warning">Confianza reducida: {context.missing_sources.join(", ")} sin datos.</p>
      )}
    </section>
  );
}

