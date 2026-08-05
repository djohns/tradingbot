# Northstar — Bot de análisis y señales cripto

Northstar V2 monitorea BTC y altcoins mediante dos modelos cuantitativos
independientes: ruptura tendencial y reversión lateral. Antes de registrar una
candidata exige régimen, disparador, coste y riesgo válidos. Opera en modo
**sombra** hasta superar las puertas de validación; nunca abre ni cierra órdenes.

> **Aviso:** las señales son generadas algorítmicamente con fines informativos.
> No constituyen asesoría financiera. Los criptoactivos son volátiles y pueden
> ocasionar pérdidas sustanciales; valida siempre los supuestos y decide tu
> propia gestión de riesgo.

## Qué incluye

- Datos OHLCV, ticker y libro de órdenes con Binance/Kraken y fallback automático.
- Dominancia y capitalización global desde CoinGecko.
- Fear & Greed de Alternative.me.
- Contexto macro opcional con FRED: dólar ponderado, tasa de fondos federales,
  M2, curva 10Y-2Y e IPC.
- Contexto on-chain gratuito con mempool.space y Blockchain.com.
- Sentimiento social opcional con LunarCrush.
- EMA 20/50/200, Donchian 10/20/55, ADX, Efficiency Ratio, Bollinger, ATR,
  volatilidad realizada y volumen relativo.
- Clasificador con veto duro para regímenes tendencial, lateral y transición.
- Ruptura Donchian confirmada en 4h, alineación diaria, volumen y filtro especial
  para cortos en altcoins según el régimen de BTC.
- Reversión a la media en 1h únicamente en régimen lateral y con rechazo real
  en el extremo de Bollinger.
- Ranking de fuerza relativa de 14 días como selector de activos.
- Filtro económico que exige que el movimiento esperado supere al menos tres
  veces comisiones, spread, slippage y funding estimado.
- Snapshot Binance Futures de mark/index price, funding, intervalo dinámico y
  open interest; una caída superior al 3% entre ejecuciones veta la ruptura.
- Riesgo adaptado a volatilidad entre 0,25% y 0,50%, límite de notional y tope
  agregado para exposiciones correlacionadas.
- SQLite para deduplicación, histórico y liquidación auditable de señales.
- Ejecución simulada Binance USDⓈ-M con comisiones maker/taker, spread,
  slippage y funding histórico público (o fallback explícitamente estimado).
- Chandelier/ATR y veto de falta de continuación para tendencias; objetivo en
  la media para rangos. La lógica V1 se conserva solo para liquidar su historial.
- Replay cronológico, folds walk-forward con parámetros fijos y estrés de costes
  1x/2x/3x. La V2 no se declara validada con menos de 150 operaciones OOS.
- Alertas opcionales por Telegram.
- Dashboard React desplegable en GitHub Pages.
- GitHub Actions para análisis horario, actualización de datos, pruebas y deploy.
- Monitor local opcional por WebSocket al cierre de velas.

## Arquitectura

```text
APIs públicas ──> indicadores ──> régimen ──> selector de estrategia
                                                   │
                                                   v
                                        disparador obligatorio
                                                   │
                                                   v
                                         costes ──> riesgo
                                                   │
                                                   v
                                  SQLite / JSON / dashboard
```

La ejecución programada escribe los mismos cinco contratos que consume el
dashboard:

- `market.json`: velas, EMAs, volumen, order blocks y liquidez.
- `signals.json`: feed histórico de señales.
- `performance.json`: resultados reales simulados y backtests.
- `context.json`: score macro, sentimiento, dominancia y on-chain.
- `system.json`: salud y última actualización de cada fuente.

Los archivos se guardan en `backend/data/` y se copian a
`dashboard/public/data/`. Si una fuente opcional falla, las restantes siguen
operando y el output indica qué datos faltan.

## Puesta en marcha local

Requiere Python 3.12+ y Node.js 22+.

```bash
git clone <URL-DE-TU-REPOSITORIO>
cd <NOMBRE-DEL-REPOSITORIO>

python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements-dev.txt

cp .env.example .env
python -m backend.main --backtest

cd dashboard
npm ci
npm run dev
```

Abre la URL que muestra Vite. El bot funciona sin claves para las fuentes
públicas; sin `FRED_API_KEY`, el contexto macro queda neutral y marcado como no
configurado.

### Ejecuciones disponibles

```bash
# Análisis periódico y actualización de JSON
python -m backend.main

# Análisis más backtest sobre las velas descargadas
python -m backend.main --backtest

# Monitor continuo: reanaliza al cerrar cada vela configurada
python -m backend.live_monitor

# Pruebas del backend
pytest -q

# Validación del dashboard
cd dashboard
npm run build
npm run lint
```

## Configuración

Edita `backend/config.yaml` para cambiar:

