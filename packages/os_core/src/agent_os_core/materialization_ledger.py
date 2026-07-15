from __future__ import annotations

import sqlite3
from pathlib import Path
from threading import RLock


class SQLiteAdaptationLedger:
    """Owns one SQLite connection and its in-process transaction lock."""

    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = str(path)
        self.lock = RLock()
        self.connection = sqlite3.connect(self.path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.execute("PRAGMA journal_mode = WAL")
        self._closed = False

    def close(self) -> None:
        with self.lock:
            if not self._closed:
                self.connection.close()
                self._closed = True
