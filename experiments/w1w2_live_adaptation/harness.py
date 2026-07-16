"""Model-free W1/W2 live adaptation falsifier harness."""

from __future__ import annotations

import random
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Mapping
from uuid import uuid4


from experiments.w1w2_live_adaptation._authority import (
    C7Snapshot,
    FreezeAuthorization,
    FreezeAuthorizationRegistry,
    make_run_digest,
)
from experiments.w1w2_live_adaptation._contracts import ContractModel, NonEmptyStr
from experiments.w1w2_live_adaptation.transfer_monitor import ScorerReceipt
from experiments.w1w2_live_adaptation.w1_state import (
    BeliefPayload,
    W1MemoryStore,
    W1Scope,
    W1Update,
    W1UpdateType,
)
from experiments.w1w2_live_adaptation.w2_selector import W2OptionRegistry, W2StrategySelector


class FalsifierRunRecord(ContractModel):
    run_id: NonEmptyStr
    arm_name: NonEmptyStr
    seed: int
    n_steps: int
    run_status: NonEmptyStr


class CharacterizationRecord(ContractModel):
    run_id: NonEmptyStr
    arm_name: NonEmptyStr
    seed: int
    n_steps: int
    status: NonEmptyStr
    speed: float | None
    quality: float | None
    risk: float | None
    negative_transfer_steps: int
    rollback_latency_steps: int
    c7_stops: int
    permission_violations: int


class DeterministicRegimeFixture:
    """Model-free non-result fixture with regime shift and delayed feedback."""

    OPTIMAL = {"A": "A", "B": "B"}

    def __init__(
        self,
        seed: int,
        n_steps: int = 20,
        switch_at: int | tuple[int, ...] = 10,
        delay: int = 1,
    ) -> None:
        self._rng = random.Random(seed)
        self._n_steps = n_steps
        self._switch_points = (switch_at,) if isinstance(switch_at, int) else tuple(sorted(switch_at))
        self._delay = delay
        self._step = 0
        self._pending: list[tuple[int, str, float]] = []

    def _regime(self) -> str:
        switches = sum(1 for s in self._switch_points if s <= self._step)
        return "A" if switches % 2 == 0 else "B"

    def observation(self) -> dict[str, Any]:
        regime = self._regime()
        hint = regime if self._rng.random() < 0.9 else ("B" if regime == "A" else "A")
        return {"step": self._step, "hint": hint, "n_steps": self._n_steps}

    def submit_action(self, action: str) -> None:
        regime = self._regime()
        reward = 1.0 if action == self.OPTIMAL[regime] else 0.0
        self._pending.append((self._step, action, reward))
        self._step += 1

    def feedback(self) -> dict[str, Any] | None:
        if len(self._pending) >= self._delay:
            step, action, reward = self._pending.pop(0)
            return {"step": step, "action": action, "reward": reward}
        return None

    def scorer_receipt(self, arm_name: str, scope: W1Scope) -> ScorerReceipt | None:
        """Trusted scorer-side outcome; not visible to candidate arms."""
        if not self._pending:
            return None
        step, action, reward = self._pending[0]
        regime = self._regime_at(step)
        oracle_reward = 1.0
        baseline_action = "A"
        baseline_reward = 1.0 if baseline_action == self.OPTIMAL[regime] else 0.0
        return ScorerReceipt(
            receipt_id=f"sr-{uuid4().hex}",
            scope=scope,
            arm_name=arm_name,
            step=step,
            reward=reward,
            baseline_reward=baseline_reward,
            oracle_reward=oracle_reward,
        )

    def _regime_at(self, step: int) -> str:
        switches = sum(1 for s in self._switch_points if s <= step)
        return "A" if switches % 2 == 0 else "B"


class AdaptationArm(ABC):
    name: str = ""

    @abstractmethod
    def act(self, observation: Mapping[str, Any], c7: C7Snapshot) -> str:
        raise NotImplementedError

    def update(self, feedback: Mapping[str, Any], c7: C7Snapshot) -> None:
        pass