- `assets`: pares USDT monitoreados.
- `timeframes`: velas recolectadas.
- `signal_timeframes`: cierres que pueden producir señales.
- `risk.capital_usd`: capital hipotético usado para dimensionar.
- `risk.risk_per_trade_pct`: pérdida máxima sugerida por operación.
- `risk.minimum_risk_per_trade_pct`: suelo del riesgo tras escalar volatilidad.
- `risk.volatility_target_annual_pct`: objetivo usado para reducir tamaño.
- `risk.max_notional_pct`: límite de exposición por señal.
- `risk.max_open_signals_per_asset`: evita acumular señales duplicadas.
- `risk.max_portfolio_risk_pct`: limita el riesgo agregado de señales correlacionadas.
- `risk.cooldown_bars_after_loss`: pausa nuevas entradas tras un stop.
- `execution.maker_fee_rate` / `taker_fee_rate`: comisión de tu nivel de Binance.
- `execution.spread_bps` / `slippage_bps`: hipótesis conservadoras de ejecución.
- `execution.bnb_fee_discount_pct`: descuento aplicable si pagas comisiones con BNB.
- `strategy_v2.mode`: `shadow` o `live`; solo `live` permite alertas Telegram.
- `strategy_v2.regime`: umbrales ADX y Efficiency Ratio.
- `strategy_v2.trend`: canal, volumen, stops y salida Chandelier.
- `strategy_v2.range`: z-score, rechazo, stop y duración máxima.
- `strategy_v2.cost_gate_multiple`: margen mínimo frente a costes.
- `validation`: cantidad OOS, profit factor, expectancy, drawdown y estrés.

El tamaño sugerido se calcula como:

```text
(capital × riesgo %) / distancia entre entrada y stop
```

El riesgo efectivo se reduce cuando la volatilidad observada supera el objetivo.
Cambiar los parámetros no autoriza el modo live: primero deben superarse las
puertas OOS y el periodo de observación en sombra.

### Costes de Binance Futures

El perfil incluido asume USDⓈ-M Futures, nivel VIP 0 y órdenes taker de forma
conservadora. Las tasas son configurables porque Binance las determina según
producto, nivel VIP, promociones y uso de BNB. El bot no accede a la cuenta ni
envía órdenes: calcula comisiones sobre el notional simulado de cada fill.

Al cerrar una señal consulta el historial público de funding de Binance para el
contrato y periodo exactos. Si el endpoint no está disponible desde GitHub
Actions, usa `fallback_funding_rate` y marca el resultado como estimado. El
funding conserva su signo: puede ser un coste o un ingreso.

Cada cierre guarda precio y fecha de salida, motivo, legs parciales, PnL bruto,
PnL neto, comisiones, impacto de spread/slippage, funding, MFE, MAE y duración.

## Variables y secretos

Copia `.env.example` a `.env` solo para desarrollo local. `.env` está ignorado
por Git y nunca debe subirse.

| Variable | Obligatoria | Uso |
|---|---:|---|
| `FRED_API_KEY` | No | Score macro con datos de FRED |
| `LUNARCRUSH_API_KEY` | No | Métricas de sentimiento social |
| `COINGECKO_API_KEY` | No | Mayor límite del plan Demo |
| `TELEGRAM_BOT_TOKEN` | No | Envío de alertas |
| `TELEGRAM_CHAT_ID` | No | Destino de Telegram |
| `BOT_CONFIG` | No | Ruta alternativa al YAML |
| `BOT_LOG_LEVEL` | No | Nivel de logs; por defecto `INFO` |
| `MARKET_DATA_PROVIDER` | No | `auto`, `binance` o `kraken` |
| `BINANCE_MAKER_FEE_RATE` | No | Comisión maker efectiva de la cuenta |
| `BINANCE_TAKER_FEE_RATE` | No | Comisión taker efectiva de la cuenta |
| `BINANCE_BNB_FEE_DISCOUNT_PCT` | No | Descuento real por BNB |
| `BOT_STRATEGY_MODE` | No | `shadow` o `live`; por defecto `shadow` |

### Telegram

1. Crea un bot con `@BotFather` y conserva el token.
2. Envía un mensaje al bot.
3. Consulta `https://api.telegram.org/bot<TOKEN>/getUpdates` y toma el `chat.id`.
4. Configura `TELEGRAM_BOT_TOKEN` y `TELEGRAM_CHAT_ID`.

Telegram solo recibe señales cuando `strategy_v2.mode` es `live`. Las candidatas
`shadow` se guardan y liquidan para validación, pero nunca se notifican como una
operación ejecutable. Los IDs deterministas evitan duplicados.

## Subir a GitHub

Desde la raíz:

```bash
git init
git add .
git commit -m "feat: initial crypto advisor bot"
git branch -M main
git remote add origin <URL-DE-TU-REPOSITORIO>
git push -u origin main
```

