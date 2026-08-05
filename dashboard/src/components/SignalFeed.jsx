import { money, dateTime } from "../lib/format";

const ACTIVE_STATES = new Set(["pendiente", "abierta", "parcial", "sombra"]);

function SignalCard({ signal, historical = false }) {
  return (
    <article className={`signal-card ${signal.tipo} ${historical ? "historical" : "active"}`}>
      <div className="signal-top">
        <span className="side">{signal.tipo === "long" ? "LONG ↗" : "SHORT ↘"}</span>
        <span className={`status ${signal.estado}`}>{signal.estado}</span>
      </div>
      <div className="signal-title">
        <h3>{signal.activo.replace("USDT", "")}<small>/USDT · {signal.timeframe}</small></h3>
        <div className="confidence" title="Calidad de reglas superadas; no es una probabilidad de éxito">
          <strong>{signal.confianza}</strong><span> calidad</span>
        </div>
      </div>
      <div className="strategy-line">
        <span>{signal.version_estrategia?.toUpperCase() || "V1"}</span>
        <span>{signal.estrategia?.replaceAll("_", " ") || "confluencia histórica"}</span>
        {signal.modo && <span>{signal.modo}</span>}
      </div>
      <div className="levels">
        <div><small>Entrada</small><strong>{money(signal.entrada_sugerida)}</strong></div>
        <div><small>Stop</small><strong>{money(signal.stop_loss)}</strong></div>
        <div><small>Objetivo</small><strong>{money(signal.take_profit_1)}</strong></div>
      </div>
      <p className="reason">{signal.razones?.[0]}</p>
      {signal.regimen?.name && (
        <p className="regime-line">Régimen: {signal.regimen.name.replaceAll("_", " ")} · coste {signal.coste_estimado_bps} bps</p>
      )}
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
  );
}

function SignalGroup({ id, title, subtitle, items, historical = false }) {
  return (
    <section className={`signal-group ${historical ? "history-group" : "active-group"}`} aria-labelledby={id}>
      <div className="signal-group-heading">
        <div>
          <h3 id={id}><i />{title}</h3>
          <p>{subtitle}</p>
        </div>
        <span>{items.length}</span>
      </div>
      <div className="signal-group-items">
        {items.length === 0 ? (
          <div className="empty-state compact">
            {historical ? "Todavía no hay operaciones cerradas." : "No hay señales activas en este momento."}
          </div>
        ) : (
          items.slice(0, historical ? 20 : 12).map((signal) => (
            <SignalCard signal={signal} historical={historical} key={signal.id} />
          ))
        )}
      </div>
    </section>
  );
}

export default function SignalFeed({ signals }) {
  const items = signals?.signals || [];
  const activeSignals = items.filter((signal) => ACTIVE_STATES.has(signal.estado));
  const historicalSignals = items.filter((signal) => !ACTIVE_STATES.has(signal.estado));
  return (
    <section className="panel signal-panel">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">Radar cuantitativo</p>
          <h2>Señales</h2>
        </div>
        <span className="count-badge">{items.length}</span>
      </div>
      <div className="signal-list">
        <SignalGroup
          id="active-signals-title"
          title="Señales activas"
          subtitle="Candidatas V2 en sombra y operaciones aún abiertas"
          items={activeSignals}
        />
        <SignalGroup
          id="historical-signals-title"
          title="Historial"
          subtitle="Operaciones cerradas y resultados netos"
          items={historicalSignals}
          historical
        />
      </div>
    </section>
  );
}
