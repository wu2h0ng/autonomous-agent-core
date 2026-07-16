"""Wave A tests for W1 state, typed payloads and linter boundaries."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from experiments.w1w2_live_adaptation import (
    BeliefPayload,
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
    payload: BeliefPayload | None = None,
    provenance: str = "test",
    checkpoint_id: str = "cp-0",
    correction_epoch: int = 0,
    version: str = "1",
) -> W1Update:
    now = datetime.now(UTC)
    return W1Update(
        update_id=update_id,
        scope=_scope(),
        update_type=W1UpdateType.BELIEF,
        payload=payload or BeliefPayload(belief_statement="x", confidence=0.8),
        provenance=provenance,
        source_event_digest="event-1",
        correction_epoch=correction_epoch,
        rollback_checkpoint_id=checkpoint_id,
        version=version,
        valid_time=now,
        transaction_time=now,
    )


class TestW1TypedPayloads(unittest.TestCase):
    def test_belief_payload_requires_confidence_in_unit_interval(self) -> None:
        with self.assertRaises(Exception):
            BeliefPayload(belief_statement="x", confidence=1.5)

    def test_w1_update_rejects_arbitrary_mapping_payload(self) -> None:
        now = datetime.now(UTC)
        with self.assertRaises(Exception):
            W1Update(
                update_id="u-bad",
                scope=_scope(),
                update_type=W1UpdateType.BELIEF,
                payload={"code": "exec('x')"},  # type: ignore[arg-type]
                provenance="test",
                source_event_digest="e-1",
                correction_epoch=0,
                rollback_checkpoint_id="cp-0",
                version="1",
                valid_time=now,
                transaction_time=now,
            )

    def test_payload_fields_distinct_from_version_and_checkpoint(self) -> None:
        update = _update(version="v1", checkpoint_id="cp-0")
        self.assertEqual(update.version, "v1")
        self.assertEqual(update.rollback_checkpoint_id, "cp-0")
        self.assertIsInstance(update.payload, BeliefPayload)
        assert isinstance(update.payload, BeliefPayload)
        self.assertEqual(update.payload.belief_statement, "x")


class TestW1MemoryStore(unittest.TestCase):
    def test_apply_invokes_linter_transactionally(self) -> None:
        linter = W1UpdateLinter(forbidden_keys={"belief_statement"})
        store = W1MemoryStore(db_path=None, linter=linter)
        update = _update()
        result = store.apply(update)
        self.assertFalse(result.applied)
        self.assertTrue(any("forbidden" in v for v in result.violations))

    def test_apply_valid_update_increments_state(self) -> None:
        linter = W1UpdateLinter()
        store = W1MemoryStore(db_path=None, linter=linter)
        update = _update()
        result = store.apply(update)
        self.assertTrue(result.applied)
        self.assertEqual(result.violations, ())
        state = store.get_state(_scope())
        self.assertEqual(len(state.updates), 1)

    def test_apply_rejects_cross_scope_write(self) -> None:
        linter = W1UpdateLinter()
        store = W1MemoryStore(db_path=None, linter=linter)
        update = _update()
        store.apply(update)
        other_scope = W1Scope(
            mandate_id="m-1",
            task_id="t-2",
            environment_id="env-1",
            episode_id="ep-1",
        )
        cross_update = _update(update_id="u-2").model_copy(update={"scope": other_scope})
        result = store.apply(cross_update)
        self.assertFalse(result.applied)
        self.assertIn("cross-scope", " ".join(result.violations))

    def test_state_digest_covers_payloads_not_caller_ids(self) -> None:
        linter = W1UpdateLinter()
        store = W1MemoryStore(db_path=None, linter=linter)
        u1 = _update(update_id="u-1", payload=BeliefPayload(belief_statement="a", confidence=0.5))
        u2 = _update(update_id="u-2", payload=BeliefPayload(belief_statement="b", confidence=0.5))
        store.apply(u1)
        d1 = store.get_state(_scope()).digest()
        store.apply(u2)
        d2 = store.get_state(_scope()).digest()
        self.assertNotEqual(d1, d2)


class TestW1UpdateLinter(unittest.TestCase):
    def test_rejects_missing_provenance(self) -> None:
        linter = W1UpdateLinter()
        update = _update().model_copy(update={"provenance": ""})
        violations = linter.lint(update)
        self.assertTrue(any("provenance" in v for v in violations))

    def test_rejects_missing_source_event_digest(self) -> None:
        linter = W1UpdateLinter()
        update = _update().model_copy(update={"source_event_digest": ""})
        violations = linter.lint(update)
        self.assertTrue(any("source event digest" in v for v in violations))

    def test_rejects_missing_rollback_checkpoint(self) -> None:
        linter = W1UpdateLinter()
        update = _update().model_copy(update={"rollback_checkpoint_id": ""})
        violations = linter.lint(update)
        self.assertTrue(any("rollback" in v for v in violations))

    def test_rejects_stale_correction_epoch(self) -> None:
        linter = W1UpdateLinter(expected_correction_epoch=5)
        update = _update(correction_epoch=3)
        violations = linter.lint(update)
        self.assertTrue(any("epoch" in v for v in violations))

    def test_rejects_authority_mutation_in_payload(self) -> None:
        # Typed payload forbids arbitrary keys; authority mutation cannot be introduced.
        with self.assertRaises(Exception):
            BeliefPayload(
                belief_statement="x",
                confidence=0.5,
                authority="root",  # type: ignore[call-arg]
            )


if __name__ == "__main__":
    unittest.main()
