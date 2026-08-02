from __future__ import annotations

import argparse
import json
import logging
import math
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
from backend.collectors.binance_futures import BinanceFuturesCollector
from backend.collectors.feargreed import FearGreedCollector
from backend.collectors.fred import FredCollector
from backend.collectors.lunarcrush import LunarCrushCollector
from backend.collectors.market import ResilientMarketCollector
from backend.collectors.onchain import OnChainCollector
from backend.config import load_config, secret
from backend.execution import (
    as_utc,
    calculate_trade_result,
    estimated_funding_events,
    prepare_live_execution,
)
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


def read_previous_backtests(output_dir: Path) -> dict[str, Any]:
    path = output_dir / "performance.json"
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        backtests = payload.get("backtests", {})
        return backtests if isinstance(backtests, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _timeframe_hours(timeframe: str) -> float:
    unit = timeframe[-1]
    value = float(timeframe[:-1])
    return value / 60 if unit == "m" else value if unit == "h" else value * 24


def _cooldown_active(
    signals: list[dict[str, Any]], symbol: str, timeframe: str, bars: int
) -> bool:
    if bars <= 0:
        return False
    cutoff_hours = _timeframe_hours(timeframe) * bars
    now = datetime.now(timezone.utc)
    return any(
        item.get("activo") == symbol
        and item.get("timeframe") == timeframe
        and item.get("estado") == "perdedora"
        and item.get("cerrada_en")
        and (now - as_utc(item["cerrada_en"])).total_seconds() / 3600 < cutoff_hours
        for item in signals
    )


def _group_performance(
    signals: list[dict[str, Any]], field: str
) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for signal in signals:
        key = str(signal.get(field) or "sin_dato")
        grouped.setdefault(key, []).append(signal)
    return {
        key: {
            "trades": len(items),
            "win_rate": round(
                sum(float(item["resultado_r"]) > 0 for item in items) / len(items) * 100,
                2,
            ),
            "net_r": round(sum(float(item["resultado_r"]) for item in items), 3),
            "net_pnl_usd": round(sum(float(item.get("pnl_neto_usd", 0)) for item in items), 2),
            "costs_usd": round(sum(float(item.get("costes_totales_usd", 0)) for item in items), 2),
        }
        for key, items in grouped.items()
    }


def _wilson_interval(wins: int, total: int) -> list[float]:
    if total == 0:
        return [0.0, 0.0]
    z = 1.96
    rate = wins / total
    denominator = 1 + z * z / total
    centre = (rate + z * z / (2 * total)) / denominator
    margin = z * math.sqrt(rate * (1 - rate) / total + z * z / (4 * total * total)) / denominator
    return [round(max(0, centre - margin) * 100, 2), round(min(1, centre + margin) * 100, 2)]


def _legacy_execution_fields(
    signal: dict[str, Any], execution_config: dict[str, Any], risk_config: dict[str, Any]
) -> dict[str, Any]:
    """Make signals created before execution accounting safe to settle."""
    rr = float(signal["ratio_riesgo_beneficio"])
    entry = float(
        signal.get("entrada_sugerida")
        or (float(signal["take_profit_1"]) + rr * float(signal["stop_loss"]))
        / (rr + 1)
    )
    risk_usd = float(
        signal.get("capital_en_riesgo")
        or float(risk_config["capital_usd"])
        * float(risk_config["risk_per_trade_pct"])
        / 100
    )
    signal.setdefault("entrada_sugerida", entry)
    signal.setdefault("capital_en_riesgo", risk_usd)
    signal.setdefault(
        "tamano_posicion_sugerido", risk_usd / abs(entry - float(signal["stop_loss"]))
    )
    signal.setdefault("abierta_en", signal["timestamp"])
    signal.setdefault("spread_bps_aplicado", float(execution_config["spread_bps"]))
    signal.setdefault("slippage_bps_aplicado", float(execution_config["slippage_bps"]))
    signal.setdefault("tipo_entrada", execution_config["entry_order_type"])
    return signal


def _funding_for_trade(
    symbol: str,
    opened_at: datetime,
    closed_at: datetime,
    execution_config: dict[str, Any],
    funding_collector: BinanceFuturesCollector | None,
) -> list[dict[str, Any]]:
    if funding_collector is not None:
        try:
            return funding_collector.funding_history(symbol, opened_at, closed_at)
        except Exception as exc:
            LOGGER.warning("Binance funding unavailable for %s: %s", symbol, exc)
    return estimated_funding_events(
        opened_at,
        closed_at,
        float(execution_config["fallback_funding_rate"]),
        int(execution_config["fallback_funding_interval_hours"]),
    )


def _close_signal(
    storage: Storage,
    signal: dict[str, Any],
    candle: Any,
    exit_legs: list[dict[str, Any]],
    reason: str,
    execution_config: dict[str, Any],
    funding_collector: BinanceFuturesCollector | None,
    candles_seen: Any,
) -> None:
    closed_at = as_utc(candle.close_time)
    opened_at = as_utc(signal.get("abierta_en", signal["timestamp"]))
    funding = _funding_for_trade(
        signal["activo"], opened_at, closed_at, execution_config, funding_collector
    )
    result = calculate_trade_result(signal, exit_legs, execution_config, funding)
    entry = float(result["entrada_ejecutada"])
    quantity = float(signal["tamano_posicion_sugerido"])
    risk_usd = float(signal["capital_en_riesgo"])
    if signal["tipo"] == "long":
        mfe_usd = max(0.0, (float(candles_seen["high"].max()) - entry) * quantity)
        mae_usd = max(0.0, (entry - float(candles_seen["low"].min())) * quantity)
    else:
        mfe_usd = max(0.0, (entry - float(candles_seen["low"].min())) * quantity)
        mae_usd = max(0.0, (float(candles_seen["high"].max()) - entry) * quantity)
    net_r = float(result["resultado_r"])
    status = "ganadora" if net_r > 0 else "perdedora" if net_r < 0 else "neutral"
    details = {
        **result,
        "cerrada_en": closed_at.isoformat(),
        "motivo_salida": reason,
        "duracion_horas": round((closed_at - opened_at).total_seconds() / 3600, 2),
        "mfe_r": round(mfe_usd / risk_usd, 4) if risk_usd else 0.0,
        "mae_r": round(mae_usd / risk_usd, 4) if risk_usd else 0.0,
    }
    storage.settle(signal["id"], status, net_r, details)


def settle_open_signals(
    storage: Storage,
    symbol: str,
    price_frame: Any,
    execution_config: dict[str, Any],
    risk_config: dict[str, Any],
    funding_collector: BinanceFuturesCollector | None = None,
) -> None:
    """Resolve open signals against every completed candle since publication.

    A candle touching stop and target is counted as a loss because intrabar
    ordering is unknown. This deliberately avoids optimistic performance data.
    """
    for original in storage.open_for_asset(symbol):
        signal = _legacy_execution_fields(original, execution_config, risk_config)
        side = signal["tipo"]
        opened_at = as_utc(signal.get("abierta_en", signal["timestamp"]))
        # Never use a candle that began before publication: its extrema include
        # price action the trader could not have observed or executed.
        candles = price_frame[price_frame["open_time"] >= opened_at].copy()
        if candles.empty:
            continue
        tp1_reached = bool(signal.get("tp1_alcanzado_en"))
        if tp1_reached:
            progress_at = as_utc(signal["tp1_alcanzado_en"])
            process = candles[candles["open_time"] >= progress_at]
        else:
            process = candles
        max_bars = int(execution_config["max_bars_open"])
        close_fraction = float(execution_config["tp1_close_fraction"])
        for candle in process.itertuples():
            active_stop = (
                float(signal["entrada_sugerida"])
                if tp1_reached and execution_config["move_stop_to_break_even"]
                else float(signal["stop_loss"])
            )
            stop_hit = (
                candle.low <= active_stop
                if side == "long"
                else candle.high >= active_stop
            )
            tp1_hit = (
                candle.high >= signal["take_profit_1"]
                if side == "long"
                else candle.low <= signal["take_profit_1"]
            )
            if stop_hit:
                legs = []
                if tp1_reached:
                    legs.append(
                        {"fraction": close_fraction, "price": signal["take_profit_1"], "reason": "tp1"}
                    )
                legs.append(
                    {
                        "fraction": 1 - close_fraction if tp1_reached else 1.0,
                        "price": active_stop,
                        "reason": "break_even" if tp1_reached else "stop_loss",
                    }
                )
                _close_signal(
                    storage, signal, candle, legs, legs[-1]["reason"],
                    execution_config, funding_collector,
                    candles[candles["open_time"] <= candle.open_time],
                )
                break
            tp2_hit = tp1_reached and (
                candle.high >= signal["take_profit_2"]
                if side == "long"
                else candle.low <= signal["take_profit_2"]
            )
            if tp2_hit or (not tp1_reached and tp1_hit and (
                candle.high >= signal["take_profit_2"]
                if side == "long" else candle.low <= signal["take_profit_2"]
            )):
                signal.setdefault("tp1_alcanzado_en", as_utc(candle.close_time).isoformat())
                legs = [
                    {"fraction": close_fraction, "price": signal["take_profit_1"], "reason": "tp1"},
                    {"fraction": 1 - close_fraction, "price": signal["take_profit_2"], "reason": "tp2"},
                ]
                _close_signal(
                    storage, signal, candle, legs, "tp2", execution_config,
                    funding_collector, candles[candles["open_time"] <= candle.open_time],
                )
                break
            if not tp1_reached and tp1_hit:
                tp1_reached = True
                signal["tp1_alcanzado_en"] = as_utc(candle.close_time).isoformat()
                signal["estado"] = "parcial"
                storage.update_signal(
                    signal["id"],
                    {
                        "estado": "parcial",
                        "tp1_alcanzado_en": signal["tp1_alcanzado_en"],
                        "porcentaje_cerrado": round(close_fraction * 100, 2),
                        "stop_actual": signal["entrada_sugerida"],
                    },
                )
        else:
            if len(candles) >= max_bars:
                candle = candles.iloc[max_bars - 1]
                legs = []
                if tp1_reached:
                    legs.append(
                        {"fraction": close_fraction, "price": signal["take_profit_1"], "reason": "tp1"}
                    )
                legs.append(
                    {
                        "fraction": 1 - close_fraction if tp1_reached else 1.0,
                        "price": float(candle["close"]),
                        "reason": "time_stop",
                    }
                )
                _close_signal(
                    storage, signal, candle, legs, "time_stop", execution_config,
                    funding_collector, candles.iloc[:max_bars],
                )


def reprice_legacy_settled_signals(
    storage: Storage,
    symbol: str,
    price_frame: Any,
    execution_config: dict[str, Any],
    risk_config: dict[str, Any],
    funding_collector: BinanceFuturesCollector | None = None,
) -> None:
    """Backfill net Binance execution costs into previously closed signals."""
    candidates = [
        item
        for item in storage.list_signals()
        if item.get("activo") == symbol
        and item.get("resultado_r") is not None
        and item.get("pnl_neto_usd") is None
    ]
    for original in candidates:
        signal = _legacy_execution_fields(original, execution_config, risk_config)
        opened_at = as_utc(signal.get("abierta_en", signal["timestamp"]))
        candles = price_frame[price_frame["open_time"] >= opened_at].copy()
        for candle in candles.itertuples():
            side = signal["tipo"]
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
            if stop_hit or target_hit:
                reason = "stop_loss" if stop_hit else "tp1_legacy"
                price = signal["stop_loss"] if stop_hit else signal["take_profit_1"]
                _close_signal(
                    storage,
                    signal,
                    candle,
                    [{"fraction": 1.0, "price": price, "reason": reason}],
                    reason,
                    execution_config,
                    funding_collector,
                    candles[candles["open_time"] <= candle.open_time],
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
    futures_collector = BinanceFuturesCollector(**kwargs)
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
    backtests: dict[str, Any] = {} if backtest else read_previous_backtests(output_dir)
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
        futures_book, futures_status = safe_collect(
            f"Binance Futures execution {symbol}",
            lambda s=symbol: futures_collector.book_ticker(s),
        )
        statuses.append(futures_status)
        if not frames:
            continue
        execution_market_price = float(
            (futures_book or {}).get("mid_price")
            or (ticker or {}).get("price")
            or frames[next(iter(frames))].iloc[-1]["close"]
        )
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
        settlement_tf = "15m" if "15m" in frames else chart_tf
        reprice_legacy_settled_signals(
            storage,
            symbol,
            frames[settlement_tf],
            config["execution"],
            config["risk"],
            futures_collector,
        )
        settle_open_signals(
            storage,
            symbol,
            frames[settlement_tf],
            config["execution"],
            config["risk"],
            futures_collector,
        )
        max_open = int(config["risk"]["max_open_signals_per_asset"])
        active = [
            item
            for item in storage.list_signals()
            if item.get("estado") in {"pendiente", "abierta", "parcial"}
        ]
        portfolio_risk = sum(float(item.get("capital_en_riesgo", 0)) for item in active)
        portfolio_cap = (
            float(config["risk"]["capital_usd"])
            * float(config["risk"]["max_portfolio_risk_pct"])
            / 100
        )
        if len(storage.open_for_asset(symbol)) < max_open and portfolio_risk < portfolio_cap:
            for timeframe in config["signal_timeframes"]:
                if timeframe not in frames:
                    continue
                if _cooldown_active(
                    storage.list_signals(),
                    symbol,
                    timeframe,
                    int(config["risk"]["cooldown_bars_after_loss"]),
                ):
                    diagnostics.append(
                        {"symbol": symbol, "timeframe": timeframe, "status": "cooldown_after_loss"}
                    )
                    continue
                signal, detail = evaluate(
                    symbol,
                    timeframe,
                    frames,
                    context,
                    config["risk"],
                    market_price=execution_market_price,
                )
                diagnostics.append(detail)
                if signal:
                    signal = prepare_live_execution(
                        signal,
                        market_price=execution_market_price,
                        order_book=futures_book or order_book,
                        config=config["execution"],
                    )
                    if storage.save_signal(signal):
                        new_signals.append(signal)
                        # Re-evaluate the per-asset/global cap before considering
                        # another timeframe in this same run.
                        break
        if backtest and "1h" in frames:
            backtests[symbol] = run_backtest(
                frames,
                config["risk"]["minimum_rr"],
                symbol=symbol,
                risk_config=config["risk"],
                execution_config=config["execution"],
            )

    signals = storage.list_signals()
    settled = [signal for signal in signals if signal["resultado_r"] is not None]
    chronological = list(reversed(settled))
    results = [float(signal["resultado_r"]) for signal in chronological]
    gross_results = [
        float(signal.get("resultado_bruto_r", signal["resultado_r"]))
        for signal in chronological
    ]
    equity = [0.0]
    for result in results:
        equity.append(round(equity[-1] + result, 3))
    peak, max_drawdown = 0.0, 0.0
    for value in equity:
        peak = max(peak, value)
        max_drawdown = max(max_drawdown, peak - value)
    wins = [result for result in results if result > 0]
    losses = [result for result in results if result < 0]
    gross_equity = [0.0]
    usd_equity = [0.0]
    for signal, gross_result in zip(chronological, gross_results):
        gross_equity.append(round(gross_equity[-1] + gross_result, 3))
        usd_equity.append(round(usd_equity[-1] + float(signal.get("pnl_neto_usd", 0)), 2))
    total_costs = sum(float(signal.get("costes_totales_usd", 0)) for signal in settled)
    total_net_pnl = sum(float(signal.get("pnl_neto_usd", 0)) for signal in settled)
    profit_factor = sum(wins) / abs(sum(losses)) if losses else (999 if wins else 0)
    performance = {
        "total_signals": len(signals),
        "settled_signals": len(settled),
        "win_rate": round(len(wins) / len(results) * 100, 2) if results else 0,
        "win_rate_95ci": _wilson_interval(len(wins), len(results)),
        "average_r": round(sum(results) / len(results), 3) if results else 0,
        "expectancy": round(sum(results) / len(results), 3) if results else 0,
        "max_drawdown_r": round(max_drawdown, 3),
        "profit_factor": round(profit_factor, 3),
        "total_costs_usd": round(total_costs, 2),
        "net_pnl_usd": round(total_net_pnl, 2),
        "equity_curve": equity,
        "gross_equity_curve": gross_equity,
        "equity_curve_usd": usd_equity,
        "sample_status": "insuficiente" if len(results) < 30 else "preliminar" if len(results) < 100 else "robusta",
        "execution_model": config["execution"],
        "by_asset": _group_performance(settled, "activo"),
        "by_timeframe": _group_performance(settled, "timeframe"),
        "by_side": _group_performance(settled, "tipo"),
        "by_exit_reason": _group_performance(settled, "motivo_salida"),
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
