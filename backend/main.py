from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from backend.alerts.telegram import send_signal
from backend.analysis.context import compose_context
from backend.analysis.indicators import add_indicators
from backend.analysis.smc import analyze_smc
from backend.backtesting.backtest import run_backtest
from backend.collectors.coingecko import CoinGeckoCollector
from backend.collectors.feargreed import FearGreedCollector
from backend.collectors.fred import FredCollector
from backend.collectors.lunarcrush import LunarCrushCollector
from backend.collectors.market import ResilientMarketCollector
from backend.collectors.onchain import OnChainCollector
from backend.config import load_config, secret
from backend.signals.engine import evaluate
from backend.storage import Storage

LOGGER = logging.getLogger("crypto_bot")


class MarketDataUnavailable(RuntimeError):
    """Raised before output writes when no valid market snapshot was collected."""


def require_market_data(market: dict[str, Any]) -> None:
    """Fail closed so scheduled jobs never replace valid data with an empty set."""
    if not market.get("assets"):
        raise MarketDataUnavailable(
            "No market assets were collected; preserving the last published snapshot"
        )


def safe_collect(name: str, operation: Callable[[], Any]) -> tuple[Any | None, dict[str, Any]]:
    started = datetime.now(timezone.utc)
    try:
        value = operation()
        return value, {
            "name": name,
            "status": "ok",
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "latency_ms": int((datetime.now(timezone.utc) - started).total_seconds() * 1000),
        }
    except Exception as exc:
        LOGGER.warning("%s unavailable: %s", name, exc)
        return None, {
            "name": name,
            "status": "degraded",
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "error": str(exc)[:180],
        }


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def read_previous_signals(output_dir: Path) -> list[dict[str, Any]]:
    path = output_dir / "signals.json"
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        signals = payload.get("signals", [])
        return signals if isinstance(signals, list) else []
    except (OSError, ValueError, TypeError):
        LOGGER.warning("Could not restore previous signal history from %s", path)
        return []


def settle_open_signals(storage: Storage, symbol: str, price_frame: Any) -> None:
    """Resolve open signals against every completed candle since publication.

    A candle touching stop and target is counted as a loss because intrabar
    ordering is unknown. This deliberately avoids optimistic performance data.
    """
    for signal in storage.open_for_asset(symbol):
        side = signal["tipo"]
        published = datetime.fromisoformat(signal["timestamp"])
        candles = price_frame[price_frame["close_time"] >= published]
        for candle in candles.itertuples():
            stop_hit = (
                candle.low <= signal["stop_loss"]
                if side == "long"
                else candle.high >= signal["stop_loss"]
            )
            target_hit = (
                candle.high >= signal["take_profit_1"]
                if side == "long"
                else candle.low <= signal["take_profit_1"]
            )
            if stop_hit:
                storage.settle(signal["id"], "perdedora", -1.0)
                break
            if target_hit:
                storage.settle(
                    signal["id"], "ganadora", signal["ratio_riesgo_beneficio"]
                )
                break


