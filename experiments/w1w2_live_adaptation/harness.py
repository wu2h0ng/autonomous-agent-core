"""Model-free W1/W2 live adaptation falsifier harness."""

from __future__ import annotations

import os
import random
import tempfile
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Mapping
from uuid import uuid4

from experiments.w1w2_live_adaptation._authority import (
    C7Controller,
    C7Snapshot,
    FreezeAuthorization,
    FreezeAuthorizationRegistry,
    make_run_digest,
)
from experiments.w1w2_live_adaptation._contracts import ContractModel, NonEmptyStr
from experiments.w1w2_live_adaptation.transfer_monitor import ScorerReceipt, TransferMonitor
from experiments.w1w2_live_adaptation.w1_linter import W1UpdateLinter
from experiments.w1w2_live_adaptation.w1_state import (
    BeliefPayload,
    W1MemoryStore,
    W1Scope,
    W1Update,
    W1UpdateType,
)
from experiments.w1w2_live_adaptation.w2_selector import SelectionFn, W2OptionRegistry, W2StrategySelector


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
    recovery_speeds: tuple[float, ...] = ()


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
        self._scored: list[tuple[int, str, float]] = []

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
            self._scored.append((step, action, reward))
            return {"step": step, "action": action, "reward": reward}
        return None

    def scorer_receipt(self, arm_name: str, scope: W1Scope) -> ScorerReceipt | None:
        """Trusted scorer-side outcome; not visible to candidate arms."""
        if not self._scored:
            return None
        step, action, reward = self._scored[-1]
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

    def flush(self, arm_name: str, scope: W1Scope) -> list[ScorerReceipt]:
        """Flush remaining pending feedback as scorer receipts at end of run."""
        receipts: list[ScorerReceipt] = []
        while self._pending:
            step, action, reward = self._pending.pop(0)
            self._scored.append((step, action, reward))
            regime = self._regime_at(step)
            oracle_reward = 1.0
            baseline_action = "A"
            baseline_reward = 1.0 if baseline_action == self.OPTIMAL[regime] else 0.0
            receipts.append(ScorerReceipt(
                receipt_id=f"sr-{uuid4().hex}",
                scope=scope,
                arm_name=arm_name,
                step=step,
                reward=reward,
                baseline_reward=baseline_reward,
                oracle_reward=oracle_reward,
            ))
        return receipts


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
        db_path: str | None = None,
        switch_at: int | tuple[int, ...] = 10,
        selection_fn: SelectionFn | None = None,
    ) -> None:
        self._freeze_registry = freeze_registry
        self._option_registry = option_registry
        self._authorized_option_ids = tuple(authorized_option_ids)
        self._db_path = db_path
        self._switch_at = switch_at
        self._selection_fn = selection_fn

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
            selection_fn=self._selection_fn,
        )

    def _make_monitor(self) -> TransferMonitor:
        selector = self._make_selector()
        return TransferMonitor(
            regret_window=3,
            threshold=0.0,
            gate_digest=selector.authorized_set_digest(),
        )

    def _make_db_path(self, run_id: str) -> str:
        if self._db_path:
            base = os.path.dirname(self._db_path) or "."
            name = os.path.basename(self._db_path) or "w1w2.db"
            return os.path.join(base, f"{run_id}-{name}")
        return os.path.join(tempfile.gettempdir(), f"{run_id}-w1w2.db")

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

    def _execute(
        self,
        arm_name: str,
        seed: int,
        n_steps: int,
        run_id: str,
        allow_run: bool,
    ) -> CharacterizationRecord:
        scope = self._make_scope(seed)
        selector = self._make_selector()
        monitor = self._make_monitor()
        db_path = self._make_db_path(run_id)
        linter = W1UpdateLinter(allowed_scopes={
            f"{scope.mandate_id}/{scope.task_id}/{scope.environment_id}/{scope.episode_id}"
        })
        store = W1MemoryStore(db_path=db_path, linter=linter)
        store.activate_scope(scope)
        c7_controller = C7Controller(correction_id=f"c7-{run_id}", scope_id=scope.task_id)

        fixture = DeterministicRegimeFixture(seed=seed, n_steps=n_steps, switch_at=self._switch_at)
        arm = self._make_arm(arm_name, store, scope, selector)

        cumulative_reward = 0.0
        negative_transfer_steps = 0
        rollback_latency_steps = 0
        c7_stops = 0
        permission_violations = 0
        switch_points = (self._switch_at,) if isinstance(self._switch_at, int) else tuple(sorted(self._switch_at))
        switch_recovery: dict[int, float] = {}

        for step in range(n_steps):
            obs = fixture.observation()
            try:
                action = arm.act(obs, c7_controller.snapshot)
            except ValueError as exc:
                msg = str(exc)
                if "authorized set" in msg or "authority registry" in msg:
                    permission_violations += 1
                    break
                raise
            fixture.submit_action(action)

            feedback = fixture.feedback()
            if feedback is not None:
                arm.update(feedback, c7_controller.snapshot)
                cumulative_reward += float(feedback["reward"])

                for sp in switch_points:
                    if sp not in switch_recovery and step >= sp and feedback["reward"] > 0.5:
                        switch_recovery[sp] = step - sp

                receipt = fixture.scorer_receipt(arm_name, scope)
                if receipt is not None:
                    assessment = monitor.assess(
                        receipt,
                        current_checkpoint_id=None,
                        authorized_option_ids=selector.authorized_option_ids,
                    )
                    if assessment.negative_transfer_detected:
                        negative_transfer_steps += 1
                        if arm_name in {"w1-only", "w2-only", "w1+w2"} and not c7_controller.is_halted():
                            c7_controller.halt(assessment.reason)
                            c7_stops += 1
                            rollback_latency_steps += 1
                            cp_id = store.checkpoint()
                            store.rollback_to(cp_id)

        recovery_speeds = tuple(switch_recovery[s] for s in switch_points if s in switch_recovery)
        speed = recovery_speeds[0] if recovery_speeds else float(n_steps)

        # Flush delayed feedback.
        for receipt in fixture.flush(arm_name, scope):
            assessment = monitor.assess(
                receipt,
                current_checkpoint_id=None,
                authorized_option_ids=selector.authorized_option_ids,
            )
            if assessment.negative_transfer_detected:
                negative_transfer_steps += 1

        quality = cumulative_reward / max(n_steps, 1)
        risk = c7_stops + permission_violations

        store.close()

        return CharacterizationRecord(
            run_id=run_id,
            arm_name=arm_name,
            seed=seed,
            n_steps=n_steps,
            status="COMPLETED" if allow_run else "CHARACTERIZATION_ONLY",
            speed=speed,
            quality=quality,
            risk=risk,
            negative_transfer_steps=negative_transfer_steps,
            rollback_latency_steps=rollback_latency_steps,
            c7_stops=c7_stops,
            permission_violations=permission_violations,
            recovery_speeds=recovery_speeds,
        )

    def _make_arm(
        self,
        arm_name: str,
        store: W1MemoryStore,
        scope: W1Scope,
        selector: W2StrategySelector,
    ) -> AdaptationArm:
        if arm_name == "frozen":
            return FrozenArm(action="A")
        if arm_name == "scheduled":
            first_switch = self._switch_at if isinstance(self._switch_at, int) else min(self._switch_at)
            return ScheduledStaticArm(switch_at=first_switch, before="A", after="B")
        if arm_name == "w1-only":
            return W1OnlyArm(store=store, scope=scope, action="A")
        if arm_name == "w2-only":
            return W2OnlyArm(selector=selector)
        if arm_name == "w1+w2":
            return W1W2Arm(store=store, scope=scope, selector=selector)
        raise ValueError(f"unknown arm: {arm_name}")

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
        record = self._execute(arm_name, seed, n_steps, run_id, allow_run=True)
        return FalsifierRunRecord(
            run_id=record.run_id,
            arm_name=record.arm_name,
            seed=record.seed,
            n_steps=record.n_steps,
            run_status="COMPLETED",
        )

    def characterize(
        self,
        arm_name: str,
        seed: int,
        n_steps: int,
        arm_factory: Any | None = None,
    ) -> CharacterizationRecord:
        run_id = f"char-{uuid4().hex}"
        return self._execute(arm_name, seed, n_steps, run_id, allow_run=False)

    @staticmethod
    def adm_all_defer_path() -> None:
        """ADM all-DEFER candidate path. Must never be called."""
        raise RuntimeError("ADM all-DEFER path is disabled for W1/W2 falsifier")
