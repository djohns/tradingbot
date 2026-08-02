# Northstar — Bot de análisis y señales cripto

Northstar monitorea BTC y altcoins, combina análisis técnico, Smart Money
Concepts, contexto macro/on-chain y sentimiento, y publica señales estructuradas
con control de riesgo. Opera en modo **asesor**: nunca abre ni cierra órdenes.

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
- EMA 20/50/200, RSI y divergencias, MACD, Bollinger, ATR y volumen relativo.
- BOS/CHoCH, order blocks, fair value gaps, barridos y zonas de liquidez.
- Triángulos y canales mediante regresión.
- Señales long/short con puntuación de confluencia, razones, entrada, SL, TP1/TP2, R:R, tamaño
  máximo sugerido y disclaimer.
- SQLite para deduplicación, histórico y liquidación auditable de señales.
- Ejecución simulada Binance USDⓈ-M con comisiones maker/taker, spread,
  slippage y funding histórico público (o fallback explícitamente estimado).
- Salida parcial en TP1, stop a break-even, TP2 real y cierre temporal.
- Backtesting con win rate, expectancy, profit factor, drawdown y métricas por
  régimen.
- Alertas opcionales por Telegram.
- Dashboard React desplegable en GitHub Pages.
- GitHub Actions para análisis horario, actualización de datos, pruebas y deploy.
- Monitor local opcional por WebSocket al cierre de velas.

## Arquitectura

```text
APIs públicas ──> collectors ──> indicadores + SMC + contexto
                                      │
                                      v
                              scoring + riesgo
                                │           │
                                v           v
                         SQLite / JSON   Telegram
                                │
                                v
                        dashboard estático
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
- `risk.minimum_rr`: ratio riesgo/beneficio mínimo.
- `risk.minimum_confidence`: umbral de publicación.
- `risk.max_open_signals_per_asset`: evita acumular señales duplicadas.
- `risk.max_portfolio_risk_pct`: limita el riesgo agregado de señales correlacionadas.
- `risk.cooldown_bars_after_loss`: pausa nuevas entradas tras un stop.
- `execution.maker_fee_rate` / `taker_fee_rate`: comisión de tu nivel de Binance.
- `execution.spread_bps` / `slippage_bps`: hipótesis conservadoras de ejecución.
- `execution.bnb_fee_discount_pct`: descuento aplicable si pagas comisiones con BNB.
- `execution.max_bars_open`: vencimiento temporal de la operación.
- `execution.tp1_close_fraction`: fracción liquidada en TP1; el resto busca TP2.

El tamaño sugerido se calcula como:

```text
(capital × riesgo %) / distancia entre entrada y stop
```

El stop usa estructura reciente y ATR. Cambiar los parámetros no garantiza
rentabilidad; ejecuta backtests y pruebas fuera de muestra antes de usar una
configuración.

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

### Telegram

1. Crea un bot con `@BotFather` y conserva el token.
2. Envía un mensaje al bot.
3. Consulta `https://api.telegram.org/bot<TOKEN>/getUpdates` y toma el `chat.id`.
4. Configura `TELEGRAM_BOT_TOKEN` y `TELEGRAM_CHAT_ID`.

Telegram solo recibe señales nuevas que superen el umbral; las ejecuciones
repetidas no duplican mensajes porque el ID de cada señal se deriva de
activo/timeframe/lado/cierre de vela.

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

`python -m backend.main --backtest` recorre temporalmente la misma puntuación
técnica que usa el motor en vivo, entra en la apertura siguiente, aplica la
gestión TP1/TP2 y calcula el resultado neto con costes. El contexto histórico
macro/on-chain se mantiene neutral para evitar usar el contexto actual como
información futura. Una vela que toca stop y objetivo se trata como pérdida.
Reporta:

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
│   ├── analysis/             # indicadores, SMC, patrones, contexto
│   ├── signals/              # scoring y riesgo
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