### Configurar GitHub Secrets

En el repositorio abre **Settings → Secrets and variables → Actions → New
repository secret**. Crea únicamente los secretos que vayas a usar, con estos
nombres exactos:

- `FRED_API_KEY`
- `LUNARCRUSH_API_KEY`
- `COINGECKO_API_KEY`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

### Activar GitHub Pages

1. Abre **Settings → Pages**.
2. En **Build and deployment → Source**, selecciona **GitHub Actions**.
3. Abre **Actions** y ejecuta manualmente **Analyze market and deploy
   dashboard** la primera vez.
4. Al terminar, la URL aparecerá en el resumen del job `deploy`.

El workflow:

1. Descarga datos desde Kraken en GitHub Actions y ejecuta el motor.
2. Actualiza los JSON y los confirma con `github-actions[bot]`.
3. Compila el dashboard.
4. Publica el artefacto en GitHub Pages.

El `GITHUB_TOKEN` integrado tiene permisos mínimos declarados por el workflow;
no se necesita un PAT. Si la organización bloquea escrituras desde Actions,
habilita **Settings → Actions → General → Workflow permissions → Read and write
permissions**.

GitHub Actions usa Kraken como fuente primaria porque Binance puede bloquear
runners alojados en Estados Unidos con HTTP 451. En local, `auto` prefiere
Binance. Ambas fuentes actúan como respaldo mutuo. Si ninguna devuelve velas, la
ejecución falla antes de escribir archivos: el dashboard conserva el último
snapshot válido en lugar de publicar datos vacíos.

### Frecuencia

El cron vive en `.github/workflows/run-bot.yml`:

```yaml
schedule:
  - cron: "17 * * * *"
```

Ese valor ejecuta el análisis una vez por hora, a los 17 minutos. GitHub cron
usa UTC y puede tener demoras. Para cada 30 minutos:

```yaml
- cron: "17,47 * * * *"
```

No conviene usar menos de 15 minutos: aumenta rate limits y no aporta precisión
si las señales se evalúan al cierre de 1h/4h.

Además, el workflow ejecuta el backtest completo una vez al día a las 03:47 UTC.
Las ejecuciones horarias conservan el último backtest publicado hasta que el
siguiente cálculo diario lo reemplaza.

## Backtesting y lectura de métricas

`python -m backend.main --backtest` recorre cronológicamente el mismo motor V2,
entra en la apertura siguiente y aplica su salida específica. Los canales están
desplazados una vela para impedir look-ahead. El contexto histórico macro/on-chain
se mantiene neutral y el ranking transversal se desactiva cuando no existe un
universo histórico sincronizado.

El informe separa ruptura y reversión, largos/cortos y regímenes. También crea
folds temporales y repite el replay con costes 1x, 2x y 3x. Las puertas mínimas
incluidas son:

- 150 operaciones fuera de muestra;
- expectancy neta positiva;
- profit factor mínimo 1,20;
- drawdown máximo de 12R;
- supervivencia con costes duplicados.

Mientras alguna puerta falle, `validation_v2.status` será `shadow_required` y
el dashboard mostrará **V2 en validación**. Aunque se solicite `live`, el backend
fuerza `shadow` mientras el último backtest publicado no cumpla todas las puertas.
Además reporta:

- win rate;
- R promedio y expectancy;
- profit factor;
- drawdown máximo en múltiplos R;
- desglose alcista, bajista y lateral.

Este backtest sigue siendo una aproximación: modela comisiones, spread,
slippage y funding, pero no conoce los fills de la cuenta, profundidad histórica
completa, latencia personal ni impuestos. Para una decisión seria se necesitan
datos más extensos y validación walk-forward fuera de muestra.

## Decisiones de seguridad

- No existe código para firmar, enviar o ejecutar órdenes.
- No se solicitan claves privadas ni credenciales de trading.
- Todas las peticiones tienen timeout, reintentos y backoff.
- Los secretos solo se leen del entorno.
- SQLite y `.env` están excluidos del repositorio.
- Los outputs marcan fuentes degradadas y reducen la confianza.
- El workflow de pruebas compila, ejecuta lint y corre los tests en cada PR.

## Estructura

```text
.
├── .github/workflows/        # análisis/deploy y CI
├── backend/
│   ├── collectors/           # Binance, CoinGecko, FRED, F&G, on-chain, social
│   ├── analysis/             # indicadores, régimen, SMC y contexto
│   ├── signals/              # motor V2 y riesgo; V1 solo histórica
│   ├── backtesting/          # simulador y métricas
│   ├── alerts/               # Telegram
│   ├── data/                 # JSON versionados; SQLite local ignorado
│   ├── config.yaml
│   ├── main.py
│   └── live_monitor.py
├── dashboard/                # React + Vite + Recharts
├── tests/
├── .env.example
└── README.md
```
