import { dateTime } from "../lib/format";

export default function SystemStatus({ system }) {
  const sources = system?.sources || [];
  const summary = new Map();
  sources.forEach((source) => {
    const base = source.name?.split(" ")[0] || "Fuente";
    const current = summary.get(base);
    if (!current || (current.status === "ok" && source.status !== "ok")) summary.set(base, source);
  });
  return (
    <section className="system-panel">
      <div>
        <span className={`pulse ${system?.overall_status || "degraded"}`} />
        <strong>{system?.overall_status === "operational" ? "Sistema operativo" : "Sistema degradado"}</strong>
        <small>Actualizado {dateTime(system?.updated_at)}</small>
        <span className={`validation-pill ${system?.validation_status || "shadow_required"}`}>
          {system?.validation_status === "validated" ? "V2 validada" : "V2 en validación"}
        </span>
      </div>
      <div className="source-row">
        {[...summary.values()].slice(0, 8).map((source) => (
          <span key={source.name} title={source.error || source.updated_at}>
            <i className={source.status} />{source.name}
          </span>
        ))}
      </div>
    </section>
  );
}
