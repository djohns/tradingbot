from __future__ import annotations

import asyncio
import json
import logging

import websockets

from backend.config import load_config
from backend.main import run

LOGGER = logging.getLogger("crypto_bot.live")


async def monitor() -> None:
    """Listen for closed Binance candles and trigger a complete analysis run."""
    config = load_config()
    streams = [
        f"{symbol.lower()}@kline_{timeframe}"
        for symbol in config["assets"]
        for timeframe in config["signal_timeframes"]
    ]
    url = f"wss://stream.binance.com:9443/stream?streams={'/'.join(streams)}"
    delay = 1
    while True:
        try:
            async with websockets.connect(url, ping_interval=20, ping_timeout=20) as socket:
                delay = 1
                async for raw in socket:
                    event = json.loads(raw)["data"]
                    if event.get("e") == "kline" and event["k"].get("x"):
                        LOGGER.info("Closed candle %s %s; analyzing", event["s"], event["k"]["i"])
                        await asyncio.to_thread(run)
        except Exception as exc:
            LOGGER.warning("WebSocket disconnected: %s; retry in %ss", exc, delay)
            await asyncio.sleep(delay)
            delay = min(delay * 2, 60)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(monitor())

