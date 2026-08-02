from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


class Storage:
    def __init__(self, path: str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS signals (
                id TEXT PRIMARY KEY,
                symbol TEXT NOT NULL,
                timeframe TEXT NOT NULL,
                side TEXT NOT NULL,
                confidence INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                status TEXT NOT NULL,
                result_r REAL,
                payload TEXT NOT NULL
            )
            """
        )
        self.connection.commit()

    def save_signal(self, signal: dict[str, Any]) -> bool:
        cursor = self.connection.execute(
            """
            INSERT OR IGNORE INTO signals
            (id, symbol, timeframe, side, confidence, created_at, status, result_r, payload)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                signal["id"],
                signal["activo"],
                signal["timeframe"],
                signal["tipo"],
                signal["confianza"],
                signal["timestamp"],
                signal["estado"],
                signal["resultado_r"],
                json.dumps(signal, ensure_ascii=False),
            ),
        )
        self.connection.commit()
        return cursor.rowcount > 0

    def hydrate(self, signals: list[dict[str, Any]]) -> int:
        """Restore versioned signal history into an ephemeral Actions database."""
        restored = 0
        for signal in signals:
            if self.save_signal(signal):
                restored += 1
        return restored

    def list_signals(self, limit: int = 250) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            "SELECT payload FROM signals ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [json.loads(row["payload"]) for row in rows]

    def open_for_asset(self, symbol: str) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            """SELECT payload FROM signals
            WHERE symbol = ? AND status IN ('pendiente', 'abierta', 'parcial')""",
            (symbol,),
        ).fetchall()
        return [json.loads(row["payload"]) for row in rows]

    def update_signal(self, signal_id: str, changes: dict[str, Any]) -> None:
        row = self.connection.execute(
            "SELECT payload FROM signals WHERE id = ?", (signal_id,)
        ).fetchone()
        if not row:
            return
        payload = json.loads(row["payload"])
        payload.update(changes)
        self.connection.execute(
            "UPDATE signals SET status = ?, result_r = ?, payload = ? WHERE id = ?",
            (
                payload["estado"],
                payload.get("resultado_r"),
                json.dumps(payload, ensure_ascii=False),
                signal_id,
            ),
        )
        self.connection.commit()

    def settle(
        self,
        signal_id: str,
        status: str,
        result_r: float,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.update_signal(
            signal_id,
            {"estado": status, "resultado_r": result_r, **(details or {})},
        )
