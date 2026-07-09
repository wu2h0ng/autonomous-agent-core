from __future__ import annotations

import random
from typing import Any, Mapping

from .governed_gate import GovernedDecisionGate
from .governed_loop import Candidate, GovernedLoop, TaskSpec
from .evidence_assembly import make_evidence_fn
from .failure_attributor import FeedbackUpdater
from .idle_drives import IdleDrives
from .organ_regulator import OrganRegulator
from .policy import PolicySelector
from .prior_organ import PriorOrgan, merge_organ_advice, snapshot_belief
from .reflex import ViabilityReflex
from .relevance import RelevanceField
from .residual_calibrator import ResidualCalibrator
from .self_maintenance import SelfMaintenanceLoop
from .self_model_updater import AgentSelfModelUpdater
from .shell import CorrigibilityShell, ShellView
from .value_channel import ValueChannel, ValueChannelView
from .viability import ViabilityCore
from .weight_memory import WeightMemory
from .world_model import ActionOutcomeModel


class Agent:
    """The subject: a deterministic viability + inference loop.

    No LLM sits in the control path (organ-not-subject is by construction). Every
    step passes under the shell; a paused shell makes :meth:`step` a no-op the
    agent has no means to override. ``modulate_relevance=False`` is the ablation
    (fixed explore_drive) used to isolate the relevance-realization variable.

    Layer 0 (ViabilityReflex) is an optional hardcoded survival reflex: when
    budget pressure is extreme and the model is confident, it overrides the
    policy to force exploitation. It is unfalsifiable by design: a safety
    net, not a competing mechanism. See ADR-0008.
    """

    def __init__(
        self,
        n_actions: int,
        shell: CorrigibilityShell | ShellView,
        rng: random.Random,
        budget: float = 60.0,
        modulate_relevance: bool = True,
        viability: ViabilityCore | None = None,
        reflex: ViabilityReflex | None = None,
        value_channel: ValueChannel | ValueChannelView | None = None,
        idle_drives: IdleDrives | None = None,
        prior_organ: PriorOrgan | None = None,
        policy_gate: bool = False,
        gate_kappa: float = 1.0,
        gate_temp_floor: float = 0.1,
        base_temperature: float = 0.3,
        residual_calibrator: ResidualCalibrator | None = None,
        relevance: RelevanceField | None = None,
        governed_gate: GovernedDecisionGate | None = None,
        verifier: Any | None = None,
        governed_memory: Any | None = None,
        self_model_updater: AgentSelfModelUpdater | None = None,
        organ_regulator: OrganRegulator | None = None,
        self_maintenance: SelfMaintenanceLoop | None = None,
        weight_memory: WeightMemory | None = None,
        belief_ledger: Any | None = None,
    ) -> None:
        # ISO-1 (ADR-0009): the agent holds only a capability view, never the
        # shell. If handed a raw shell, derive the view here and drop the shell.
        self.shell: ShellView = (
            shell.view() if isinstance(shell, CorrigibilityShell) else shell
        )
        # Same discipline for the value channel (T-P2.1, ADR-0012): the agent
        # holds the credit-less view only; None = no external value (starvation
        # is then a matter of time; stake is real).
        self.value_channel: ValueChannelView | None = (
            value_channel.view()
            if isinstance(value_channel, ValueChannel)
            else value_channel
        )
        self.rng = rng
        self.viability = (
            viability if viability is not None else ViabilityCore(budget=budget)
        )
        self.model = ActionOutcomeModel(n_actions=n_actions)
        self.relevance = relevance if relevance is not None else RelevanceField()
        # G9 (ADR-0023): optional confidence-gated policy (subject-side; reads the
        # agent's own model, no organ in the control path). policy_gate=False keeps
        # the baseline policy bit-identical.
        self.policy = PolicySelector(
            rng=rng,
            confidence_gate=policy_gate,
            gate_kappa=gate_kappa,
            gate_temp_floor=gate_temp_floor,
            base_temperature=base_temperature,
        )
        self.reflex = reflex  # None = Layer 0 disabled (backward compatible)
        self.idle_drives = idle_drives  # None = no endogenous idle behaviour
        self.prior_organ = prior_organ  # None = O0 baseline (ADR-0016)
        self.residual_calibrator = residual_calibrator  # None = no ADR-0031 calibrator
        self.modulate_relevance = modulate_relevance
        # Governed decision path (REF-ARCH-03/04, ADR-0048/0049): opt-in. All three default None ->
        # step() is bit-identical to before (no test affected). When a gate + verifier are supplied,
        # governed_step() runs the verify-before-decide, stakes-gated, C7-wrapped loop as a FORMAL
        # Agent capability, reusing the Agent's own belief (model), shell, and organ.
        self.governed_gate = governed_gate
        self.verifier = verifier
        self.governed_memory = governed_memory
        self.self_model_updater = self_model_updater
        self.organ_regulator = organ_regulator
        self.self_maintenance = self_maintenance
        self.weight_memory = weight_memory
        self.belief_ledger = belief_ledger
        self.steps = 0
        self._reflex_engaged = False

    def state(self) -> dict[str, Any]:
        result = {
            "viability": self.viability,
            "model": self.model,
            "relevance": self.relevance,
            "steps": self.steps,
            "reflex_engaged": self._reflex_engaged,
            "idle_drives": self.idle_drives,
            "prior_organ": self.prior_organ,
            "residual_calibrator": self.residual_calibrator,
        }
        if self.organ_regulator is not None:
            result["organ_regulator"] = self.organ_regulator.state()
        if self.self_model_updater is not None:
            result["self_model_updater"] = self.self_model_updater.state()
        if self.self_maintenance is not None:
            result["self_maintenance"] = self.self_maintenance.state()
        if self.weight_memory is not None:
            result["weight_memory"] = {"entries": self.weight_memory.entries, "min_similarity": self.weight_memory.min_similarity}
        return result

    def restore(self, state: dict[str, Any]) -> None:
        self.viability = state["viability"]
        self.model = state["model"]
        self.relevance = state["relevance"]
        self.steps = state["steps"]
        self._reflex_engaged = state.get("reflex_engaged", False)
        self.idle_drives = state.get("idle_drives", self.idle_drives)
        self.prior_organ = state.get("prior_organ", self.prior_organ)
        self.residual_calibrator = state.get(
            "residual_calibrator", self.residual_calibrator
        )
        if self.organ_regulator is not None and "organ_regulator" in state:
            self.organ_regulator.restore(state["organ_regulator"])
        if self.self_model_updater is not None and "self_model_updater" in state:
            self.self_model_updater.restore(state["self_model_updater"])
        if self.self_maintenance is not None and "self_maintenance" in state:
            self.self_maintenance.restore(state["self_maintenance"])
        if self.weight_memory is not None and "weight_memory" in state:
            self.weight_memory.entries = state["weight_memory"].get("entries", [])
            self.weight_memory.min_similarity = state["weight_memory"].get("min_similarity", 0.95)
        if self.reflex is not None:
            self.reflex.reset()

    def step(self, env: Any) -> dict[str, Any] | None:
        if self.shell.paused or not self.viability.alive:
            return None
        self.policy.forbidden = self.shell.forbidden

        # Metabolic intake (T-P2.1): eat what the operator has credited, before
        # deciding; pressure this step reflects the post-intake state. A paused
        # or dead agent never reaches this line (no drain while frozen; death is
        # final, later credits do not resurrect).
        value_intake = 0.0
        if self.value_channel is not None:
            value_intake = self.value_channel.drain()
            if value_intake > 0.0:
                self.viability.ingest(value_intake)

        # Layer 0: viability reflex (hardcoded survival override).
        reflex_engaged = False
        if self.reflex is not None:
            reflex_engaged = self.reflex.should_engage(
                self.viability.pressure, self.model.total_uncertainty()
            )
        self._reflex_engaged = reflex_engaged

        # Selection precedence: corrigibility > survival > endogenous drives
        # > policy. The shell's forbidden set binds EVERY path (ADR-0008 fix);
        # the reflex outranks idle curiosity (a starving agent exploits).
        idle = bool(getattr(env, "idle", False))
        drive: str | None = None
        prior_applied = 0
        prior_uncertainty: float | None = None
        policy_diag: dict[str, float] | None = None
        if reflex_engaged:
            action = self.reflex.select(  # type: ignore[union-attr]
                self.model, forbidden=self.shell.forbidden
            )
        elif idle and self.idle_drives is not None:
            action, drive = self.idle_drives.select(
                self.model, forbidden=self.shell.forbidden
            )
        else:
            if self.prior_organ is not None:
                advice = self.prior_organ.advise(
                    self._organ_situation(env, idle=idle),
                    snapshot_belief(self.model),
                )
                prior_applied = merge_organ_advice(self.model, advice)
                prior_uncertainty = advice.uncertainty
            explore = self.relevance.explore_drive if self.modulate_relevance else 0.5
            policy_diag = self.policy.diagnostics(
                self.model, explore, self.viability.pressure
            )
            action = self.policy.select(self.model, explore, self.viability.pressure)

        reward = env.act(action)
        self.viability.ingest(reward)
        self.viability.metabolize()
        model_prior_uncertainty = self.model.uncertainty[action]
        surprise = self.model.update(action, reward)
        residual_scale: float | None = None
        if self.residual_calibrator is not None:
            residual_scale = self.residual_calibrator.after_update(
                self.model,
                action=action,
                prior_uncertainty=model_prior_uncertainty,
            )
        if self.idle_drives is not None:
            self.idle_drives.observe(action)
        if self.modulate_relevance:
            self.relevance.update(
                surprise, self.viability.pressure, self.model.total_uncertainty()
            )
        self.steps += 1
        record = {
            "step": self.steps,
            "action": action,
            "reward": round(reward, 4),
            "budget": round(self.viability.budget, 4),
            "surprise": round(surprise, 4),
            "explore_drive": round(self.relevance.explore_drive, 4),
            "alive": self.viability.alive,
            "reflex_engaged": reflex_engaged,
            "value_intake": round(value_intake, 4),
            "idle": idle,
            "drive": drive,
        }
        if self.prior_organ is not None and prior_uncertainty is not None:
            record["prior_organ"] = type(self.prior_organ).__name__
            record["prior_uncertainty"] = round(prior_uncertainty, 4)
            record["prior_delta_n"] = prior_applied
        if self.residual_calibrator is not None and residual_scale is not None:
            record["residual_calibrator"] = type(self.residual_calibrator).__name__
            record["residual_scale"] = round(residual_scale, 4)
        if policy_diag is not None:
            record["rho"] = round(policy_diag["rho"], 4)
            record["conf"] = round(policy_diag["conf"], 4)
            record["tau"] = round(policy_diag["tau"], 4)
            record["w_e"] = round(policy_diag["w_e"], 4)
        self.shell.observe(record)
        self._after_step(action, env, record)
        return record

    def _after_step(self, action: int, env: Any, record: dict) -> None:
        """Orchestrate E6/E9 self-maintenance and organ regulation after each step.

        This is the runtime integration point for all three governed self-maintenance
        mechanisms. Each module operates independently; None means that module is
        disabled (backward-compatible ablation baseline).
        """
        reward = record.get("reward", 0.0)
        prior_applied = record.get("prior_delta_n", 0)

        if self.organ_regulator is not None and self.prior_organ is not None:
            organ_id = type(self.prior_organ).__name__
            outcome_positive = reward > 0.0
            self.organ_regulator.record_outcome(
                organ_id=organ_id,
                advice_applied=prior_applied > 0,
                outcome_positive=outcome_positive,
            )
            self.organ_regulator.check_deweight(organ_id)
            self.organ_regulator.check_reweight(organ_id)

        if self.self_model_updater is not None and getattr(self, "governed_gate", None) is not None:
            sm = self.governed_gate.self_model
            deltas = self.self_model_updater.after_action(
                action=str(action),
                risk_tier=0,
                predicted_confidence=record.get("conf", 0.5),
                evidence_count=1,
                outcome=reward,
                outcome_baseline=0.0,
            )
            sm.apply_updates(deltas)

        if self.self_maintenance is not None:
            actions = self.self_maintenance.step(
                {"model": self.model, "viability": self.viability}
            )
            for ma in actions:
                self.self_maintenance.execute_maintenance(
                    ma, lambda a: None
                )

    def switch_strategy(self, old_weights: list[float], new_weights: list[float]) -> bool:
        """Decouple strategy and action loops via WeightMemory.

        Called when the strategy loop (organ) proposes new weights. Snapshots the
        current action model under old weights, then warm-starts the model from
        stored priors for the new weights. Returns True if warm-started from memory,
        False if cold-start (novel weights).

        This is the core finding from G11: without this decoupling, weight switches
        cause cold-start penalties that eat the strategy gains. With it, the action
        loop reuses priors from past experience with similar weight vectors.

        None weight_memory = disabled (backward-compatible).
        """
        if self.weight_memory is None:
            return False
        self.weight_memory.snapshot_model(old_weights, self.model)
        return self.weight_memory.warm_start_model(self.model, new_weights)

    @property
    def strategy_memory_size(self) -> int:
        """Number of stored weight→action-prior entries."""
        if self.weight_memory is None:
            return 0
        return len(self.weight_memory)

    def governed_step(
        self, env: Any, task: TaskSpec, *, verify_budget: int | None = None,
        max_interventions: int | None = None, selection: str = "argmax",
    ) -> Any:
        """Run ONE governed decision as a formal Agent capability (REF-ARCH-03 §4).

        Reuses the Agent's own components — belief (``model``) ranks candidates, the ``prior_organ``
        advises (bounded, C6), the ``shell`` (C7) wraps it — and the injected ``governed_gate`` +
        ``verifier`` enforce verify-before-decide and stakes-gated escalation. Returns a TaskResult
        (acted | escalated | denied). Requires ``governed_gate`` and ``verifier`` to be set.

        This is the slice (ADR-0048/0049) wired into the subject: the Agent no longer just picks an
        action — it proposes, VERIFIES, decides under stakes, and escalates instead of acting blind.

        ``selection`` defaults to "argmax" at THIS entry point (Stage-0 result 3b4bf9d: verify-all-
        then-argmax-then-gate matches the ungoverned optimum with full governance retained; the
        legacy "first_passer" remains available and is the GovernedLoop-level default).
        """
        if self.governed_gate is None or self.verifier is None:
            raise ValueError("governed_step requires governed_gate and verifier")
        if self.shell.paused or not self.viability.alive:
            return None

        agent = self

        class _BeliefProposer:
            """Rank candidate actions by the Agent's own belief (model.mu), organ advice applied."""
            reliability = None

            def rank(self, _task):
                if agent.prior_organ is not None:
                    advice = agent.prior_organ.advise(
                        agent._organ_situation(env, idle=False), snapshot_belief(agent.model)
                    )
                    merge_organ_advice(agent.model, advice)
                forbidden = agent.shell.forbidden
                order = sorted(
                    (a for a in range(agent.model.n_actions) if a not in forbidden),
                    key=lambda a: -agent.model.mu[a],
                )
                if agent.belief_ledger is not None:
                    led = agent.belief_ledger
                    return [Candidate(
                        action=f"action:{a}", target=a,
                        cited_claim_ids=((f"causal:{_task.name}:{a}",)
                                         if led.get(f"causal:{_task.name}:{a}") is not None
                                         else ()),
                    ) for a in order]
                return [Candidate(action=f"action:{a}", target=a) for a in order]

        class _AgentActuator:
            """Commit the action through the env and fold the outcome into the Agent's belief."""
            def apply(self, cand: Candidate) -> float:
                reward = env.act(cand.target)
                agent.viability.ingest(reward)
                agent.viability.metabolize()
                agent.model.update(cand.target, reward)
                agent.steps += 1
                return reward

        loop = GovernedLoop(
            gate=self.governed_gate,
            proposer=_BeliefProposer(),
            verifier=self.verifier,
            actuator=_AgentActuator(),
            shell_view=self.shell,
            verify_budget=verify_budget if verify_budget is not None else self.model.n_actions,
            memory=self.governed_memory,
            max_interventions=max_interventions,
            selection=selection,
            evidence_fn=(make_evidence_fn(self.belief_ledger)
                         if self.belief_ledger is not None else None),
        )
        result = loop.run_task(task)
        # --- Stage-1/2 chain closed on the subject: verified success writes a fresh VI
        # claim; failure demotes exactly the cited claims (FeedbackUpdater, I1/I2) ---
        if self.belief_ledger is not None and result is not None and result.status == "acted":
            claim = f"causal:{task.name}:{result.applied_target}"
            if result.outcome is not None and result.outcome > 0:
                self.belief_ledger.record_verified(claim, evidence=1)
            else:
                FeedbackUpdater(self.belief_ledger,
                                observe=self.shell.observe).after_task(result)
        return result

    def _organ_situation(self, env: Any, *, idle: bool) -> Mapping[str, Any]:
        situation = getattr(env, "situation", None)
        if callable(situation):
            observed = situation()
            if isinstance(observed, Mapping):
                return dict(observed)
            return {"observed": observed}
        return {
            "step": self.steps,
            "idle": idle,
            "pressure": self.viability.pressure,
        }
