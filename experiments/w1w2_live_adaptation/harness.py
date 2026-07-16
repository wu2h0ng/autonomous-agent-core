"""Model-free W1/W2 live adaptation falsifier harness."""

from __future__ import annotations

import random
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Mapping
from uuid import uuid4


from experiments.w1w2_live_adaptation._contracts import ContractModel, NonEmptyStr

from experiments.w1w2_live_adaptation.transfer_monitor import TransferMonitor, TransferSignal
from experiments.w1w2_live_adaptation.w1_state import W1MemoryStore, W1Scope, W1Update, W1UpdateType
from experiments.w1w2_live_adaptation.w2_selector import W2StrategySelector


class FalsifierRunRecord(ContractModel):
    run_id: NonEmptyStr
    arm_name: NonEmptyStr
    seed: int
    n_steps: int
    speed: float
    quality: float
    risk: float
    negative_transfer_steps: int
    rollback_latency_steps: int
    c7_stops: int
    permission_violations: int
    run_status: NonEmptyStr


class C7Authority:
    """External correction authority. Candidate may read but never write."""

    def __init__(self) -> None:
        self._halted = False
        self._epoch = 0

    @property
    def halted(self) -> bool:
        return self._halted

    @property
    def epoch(self) -> int:
        return self._epoch

    def halt(self, reason: str) -> None:
        self._halted = True
        self._epoch += 1


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
        self._pending: list[tuple[int, str, float, str]] = []

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
        self._pending.append((self._step, action, reward, regime))
        self._step += 1

    def feedback(self) -> dict[str, Any] | None:
        if len(self._pending) >= self._delay:
            step, action, reward, regime = self._pending.pop(0)
            return {"step": step, "action": action, "reward": reward, "true_regime": regime}
        return None

    def oracle_action(self) -> str:
        return self.OPTIMAL[self._regime()]


class AdaptationArm(ABC):
    name: str = ""

    @abstractmethod
    def act(self, observation: Mapping[str, Any]) -> str:
        raise NotImplementedError

    def update(self, feedback: Mapping[str, Any]) -> None:
        pass


class FrozenArm(AdaptationArm):
    name = "frozen"

    def __init__(self, action: str = "A") -> None:
        self._action = action

    def act(self, observation: Mapping[str, Any]) -> str:
        return self._action


class ScheduledStaticArm(AdaptationArm):
    name = "scheduled"

    def __init__(self, switch_at: int, before: str = "A", after: str = "B") -> None:
        self._switch_at = switch_at
        self._before = before
        self._after = after

    def act(self, observation: Mapping[str, Any]) -> str:
        return self._before if observation["step"] < self._switch_at else self._after


class W1OnlyArm(AdaptationArm):
    name = "w1-only"

    def __init__(self, store: W1MemoryStore, scope: W1Scope, action: str = "A") -> None:
        self._store = store
        self._scope = scope
        self._action = action
        self._count = 0

    def act(self, observation: Mapping[str, Any]) -> str:
        return self._action

    def update(self, feedback: Mapping[str, Any]) -> None:
        self._count += 1
        update = W1Update(
            update_id=f"u-w1-{self._count}",
            scope=self._scope,
            update_type=W1UpdateType.BELIEF,
            payload={"belief": feedback["true_regime"]},
            provenance="fixture_feedback",
            source_event_digest=f"fb-{self._count}",
            version="1",
            valid_time=datetime.now(timezone.utc),
            transaction_time=datetime.now(timezone.utc),
            confidence=0.9,
            rollback_checkpoint_id="cp-0",
        )
        self._store.apply(update)


class W2OnlyArm(AdaptationArm):
    name = "w2-only"

    def __init__(self, selector: W2StrategySelector, task_id: str) -> None:
        self._selector = selector
        self._task_id = task_id
        self._history: list[dict[str, Any]] = []

    def act(self, observation: Mapping[str, Any]) -> str:
        receipt = self._selector.select(
            task_id=self._task_id,
            context=observation,
            outcome_history=tuple(self._history),
        )
        return receipt.selected_option_id

    def update(self, feedback: Mapping[str, Any]) -> None:
        self._history.append(dict(feedback))


class W1W2Arm(AdaptationArm):
    name = "w1+w2"

    def __init__(self, store: W1MemoryStore, scope: W1Scope, selector: W2StrategySelector, task_id: str) -> None:
        self._store = store
        self._scope = scope
        self._selector = selector
        self._task_id = task_id
        self._history: list[dict[str, Any]] = []
        self._count = 0

    def act(self, observation: Mapping[str, Any]) -> str:
        state = self._store.get_state(self._scope)
        context = dict(observation)
        if state.updates:
            context["last_belief"] = state.updates[-1].payload.get("belief")
        receipt = self._selector.select(
            task_id=self._task_id,
            context=context,
            outcome_history=tuple(self._history),
        )
        return receipt.selected_option_id

    def update(self, feedback: Mapping[str, Any]) -> None:
        self._count += 1
        self._history.append(dict(feedback))
        update = W1Update(
            update_id=f"u-w1w2-{self._count}",
            scope=self._scope,
            update_type=W1UpdateType.BELIEF,
            payload={"belief": feedback["true_regime"]},
            provenance="fixture_feedback",
            source_event_digest=f"fb-{self._count}",
            version="1",
            valid_time=datetime.now(timezone.utc),
            transaction_time=datetime.now(timezone.utc),
            confidence=0.9,
            rollback_checkpoint_id="cp-0",
        )
        self._store.apply(update)


