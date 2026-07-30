import { useMemo, useState } from "react";
import {
  Area,
  Bar,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceArea,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { compact, money } from "../lib/format";

function ChartTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  const values = Object.fromEntries(payload.map((item) => [item.dataKey, item.value]));
  return (
    <div className="chart-tooltip">
      <span>{new Date(label).toLocaleString("es-CL")}</span>
      <strong>{money(values.close)}</strong>
      <small>Vol. {compact(values.volume)}</small>
    </div>
  );
}

export default function MarketView({ market }) {
  const symbols = Object.keys(market?.assets || {});
  const [selected, setSelected] = useState(symbols[0] || "BTCUSDT");
  const asset = market?.assets?.[selected] || market?.assets?.[symbols[0]];
  const chart = useMemo(
    () =>
      (asset?.candles || []).map((item) => ({
        ...item,
        timeLabel: new Date(item.time).toLocaleDateString("es-CL", {
          day: "2-digit",
          month: "short",
          hour: "2-digit",
        }),
      })),
    [asset],
  );
  if (!asset) {
    return <div className="empty-state">Ejecuta el bot para cargar datos de mercado.</div>;
  }
  const ticker = asset.ticker || {};
  const activeZones = (asset.zones || []).filter((zone) => zone.active).slice(-4);
  return (
    <section className="market-panel panel">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">Mercado / {asset.timeframe}</p>
          <h2>{selected.replace("USDT", "")} <span>/ USDT</span></h2>
        </div>
        <div className="asset-switcher" aria-label="Seleccionar activo">
          {symbols.map((symbol) => (
            <button
              key={symbol}
              className={symbol === selected ? "active" : ""}
              onClick={() => setSelected(symbol)}
            >
              {symbol.replace("USDT", "")}
            </button>
          ))}
        </div>
      </div>
      <div className="price-line">
        <strong>{money(ticker.price || chart.at(-1)?.close)}</strong>
        <span className={(ticker.change_24h_pct || 0) >= 0 ? "positive" : "negative"}>
          {(ticker.change_24h_pct || 0) >= 0 ? "↗" : "↘"} {Math.abs(ticker.change_24h_pct || 0).toFixed(2)}%
        </span>
        <small>Volumen 24h · {compact(ticker.quote_volume_24h)}</small>
      </div>
      <div className="chart-wrap" aria-label={`Gráfico de ${selected}`}>
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={chart} margin={{ top: 12, right: 5, bottom: 0, left: 5 }}>
            <defs>
              <linearGradient id="priceGlow" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#b9ff5a" stopOpacity={0.16} />
                <stop offset="100%" stopColor="#b9ff5a" stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid stroke="#1d242c" vertical={false} />
            <XAxis dataKey="time" tickFormatter={(value) => new Date(value).toLocaleDateString("es-CL", { day: "2-digit", month: "short" })} minTickGap={35} axisLine={false} tickLine={false} />
            <YAxis yAxisId="price" domain={["auto", "auto"]} orientation="right" tickFormatter={compact} axisLine={false} tickLine={false} width={58} />
            <YAxis yAxisId="volume" domain={[0, (max) => max * 5]} hide />
            <Tooltip content={<ChartTooltip />} />
            {activeZones.map((zone) => (
              <ReferenceArea
                key={`${zone.kind}-${zone.index}`}
                yAxisId="price"
                y1={zone.low}
                y2={zone.high}
                fill={zone.direction === "bullish" ? "#43dbaf" : "#ff6b7a"}
                fillOpacity={0.08}
                strokeOpacity={0}
              />
            ))}
            {(asset.liquidity_levels || []).map((level) => (
              <ReferenceLine key={`${level.kind}-${level.price}`} yAxisId="price" y={level.price} stroke="#ffcf5a" strokeDasharray="3 6" strokeOpacity={0.45} />
            ))}
            <Bar yAxisId="volume" dataKey="volume" fill="#26313a" />
            <Area yAxisId="price" type="monotone" dataKey="close" stroke="#b9ff5a" fill="url(#priceGlow)" strokeWidth={2.2} dot={false} />
            <Line yAxisId="price" type="monotone" dataKey="ema20" stroke="#54b8ff" strokeWidth={1} dot={false} />
            <Line yAxisId="price" type="monotone" dataKey="ema50" stroke="#aa7dff" strokeWidth={1} dot={false} />
            <Line yAxisId="price" type="monotone" dataKey="ema200" stroke="#f5a65b" strokeWidth={1} dot={false} />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <div className="legend">
        <span className="lime">Precio</span><span className="blue">EMA 20</span>
        <span className="violet">EMA 50</span><span className="orange">EMA 200</span>
        <span className="gold">Liquidez</span>
      </div>
    </section>
  );
}