def run(config_path: str | None = None, *, backtest: bool = False) -> dict[str, Any]:
    config = load_config(config_path)
    network = config["network"]
    kwargs = {
        "timeout": network["timeout_seconds"],
        "max_retries": network["max_retries"],
        "backoff": network["backoff_seconds"],
    }
    market_collector = ResilientMarketCollector(**kwargs)
    statuses: list[dict[str, Any]] = []
    fear_greed, status = safe_collect("Fear & Greed", FearGreedCollector(**kwargs).current)
    statuses.append(status)
    global_market, status = safe_collect(
        "CoinGecko",
        CoinGeckoCollector(api_key=secret("COINGECKO_API_KEY"), **kwargs).global_market,
    )
    statuses.append(status)
    onchain, status = safe_collect("On-chain", OnChainCollector(**kwargs).snapshot)
    statuses.append(status)
    fred_key = secret("FRED_API_KEY")
    if fred_key:
        fred, status = safe_collect("FRED", FredCollector(fred_key, **kwargs).snapshot)
    else:
        fred, status = None, {
            "name": "FRED",
            "status": "not_configured",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    statuses.append(status)

    social: dict[str, Any] = {}
    lunar_key = secret("LUNARCRUSH_API_KEY")
    if lunar_key:
        lunar = LunarCrushCollector(lunar_key, **kwargs)
        for symbol in config["assets"]:
            coin = symbol.removesuffix("USDT")
            social[coin], status = safe_collect(f"LunarCrush {coin}", lambda c=coin: lunar.coin(c))
            statuses.append(status)

    context = compose_context(
        fear_greed=fear_greed,
        global_market=global_market,
        fred=fred,
        onchain=onchain,
        weights=config["context"],
    )
    context["social"] = social
    context["updated_at"] = datetime.now(timezone.utc).isoformat()

    output_dir = Path(config["storage"]["output_dir"])
    storage = Storage(config["storage"]["sqlite_path"])
    restored_signals = storage.hydrate(read_previous_signals(output_dir))
    if restored_signals:
        LOGGER.info("Restored %s historical signals from JSON", restored_signals)
    market: dict[str, Any] = {
        "updated_at": context["updated_at"],
        "assets": {},
        "provider_order": market_collector.provider_order,
    }
    diagnostics: list[dict[str, Any]] = []
    backtests: dict[str, Any] = {}
    new_signals: list[dict[str, Any]] = []
    for symbol in config["assets"]:
        frames: dict[str, Any] = {}
        for timeframe in config["timeframes"]:
            frame, status = safe_collect(
                f"Market {symbol} {timeframe}",
                lambda s=symbol, tf=timeframe: market_collector.klines(
                    s, tf, config["candle_limit"]
                ),
            )
            statuses.append(status)
            if frame is not None:
                closed = frame[frame["close_time"] <= datetime.now(timezone.utc)]
                if len(closed) >= 210:
                    frames[timeframe] = add_indicators(closed)
        ticker, status = safe_collect(
            f"Market ticker {symbol}",
            lambda s=symbol: market_collector.ticker_24h(s),
        )
        statuses.append(status)
        order_book, status = safe_collect(
            f"Market orderbook {symbol}",
            lambda s=symbol: market_collector.order_book(s),
        )
        statuses.append(status)
        if not frames:
            continue
        chart_tf = "1h" if "1h" in frames else next(iter(frames))
        chart = frames[chart_tf].tail(180)
        smc = analyze_smc(frames[chart_tf])
        market["assets"][symbol] = {
            "ticker": ticker,
            "order_book": order_book,
            "data_provider": market_collector.last_provider,
            "timeframe": chart_tf,
            "candles": [
                {
                    "time": row.open_time.isoformat(),
                    "open": round(float(row.open), 8),
                    "high": round(float(row.high), 8),
                    "low": round(float(row.low), 8),
                    "close": round(float(row.close), 8),
                    "volume": round(float(row.volume), 4),
                    "ema20": round(float(row.ema_20), 8),
                    "ema50": round(float(row.ema_50), 8),
                    "ema200": round(float(row.ema_200), 8),
                }
                for row in chart.itertuples()
            ],
            "zones": smc["order_blocks"] + smc["fair_value_gaps"],
            "liquidity_levels": smc["liquidity_levels"],
        }
        settle_open_signals(storage, symbol, frames[chart_tf])
        max_open = int(config["risk"]["max_open_signals_per_asset"])
        if len(storage.open_for_asset(symbol)) < max_open:
            for timeframe in config["signal_timeframes"]:
                if timeframe not in frames:
                    continue
                signal, detail = evaluate(
                    symbol, timeframe, frames, context, config["risk"]
                )
                diagnostics.append(detail)
                if signal and storage.save_signal(signal):
                    new_signals.append(signal)
        if backtest and "1h" in frames:
            backtests[symbol] = run_backtest(frames["1h"], config["risk"]["minimum_rr"])

    signals = storage.list_signals()
    settled = [signal for signal in signals if signal["resultado_r"] is not None]
    results = [float(signal["resultado_r"]) for signal in reversed(settled)]
    equity = [0.0]
    for result in results:
        equity.append(round(equity[-1] + result, 3))
    peak, max_drawdown = 0.0, 0.0
    for value in equity:
        peak = max(peak, value)
        max_drawdown = max(max_drawdown, peak - value)
    wins = [result for result in results if result > 0]
    performance = {
        "total_signals": len(signals),
        "settled_signals": len(settled),
        "win_rate": round(len(wins) / len(results) * 100, 2) if results else 0,
        "average_r": round(sum(results) / len(results), 3) if results else 0,
        "expectancy": round(sum(results) / len(results), 3) if results else 0,
        "max_drawdown_r": round(max_drawdown, 3),
        "equity_curve": equity,
        "backtests": backtests,
        "updated_at": context["updated_at"],
    }
    market_statuses = [
        item for item in statuses if str(item.get("name", "")).startswith("Market ")
    ]
    system = {
        "updated_at": context["updated_at"],
        "overall_status": "operational"
        if market["assets"]
        and market_statuses
        and all(item["status"] == "ok" for item in market_statuses)
        else "degraded",
        "market_data_available": bool(market["assets"]),
        "market_providers": market_collector.provider_order,
        "sources": statuses,
        "new_signals": len(new_signals),
        "diagnostics": diagnostics,
    }
    require_market_data(market)
    outputs = {
        "market.json": market,
        "signals.json": {"updated_at": context["updated_at"], "signals": signals},
        "performance.json": performance,
        "context.json": context,
        "system.json": system,
    }
    public_dir = Path(config["dashboard"]["public_data_dir"])
    for filename, payload in outputs.items():
        write_json(output_dir / filename, payload)
        public_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(output_dir / filename, public_dir / filename)

    token, chat_id = secret("TELEGRAM_BOT_TOKEN"), secret("TELEGRAM_CHAT_ID")
    if config["alerts"]["telegram_enabled"] and token and chat_id:
        for signal in new_signals:
            try:
                send_signal(token, chat_id, signal, network["timeout_seconds"])
            except Exception as exc:
                LOGGER.warning("Telegram notification failed: %s", exc)
    return {"new_signals": len(new_signals), "assets": len(market["assets"]), "output": str(output_dir)}


def cli() -> None:
    parser = argparse.ArgumentParser(description="Crypto market analysis and signal bot")
    parser.add_argument("--config", help="Path to config.yaml")
    parser.add_argument("--backtest", action="store_true", help="Include historical backtests")
    args = parser.parse_args()
    logging.basicConfig(
        level=os.getenv("BOT_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    result = run(args.config, backtest=args.backtest)
    LOGGER.info("Run complete: %s", result)


if __name__ == "__main__":
    cli()