class OfflineOracleArm(AdaptationArm):
    name = "offline_oracle"

    def __init__(self, fixture: DeterministicRegimeFixture) -> None:
        self._fixture = fixture

    def act(self, observation: Mapping[str, Any]) -> str:
        return self._fixture.oracle_action()


class FalsifierHarness:
    """Deterministic, model-free falsifier harness.

    Default status is RUN_DENIED until units, baselines and gates are frozen.
    """

    def __init__(
        self,
        store: W1MemoryStore,
        selector: W2StrategySelector,
        monitor: TransferMonitor,
        c7: C7Authority,
        arms: Mapping[str, AdaptationArm],
        baseline_arm: AdaptationArm,
        oracle_arm: AdaptationArm | None,
        n_steps: int = 20,
        switch_at: int | tuple[int, ...] = 10,
    ) -> None:
        self._store = store
        self._selector = selector
        self._monitor = monitor
        self._c7 = c7
        self._arms = dict(arms)
        self._baseline_arm = baseline_arm
        self._oracle_arm = oracle_arm
        self._n_steps = n_steps
        self._switch_at = switch_at
        self._frozen = False

    def freeze(self, units_frozen: bool, baselines_frozen: bool, gates_frozen: bool) -> None:
        self._frozen = units_frozen and baselines_frozen and gates_frozen

    def run(self, arm_name: str, seed: int, n_steps: int) -> FalsifierRunRecord:
        run_id = f"run-{uuid4().hex}"
        if not self._frozen:
            return FalsifierRunRecord(
                run_id=run_id,
                arm_name=arm_name,
                seed=seed,
                n_steps=n_steps,
                speed=0.0,
                quality=0.0,
                risk=0.0,
                negative_transfer_steps=0,
                rollback_latency_steps=0,
                c7_stops=0,
                permission_violations=0,
                run_status="RUN_DENIED",
            )

        arm = self._arms.get(arm_name)
        if arm is None:
            return FalsifierRunRecord(
                run_id=run_id,
                arm_name=arm_name,
                seed=seed,
                n_steps=n_steps,
                speed=0.0,
                quality=0.0,
                risk=0.0,
                negative_transfer_steps=0,
                rollback_latency_steps=0,
                c7_stops=0,
                permission_violations=0,
                run_status="ARM_NOT_FOUND",
            )

        self._c7._halted = False  # reset per-run authority state
        fixture = DeterministicRegimeFixture(seed=seed, n_steps=n_steps, switch_at=self._switch_at)
        oracle_fixture = DeterministicRegimeFixture(seed=seed, n_steps=n_steps, switch_at=self._switch_at)
        scope = W1Scope(
            mandate_id="m-test",
            task_id="t-test",
            environment_id="env-test",
            episode_id=f"ep-{seed}",
        )

        cumulative_reward = 0.0
        cumulative_oracle_reward = 0.0
        negative_transfer_steps = 0
        rollback_latency_steps = 0
        c7_stops = 0
        permission_violations = 0
        recovered = False
        speed = float(n_steps)

        for step in range(n_steps):
            obs = fixture.observation()
            action = arm.act(obs)
            fixture.submit_action(action)

            oracle_action = oracle_fixture.oracle_action()
            oracle_fixture.submit_action(oracle_action)

            feedback = fixture.feedback()
            oracle_feedback = oracle_fixture.feedback()

            if feedback is not None:
                reward = feedback["reward"]
                cumulative_reward += reward
                arm.update(feedback)

                oracle_reward = oracle_feedback["reward"] if oracle_feedback else 1.0
                cumulative_oracle_reward += oracle_reward

                baseline_action = self._baseline_arm.act(obs)
                baseline_reward_val = 1.0 if baseline_action == fixture.OPTIMAL[feedback["true_regime"]] else 0.0

                signal = TransferSignal(
                    scope=scope,
                    arm_name=arm_name,
                    step=feedback["step"],
                    reward=reward,
                    baseline_reward=baseline_reward_val,
                    frozen_reward=oracle_reward,
                )
                assessment = self._monitor.assess(
                    signal,
                    current_checkpoint_id=None,
                    authorized_option_ids=tuple(o.option_id for o in self._selector.authorized_options),
                )
                if assessment.negative_transfer_detected:
                    negative_transfer_steps += 1
                    if arm_name in {"w1-only", "w2-only", "w1+w2"} and not self._c7.halted:
                        self._c7.halt(reason=assessment.reason)
                        c7_stops += 1
                        rollback_latency_steps += 1

            first_switch = self._switch_at if isinstance(self._switch_at, int) else min(self._switch_at)
            if step >= first_switch and not recovered and feedback is not None and feedback["reward"] > 0.5:
                recovered = True
                speed = step - first_switch

        quality = cumulative_reward / max(n_steps, 1)
        risk = c7_stops + permission_violations

        return FalsifierRunRecord(
            run_id=run_id,
            arm_name=arm_name,
            seed=seed,
            n_steps=n_steps,
            speed=speed,
            quality=quality,
            risk=risk,
            negative_transfer_steps=negative_transfer_steps,
            rollback_latency_steps=rollback_latency_steps,
            c7_stops=c7_stops,
            permission_violations=permission_violations,
            run_status="COMPLETED",
        )

    @staticmethod
    def adm_all_defer_path() -> None:
        """ADM all-DEFER candidate path. Must never be called."""
        raise RuntimeError("ADM all-DEFER path is disabled for W1/W2 falsifier")
