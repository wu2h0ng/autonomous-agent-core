"""SQLite persistence for frozen PredicateSets.

Follows the same connection/locking pattern as SQLiteTaskEventStore.
PredicateSets are content-addressed (keyed by their SHA256 content digest)
and immutable once written — save is idempotent.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from threading import RLock

from agent_os_contracts import PredicateSet


class SQLitePredicateSetStore:
    """Persistent, content-addressed PredicateSet storage."""

    def __init__(self, path: str | Path = ":memory:", *, uri: bool = False) -> None:
        self.path = str(path)
        self._uri = uri
        self._lock = RLock()
        self._db = sqlite3.connect(
            self.path,
            check_same_thread=False,
            uri=self._uri,
        )
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode = WAL")
        self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS predicate_sets (
              content_digest TEXT PRIMARY KEY,
              set_id TEXT NOT NULL,
              contract_id TEXT NOT NULL,
              task_id TEXT NOT NULL,
              tenant_id TEXT NOT NULL,
              workspace_id TEXT NOT NULL,
              predicate_count INTEGER NOT NULL,
              payload_json TEXT NOT NULL,
              created_at TEXT NOT NULL
            )
            """
        )
        self._db.commit()

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def save(self, predicate_set: PredicateSet) -> None:
        """Save a PredicateSet. Idempotent: same digest = no-op."""
        digest = predicate_set.content_key()
        payload = predicate_set.model_dump(mode="json")
        with self._lock:
            self._db.execute(
                """
                INSERT OR IGNORE INTO predicate_sets
                  (content_digest, set_id, contract_id, task_id, tenant_id,
                   workspace_id, predicate_count, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    digest,
                    predicate_set.set_id,
                    predicate_set.contract_id,
                    predicate_set.task_id,
                    predicate_set.tenant_id,
                    predicate_set.workspace_id,
                    len(predicate_set.predicates),
                    json.dumps(payload, ensure_ascii=False, sort_keys=True),
                    predicate_set.frozen_at.isoformat(),
                ),
            )
            self._db.commit()

    def load(self, digest: str) -> PredicateSet | None:
        """Load a PredicateSet by content digest. Returns None if not found."""
        with self._lock:
            row = self._db.execute(
                "SELECT payload_json FROM predicate_sets WHERE content_digest = ?",
                (digest,),
            ).fetchone()
        if row is None:
            return None
        payload = json.loads(row["payload_json"])
        return PredicateSet.model_validate(payload)

    def exists(self, digest: str) -> bool:
        with self._lock:
            row = self._db.execute(
                "SELECT 1 FROM predicate_sets WHERE content_digest = ?",
                (digest,),
            ).fetchone()
        return row is not None
