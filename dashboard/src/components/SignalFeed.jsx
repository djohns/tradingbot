import { money, dateTime } from "../lib/format";

export default function SignalFeed({ signals }) {
  const items = signals?.signals || [];
  return (
    <section className="panel signal-panel">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">Radar cuantitativo</p>
          <h2>Señales recientes</h2>
        </div>
        <span className="count-badge">{items.length}</span>
      </div>
      <div className="signal-list">
        {items.length === 0 && <div className="empty-state">Sin señales que superen el umbral actual.</div>}
        {items.slice(0, 12).map((signal) => (
          <article className={`signal-card ${signal.tipo}`} key={signal.id}>
            <div className="signal-top">
              <span className="side">{signal.tipo === "long" ? "LONG ↗" : "SHORT ↘"}</span>
              <span className={`status ${signal.estado}`}>{signal.estado}</span>
            </div>
            <div className="signal-title">
              <h3>{signal.activo.replace("USDT", "")}<small>/USDT · {signal.timeframe}</small></h3>
              <div className="confidence" title="Puntuación de confluencia; no es una probabilidad calibrada">
                <strong>{signal.puntuacion_confluencia ?? signal.confianza}</strong><span> confluencia</span>
              </div>
            </div>
            <div className="levels">
              <div><small>Entrada</small><strong>{money(signal.entrada_sugerida)}</strong></div>
              <div><small>Stop</small><strong>{money(signal.stop_loss)}</strong></div>
              <div><small>Objetivo</small><strong>{money(signal.take_profit_1)}</strong></div>
            </div>
            <p className="reason">{signal.razones?.[0]}</p>
            <footer>
              <span>
                {signal.resultado_r != null
                  ? `${signal.resultado_r > 0 ? "+" : ""}${signal.resultado_r} R neto · ${money(signal.pnl_neto_usd)}`
                  : `R:R ${signal.ratio_riesgo_beneficio}`}
              </span>
              <time>{dateTime(signal.timestamp)}</time>
            </footer>
            {signal.resultado_r != null && (
              <div className="cost-line">
                Costes {money(signal.costes_totales_usd)} · {signal.motivo_salida?.replaceAll("_", " ")}
              </div>
            )}
          </article>
        ))}
      </div>
    </section>
  );
}
