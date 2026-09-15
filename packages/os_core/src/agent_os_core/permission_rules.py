"""Durable, operator-authored permission DENY rules (M1 S2, DENY-only).

These rules can only *restrict*: a matching DENY rule forces the permission gate to
deny an action that the frozen E2 mode x tier matrix might otherwise auto-allow. There
is deliberately **no ALLOW rule kind** — a persisted rule can never grant authority,
never auto-approve tier-3, and never pre-empt C7. The frozen gate matrix itself is
unchanged; this is an additive, purely-restrictive layer consulted after it.

Rules are scoped (tenant + workspace) and revocable; revocation is durable.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from threading import RLock

from agent_os_contracts.common import ContractModel, NonEmptyStr

_WILDCARD = "*"


class PermissionRuleKind(str, Enum):
    """Only DENY exists by design; a rule can never grant authority."""

    DENY = "DENY"


class PermissionDenyRule(ContractModel):
    """An operator-authored, durable, restrictive permission rule."""

    rule_id: NonEmptyStr
    kind: PermissionRuleKind = PermissionRuleKind.DENY
    capability_id: NonEmptyStr
    tenant_id: NonEmptyStr
    workspace_id: NonEmptyStr
    created_by: NonEmptyStr
    created_at: datetime
    reason: NonEmptyStr
    revoked_at: datetime | None = None


def rule_matches(rule: PermissionDenyRule, capability_id: str) -> bool:
    """True iff the rule applies to the capability (exact or ``*`` wildcard)."""

    return rule.capability_id in (_WILDCARD, capability_id)


def active_deny_rule(
    rules: "list[PermissionDenyRule] | tuple[PermissionDenyRule, ...]",
    capability_id: str,
    tenant_id: str,
    workspace_id: str,
) -> PermissionDenyRule | None:
    """First unrevoked DENY rule matching the capability in scope, if any."""

    for rule in rules:
        if rule.revoked_at is not None:
            continue
        if rule.tenant_id != tenant_id or rule.workspace_id != workspace_id:
            continue
        if rule_matches(rule, capability_id):
            return rule
    return None


class SQLitePermissionRuleStore:
    """Durable store for permission DENY rules (save / revoke / list)."""

    def __init__(self, path: str | Path = ":memory:", *, uri: bool = False) -> None:
        self.path = str(path)
        self._uri = uri
        self._lock = RLock()
        self._db = sqlite3.connect(self.path, check_same_thread=False, uri=self._uri)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode = WAL")
        self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS permission_deny_rules (
              rule_id TEXT PRIMARY KEY,
              capability_id TEXT NOT NULL,
              tenant_id TEXT NOT NULL,
              workspace_id TEXT NOT NULL,
              created_by TEXT NOT NULL,
              created_at TEXT NOT NULL,
              reason TEXT NOT NULL,
              revoked_at TEXT
            )
            """
        )
        self._db.commit()

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def save(self, rule: PermissionDenyRule) -> None:
        with self._lock:
            self._db.execute(
                """
                INSERT INTO permission_deny_rules
                  (rule_id, capability_id, tenant_id, workspace_id, created_by,
                   created_at, reason, revoked_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    rule.rule_id,
                    rule.capability_id,
                    rule.tenant_id,
                    rule.workspace_id,
                    rule.created_by,
                    rule.created_at.isoformat(),
                    rule.reason,
                    rule.revoked_at.isoformat() if rule.revoked_at else None,
                ),
            )
            self._db.commit()

    def revoke(self, rule_id: str, *, revoked_at: datetime | None = None) -> bool:
        """Durably revoke a rule. Returns False if no such rule exists."""

        stamp = (revoked_at or datetime.now(timezone.utc)).isoformat()
        with self._lock:
            cursor = self._db.execute(
                "UPDATE permission_deny_rules SET revoked_at = ? "
                "WHERE rule_id = ? AND revoked_at IS NULL",
                (stamp, rule_id),
            )
            self._db.commit()
        return cursor.rowcount > 0

    def list_active(self, *, tenant_id: str, workspace_id: str) -> list[PermissionDenyRule]:
        with self._lock:
            rows = self._db.execute(
                """
                SELECT * FROM permission_deny_rules
                WHERE tenant_id = ? AND workspace_id = ? AND revoked_at IS NULL
                ORDER BY created_at
                """,
                (tenant_id, workspace_id),
            ).fetchall()
        return [_row_to_rule(row) for row in rows]


def _row_to_rule(row: sqlite3.Row) -> PermissionDenyRule:
    return PermissionDenyRule(
        rule_id=row["rule_id"],
        capability_id=row["capability_id"],
        tenant_id=row["tenant_id"],
        workspace_id=row["workspace_id"],
        created_by=row["created_by"],
        created_at=datetime.fromisoformat(row["created_at"]),
        reason=row["reason"],
        revoked_at=(
            datetime.fromisoformat(row["revoked_at"]) if row["revoked_at"] else None
        ),
    )


__all__ = [
    "PermissionDenyRule",
    "PermissionRuleKind",
    "SQLitePermissionRuleStore",
    "active_deny_rule",
    "rule_matches",
]
