"""Content-addressed SQLite cache. Reruns of an identical prompt cost zero tokens.

SQLite calls are microseconds and the DB is local, so we stay synchronous rather
than paying thread-hop overhead on every lookup.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any


class ResponseCache:
    _DDL = (
        "CREATE TABLE IF NOT EXISTS responses ("
        "key TEXT PRIMARY KEY, value TEXT NOT NULL, created REAL DEFAULT (unixepoch('subsec'))"
        ") WITHOUT ROWID"
    )

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute(self._DDL)

    @staticmethod
    def key(**parts: Any) -> str:  # noqa: ANN401
        blob = json.dumps(parts, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(blob.encode()).hexdigest()

    def get(self, key: str) -> str | None:
        row = self._conn.execute("SELECT value FROM responses WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None

    def put(self, key: str, value: str) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO responses(key, value) VALUES (?, ?)", (key, value)
        )

    def close(self) -> None:
        self._conn.close()
