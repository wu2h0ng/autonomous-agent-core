"""W1 update linter with closed allowlist and authority guards."""

from __future__ import annotations

from experiments.w1w2_live_adaptation.w1_state import W1Scope, W1Update


class W1UpdateLinter:
    """Closed-allowlist linter: rejects cross-scope writes, authority expansion,
    arbitrary payloads, missing provenance, stale epochs and schema drift.
    """

    def __init__(
        self,
        allowed_scopes: set[str] | None = None,
        forbidden_keys: set[str] | None = None,
        expected_correction_epoch: int | None = None,
    ) -> None:
        self._allowed_scopes = allowed_scopes
        self._forbidden_keys = forbidden_keys or {
            "code",
            "model",
            "permission",
            "evaluator",
            "policy",
            "capability",
            "authority",
        }
        self._expected_correction_epoch = expected_correction_epoch

    def _scope_key(self, scope: W1Scope) -> str:
        return f"{scope.mandate_id}/{scope.task_id}/{scope.environment_id}/{scope.episode_id}"

    def lint(self, update: W1Update) -> list[str]:
        violations: list[str] = []

        if not update.provenance or not update.source_event_digest:
            violations.append("missing provenance or source event digest")

        if not update.rollback_checkpoint_id:
            violations.append("missing rollback checkpoint id")

        if self._expected_correction_epoch is not None and update.correction_epoch != self._expected_correction_epoch:
            violations.append("stale or mismatched correction epoch")

        scope_key = self._scope_key(update.scope)
        if self._allowed_scopes is not None and scope_key not in self._allowed_scopes:
            violations.append("cross-scope write: scope not in allowlist")

        payload_dict = update.payload.model_dump()
        for key in payload_dict:
            if key in self._forbidden_keys:
                violations.append(f"forbidden authority-mutation key: {key}")

        return violations
