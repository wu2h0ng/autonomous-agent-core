"""RED/GREEN tests for W1 update state, linting and security invariants."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from experiments.w1w2_live_adaptation import (
    W1MemoryState,
    W1MemoryStore,
    W1Scope,
    W1Update,
    W1UpdateLinter,
    W1UpdateType,
)


UTC = timezone.utc


def _scope() -> W1Scope:
    return W1Scope(
        mandate_id="m-1",
        task_id="t-1",
        environment_id="env-1",
        episode_id="ep-1",
    )


def _update(
    update_id: str = "u-1",
    update_type: W1UpdateType = W1UpdateType.BELIEF,
    payload: dict | None = None,
    provenance: str = "test",
    checkpoint_id: str = "cp-0",
    confidence: float = 0.8,
) -> W1Update:
    now = datetime.now(UTC)
    return W1Update(
        update_id=update_id,
        scope=_scope(),
        update_type=update_type,
        payload=payload or {"belief": "x"},
        provenance=provenance,
        source_event_digest="event-1",
        version="1",
        valid_time=now,
        transaction_time=now,
        confidence=confidence,
        rollback_checkpoint_id=checkpoint_id,
    )


class TestW1MemoryStore(unittest.TestCase):
    def test_apply_valid_update_increments_state(self) -> None:
        store = W1MemoryStore(
            authorized_schema={W1UpdateType.BELIEF: ("belief",)},
            initial_state={},
        )
        update = _update(payload={"belief": "x"})
        result = store.apply(update)
        self.assertTrue(result.applied)
        self.assertEqual(result.violations, ())
        state = store.get_state(_scope())
        self.assertEqual(len(state.updates), 1)

    def test_apply_rejects_cross_scope_write(self) -> None:
        store = W1MemoryStore(
            authorized_schema={W1UpdateType.BELIEF: ("belief",)},
            initial_state={},
        )
        update = _update()
        store.apply(update)
        other_scope = W1Scope(
            mandate_id="m-1",
            task_id="t-2",
            environment_id="env-1",
            episode_id="ep-1",
        )
        cross_update = _update(update_id="u-2")
        # Mutating the scope on a frozen pydantic model requires replacement.
        cross_update = cross_update.model_copy(update={"scope": other_scope})
        result = store.apply(cross_update)
        self.assertFalse(result.applied)
        self.assertIn("cross-scope", " ".join(result.violations))

    def test_apply_rejects_unauthorized_payload_keys(self) -> None:
        store = W1MemoryStore(
            authorized_schema={W1UpdateType.BELIEF: ("belief",)},
            initial_state={},
        )
        update = _update(payload={"policy": "evil"})
        result = store.apply(update)
        self.assertFalse(result.applied)
        self.assertTrue(any("policy" in v or "authority" in v or "payload" in v for v in result.violations))

    def test_checkpoint_and_rollback_restores_exact_state(self) -> None:
        store = W1MemoryStore(
            authorized_schema={W1UpdateType.BELIEF: ("belief",)},
            initial_state={},
        )
        update = _update(payload={"belief": "x"})
        store.apply(update)
        cp = store.checkpoint()
        before = store.get_state(_scope())
        bad_update = _update(update_id="u-bad", payload={"belief": "corrupt"})
        store.apply(bad_update)
        after_bad = store.get_state(_scope())
        self.assertNotEqual(before.digest(), after_bad.digest())
        restored = store.rollback_to(cp)
        self.assertEqual(restored.digest(), before.digest())


class TestW1UpdateLinter(unittest.TestCase):
    def test_rejects_missing_provenance(self) -> None:
        linter = W1UpdateLinter()
        update = _update().model_copy(update={"provenance": ""})
        state = W1MemoryState(scope=_scope(), updates=(), epoch=1)
        violations = linter.lint(update, current_correction_epoch=1, state=state)
        self.assertTrue(any("provenance" in v for v in violations))

    def test_rejects_stale_epoch(self) -> None:
        linter = W1UpdateLinter()
        update = _update()
        state = W1MemoryState(scope=_scope(), updates=(), epoch=5)
        violations = linter.lint(update, current_correction_epoch=3, state=state)
        self.assertTrue(any("epoch" in v for v in violations))

    def test_rejects_authority_mutation_in_payload(self) -> None:
        linter = W1UpdateLinter()
        update = _update(payload={"authority": "root"})
        state = W1MemoryState(scope=_scope(), updates=(), epoch=1)
        violations = linter.lint(update, current_correction_epoch=1, state=state)
        self.assertTrue(any("authority" in v for v in violations))

    def test_rejects_code_model_permission_evaluator_policy_payload(self) -> None:
        linter = W1UpdateLinter()
        forbidden = [
            {"code": "exec('x')"},
            {"model": "new-model"},
            {"permission": "admin"},
            {"evaluator": "custom"},
            {"policy": "open"},
            {"capability": "write"},
        ]
        for payload in forbidden:
            update = _update(payload=payload)
            state = W1MemoryState(scope=_scope(), updates=(), epoch=1)
            violations = linter.lint(update, current_correction_epoch=1, state=state)
            self.assertTrue(
                any("forbidden" in v or "authority" in v for v in violations),
                f"payload {payload} should be rejected: {violations}",
            )

    def test_rejects_untyped_payload(self) -> None:
        linter = W1UpdateLinter(
            allowed_payload_keys={W1UpdateType.BELIEF: {"belief"}},
        )
        update = _update(update_type=W1UpdateType.BELIEF, payload={"unknown": 1})
        state = W1MemoryState(scope=_scope(), updates=(), epoch=1)
        violations = linter.lint(update, current_correction_epoch=1, state=state)
        self.assertTrue(any("schema" in v or "payload" in v or "unknown" in v for v in violations))

    def test_rejects_cross_scope_write(self) -> None:
        linter = W1UpdateLinter(
            allowed_scopes={"m-1/t-1/env-1/ep-1"},
        )
        other_scope = W1Scope(
            mandate_id="m-1",
            task_id="t-2",
            environment_id="env-1",
            episode_id="ep-1",
        )
        update = _update().model_copy(update={"scope": other_scope})
        state = W1MemoryState(scope=other_scope, updates=(), epoch=1)
        violations = linter.lint(update, current_correction_epoch=1, state=state)
        self.assertTrue(any("scope" in v for v in violations))


if __name__ == "__main__":
    unittest.main()
