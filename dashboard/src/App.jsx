import { useEffect, useState } from "react";
import ContextPanel from "./components/ContextPanel";
import MarketView from "./components/MarketView";
import PerformancePanel from "./components/PerformancePanel";
import SignalFeed from "./components/SignalFeed";
import SystemStatus from "./components/SystemStatus";

const files = ["market", "signals", "performance", "context", "system"];

function useBotData() {
  const [data, setData] = useState({});
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    let active = true;
    const load = async () => {
      try {
        const responses = await Promise.all(
          files.map((name) => fetch(`${import.meta.env.BASE_URL}data/${name}.json?ts=${Date.now()}`)),
        );
        if (responses.some((response) => !response.ok)) throw new Error("No se pudieron cargar los datos");
        const values = await Promise.all(responses.map((response) => response.json()));
        if (active) setData(Object.fromEntries(files.map((name, index) => [name, values[index]])));
      } catch (reason) {
        if (active) setError(reason.message);
      } finally {
        if (active) setLoading(false);
      }
    };
    load();
    const timer = window.setInterval(load, 60_000);
    return () => { active = false; window.clearInterval(timer); };
  }, []);
  return { data, error, loading };
}

export default function App() {
  const { data, error, loading } = useBotData();
  return (
    <div className="app-shell">
      <header className="topbar">
        <a href="#" className="brand" aria-label="Northstar inicio">
          <span className="brand-mark">N</span>
          <span><strong>NORTHSTAR</strong><small>CRYPTO INTELLIGENCE</small></span>
        </a>
        <div className="topbar-meta">
          <span className="mode"><i /> V2 · {(data.system?.strategy_mode || "shadow").toUpperCase()}</span>
          <span className="utc">UTC · 24/7</span>
        </div>
      </header>
      <main>
        <div className="intro">
          <div>
            <p className="eyebrow">Motor V2 · régimen, disparador y coste</p>
            <h1>Menos señales.<br /><em>Más evidencia.</em></h1>
          </div>
          <p>Rupturas tendenciales y reversión lateral funcionan como modelos separados. La V2 permanece en simulación hasta superar la validación fuera de muestra.</p>
        </div>
        {loading && <div className="loading"><span /> Sincronizando inteligencia de mercado…</div>}
        {error && <div className="error-banner">No pudimos actualizar los datos: {error}</div>}
        {!loading && (
          <>
            <SystemStatus system={data.system} />
            <div className="dashboard-grid">
              <MarketView market={data.market} />
              <SignalFeed signals={data.signals} />
              <PerformancePanel performance={data.performance} />
              <ContextPanel context={data.context} />
            </div>
          </>
        )}
      </main>
      <footer className="site-footer">
        <p>Northstar genera análisis algorítmico con fines informativos. No constituye asesoría financiera.</p>
        <span>Las pérdidas en criptoactivos pueden ser sustanciales.</span>
      </footer>
    </div>
  );
}