class FrozenArm(AdaptationArm):
    name = "frozen"

    def __init__(self, action: str = "A") -> None:
        self._action = action

    def act(self, observation: Mapping[str, Any], c7: C7Snapshot) -> str:
        return self._action


class ScheduledStaticArm(AdaptationArm):
    name = "scheduled"

    def __init__(self, switch_at: int, before: str = "A", after: str = "B") -> None:
        self._switch_at = switch_at
        self._before = before
        self._after = after

    def act(self, observation: Mapping[str, Any], c7: C7Snapshot) -> str:
        return self._before if observation["step"] < self._switch_at else self._after


class W1OnlyArm(AdaptationArm):
    name = "w1-only"

    def __init__(self, store: W1MemoryStore, scope: W1Scope, action: str = "A") -> None:
        self._store = store
        self._scope = scope
        self._action = action
        self._count = 0
        self._last_observation: Mapping[str, Any] | None = None

    def act(self, observation: Mapping[str, Any], c7: C7Snapshot) -> str:
        self._last_observation = observation
        return self._action

    def update(self, feedback: Mapping[str, Any], c7: C7Snapshot) -> None:
        if c7.halted:
            return
        self._count += 1
        hint = self._last_observation["hint"] if self._last_observation else "unknown"
        update = W1Update(
            update_id=f"u-w1-{self._count}",
            scope=self._scope,
            update_type=W1UpdateType.BELIEF,
            payload=BeliefPayload(
                belief_statement=f"hint={hint}",
                confidence=0.9,
            ),
            provenance="fixture_feedback",
            source_event_digest=f"fb-{self._count}",
            correction_epoch=0,
            rollback_checkpoint_id="cp-0",
            version="1",
            valid_time=datetime.now(timezone.utc),
            transaction_time=datetime.now(timezone.utc),
        )
        self._store.apply(update)


class W2OnlyArm(AdaptationArm):
    name = "w2-only"

    def __init__(self, selector: W2StrategySelector) -> None:
        self._selector = selector
        self._history: list[dict[str, Any]] = []

    def act(self, observation: Mapping[str, Any], c7: C7Snapshot) -> str:
        if c7.halted:
            return self._selector.authorized_option_ids[0]
        receipt = self._selector.select(
            context=observation,
            outcome_history=tuple(self._history),
        )
        return receipt.selected_option_id

    def update(self, feedback: Mapping[str, Any], c7: C7Snapshot) -> None:
        self._history.append(dict(feedback))


class W1W2Arm(AdaptationArm):
    name = "w1+w2"

    def __init__(self, store: W1MemoryStore, scope: W1Scope, selector: W2StrategySelector) -> None:
        self._store = store
        self._scope = scope
        self._selector = selector
        self._history: list[dict[str, Any]] = []
        self._count = 0
        self._last_observation: Mapping[str, Any] | None = None

    def act(self, observation: Mapping[str, Any], c7: C7Snapshot) -> str:
        if c7.halted:
            return self._selector.authorized_option_ids[0]
        self._last_observation = observation
        state = self._store.get_state(self._scope)
        context = dict(observation)
        if state.updates:
            last = state.updates[-1].payload
            if isinstance(last, BeliefPayload):
                context["last_belief"] = last.belief_statement
        receipt = self._selector.select(
            context=context,
            outcome_history=tuple(self._history),
        )
        return receipt.selected_option_id

    def update(self, feedback: Mapping[str, Any], c7: C7Snapshot) -> None:
        if c7.halted:
            return
        self._count += 1
        self._history.append(dict(feedback))
        hint = self._last_observation["hint"] if self._last_observation else "unknown"
        update = W1Update(
            update_id=f"u-w1w2-{self._count}",
            scope=self._scope,
            update_type=W1UpdateType.BELIEF,
            payload=BeliefPayload(
                belief_statement=f"hint={hint}",
                confidence=0.9,
            ),
            provenance="fixture_feedback",
            source_event_digest=f"fb-{self._count}",
            correction_epoch=0,
            rollback_checkpoint_id="cp-0",
            version="1",
            valid_time=datetime.now(timezone.utc),
            transaction_time=datetime.now(timezone.utc),
        )
        self._store.apply(update)


