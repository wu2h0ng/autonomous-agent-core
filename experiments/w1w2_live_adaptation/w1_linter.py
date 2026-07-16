"""W1 update linter with closed allowlist and authority guards."""

from __future__ import annotations

from typing import Mapping

from experiments.w1w2_live_adaptation.w1_state import W1MemoryState, W1Scope, W1Update, W1UpdateType


class W1UpdateLinter:
    """Closed-allowlist linter: rejects cross-scope writes, authority expansion,
    arbitrary payloads, missing provenance, stale epochs and schema drift.
    """

    def __init__(
        self,
        allowed_scopes: set[str] | None = None,
        allowed_payload_keys: Mapping[W1UpdateType, set[str]] | None = None,
        forbidden_keys: set[str] | None = None,
    ) -> None:
        self._allowed_scopes = allowed_scopes
        self._allowed_payload_keys = dict(allowed_payload_keys) if allowed_payload_keys else {}
        self._forbidden_keys = forbidden_keys or {
            "code",
            "model",
            "permission",
            "evaluator",
            "policy",
            "capability",
            "authority",
        }

    def _scope_key(self, scope: W1Scope) -> str:
        return f"{scope.mandate_id}/{scope.task_id}/{scope.environment_id}/{scope.episode_id}"

    def lint(
        self,
        update: W1Update,
        current_correction_epoch: int,
        state: W1MemoryState,
    ) -> list[str]:
        violations: list[str] = []

        if not update.provenance or not update.source_event_digest:
            violations.append("missing provenance or source event digest")

        if current_correction_epoch < state.epoch:
            violations.append("stale correction epoch")

        scope_key = self._scope_key(update.scope)
        if self._allowed_scopes is not None and scope_key not in self._allowed_scopes:
            violations.append("cross-scope write: scope not in allowlist")

        for key in update.payload:
            if key in self._forbidden_keys:
                violations.append(f"forbidden authority-mutation key: {key}")

        allowed_keys = self._allowed_payload_keys.get(update.update_type)
        if allowed_keys is not None:
            for key in update.payload:
                if key not in allowed_keys:
                    violations.append(f"schema drift: unknown payload key '{key}'")

        return violations