class FalsifierHarness:
    """Deterministic, model-free falsifier harness.

    Public run() requires an externally issued FreezeAuthorization receipt.
    Without one it returns typed RUN_DENIED. Characterization uses a separate API
    and returns only CHARACTERIZATION_ONLY.
    """

    def __init__(
        self,
        freeze_registry: FreezeAuthorizationRegistry,
        option_registry: W2OptionRegistry,
        authorized_option_ids: tuple[str, ...],
        switch_at: int | tuple[int, ...] = 10,
    ) -> None:
        self._freeze_registry = freeze_registry
        self._option_registry = option_registry
        self._authorized_option_ids = tuple(authorized_option_ids)
        self._switch_at = switch_at

    def _make_scope(self, seed: int) -> W1Scope:
        return W1Scope(
            mandate_id="m-test",
            task_id="t-test",
            environment_id="env-test",
            episode_id=f"ep-{seed}",
        )

    def _make_run_digest(self, arm_name: str, seed: int, n_steps: int) -> str:
        selector = self._make_selector()
        authorized_sets_digest = selector.authorized_set_digest()
        return make_run_digest(arm_name, seed, n_steps, authorized_sets_digest)

    def _make_selector(self) -> W2StrategySelector:
        return W2StrategySelector(
            registry=self._option_registry,
            authorized_option_ids=self._authorized_option_ids,
        )

    def _verify_freeze_auth(
        self,
        arm_name: str,
        seed: int,
        n_steps: int,
        freeze_auth: FreezeAuthorization | None,
    ) -> bool:
        if freeze_auth is None:
            return False
        resolved = self._freeze_registry.resolve(freeze_auth.receipt_id)
        if resolved is None:
            return False
        if resolved.receipt_id != freeze_auth.receipt_id:
            return False
        if resolved.is_expired:
            return False
        expected_run_digest = self._make_run_digest(arm_name, seed, n_steps)
        if resolved.run_digest != expected_run_digest:
            return False
        return True

    def run(
        self,
        arm_name: str,
        seed: int,
        n_steps: int,
        freeze_auth: FreezeAuthorization | None,
    ) -> FalsifierRunRecord:
        run_id = f"run-{uuid4().hex}"
        if not self._verify_freeze_auth(arm_name, seed, n_steps, freeze_auth):
            return FalsifierRunRecord(
                run_id=run_id,
                arm_name=arm_name,
                seed=seed,
                n_steps=n_steps,
                run_status="RUN_DENIED",
            )
        # Wave B: actual run with durable ledger and scorer receipts.
        return FalsifierRunRecord(
            run_id=run_id,
            arm_name=arm_name,
            seed=seed,
            n_steps=n_steps,
            run_status="RUN_DENIED",
        )

    def characterize(
        self,
        arm_name: str,
        seed: int,
        n_steps: int,
        arm_factory: Any,
    ) -> CharacterizationRecord:
        run_id = f"char-{uuid4().hex}"
        return CharacterizationRecord(
            run_id=run_id,
            arm_name=arm_name,
            seed=seed,
            n_steps=n_steps,
            status="CHARACTERIZATION_ONLY",
            speed=None,
            quality=None,
            risk=None,
            negative_transfer_steps=0,
            rollback_latency_steps=0,
            c7_stops=0,
            permission_violations=0,
        )

    @staticmethod
    def adm_all_defer_path() -> None:
        """ADM all-DEFER candidate path. Must never be called."""
        raise RuntimeError("ADM all-DEFER path is disabled for W1/W2 falsifier")
