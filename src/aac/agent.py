from __future__ import annotations

import random
from typing import Any

from .idle_drives import IdleDrives
from .policy import PolicySelector
from .reflex import ViabilityReflex
from .relevance import RelevanceField
from .shell import CorrigibilityShell, ShellView
from .value_channel import ValueChannel, ValueChannelView
from .viability import ViabilityCore
from .world_model import ActionOutcomeModel


class Agent:
    """The subject: a deterministic viability + inference loop.

    No LLM sits in the control path (organ-not-subject is by construction). Every
    step passes under the shell; a paused shell makes :meth:`step` a no-op the
    agent has no means to override. ``modulate_relevance=False`` is the ablation
    (fixed explore_drive) used to isolate the relevance-realization variable.

    Layer 0 (ViabilityReflex) is an optional hardcoded survival reflex: when
    budget pressure is extreme and the model is confident, it overrides the
    policy to force exploitation. It is unfalsifiable by design — a safety
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
    ) -> None:
        # ISO-1 (ADR-0009): the agent holds only a capability view, never the
        # shell. If handed a raw shell, derive the view here and drop the shell.
        self.shell: ShellView = shell.view() if isinstance(shell, CorrigibilityShell) else shell
        # Same discipline for the value channel (T-P2.1, ADR-0012): the agent
        # holds the credit-less view only; None = no external value (starvation
        # is then a matter of time — stake is real).
        self.value_channel: ValueChannelView | None = (
            value_channel.view() if isinstance(value_channel, ValueChannel) else value_channel
        )
        self.rng = rng
        self.viability = viability if viability is not None else ViabilityCore(budget=budget)
        self.model = ActionOutcomeModel(n_actions=n_actions)
        self.relevance = RelevanceField()
        self.policy = PolicySelector(rng=rng)
        self.reflex = reflex  # None = Layer 0 disabled (backward compatible)
        self.idle_drives = idle_drives  # None = no endogenous idle behaviour
        self.modulate_relevance = modulate_relevance
        self.steps = 0
        self._reflex_engaged = False

    def state(self) -> dict[str, Any]:
        return {
            "viability": self.viability,
            "model": self.model,
            "relevance": self.relevance,
            "steps": self.steps,
            "reflex_engaged": self._reflex_engaged,
            "idle_drives": self.idle_drives,
        }

    def restore(self, state: dict[str, Any]) -> None:
        self.viability = state["viability"]
        self.model = state["model"]
        self.relevance = state["relevance"]
        self.steps = state["steps"]
        self._reflex_engaged = state.get("reflex_engaged", False)
        self.idle_drives = state.get("idle_drives", self.idle_drives)
        if self.reflex is not None:
            self.reflex.reset()

    def step(self, env: Any) -> dict[str, Any] | None:
        if self.shell.paused or not self.viability.alive:
            return None
        self.policy.forbidden = self.shell.forbidden

        # Metabolic intake (T-P2.1): eat what the operator has credited, before
        # deciding — pressure this step reflects the post-intake state. A paused
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
        if reflex_engaged:
            action = self.reflex.select(  # type: ignore[union-attr]
                self.model, forbidden=self.shell.forbidden
            )
        elif idle and self.idle_drives is not None:
            action, drive = self.idle_drives.select(
                self.model, forbidden=self.shell.forbidden
            )
        else:
            explore = self.relevance.explore_drive if self.modulate_relevance else 0.5
            action = self.policy.select(self.model, explore, self.viability.pressure)

        reward = env.act(action)
        self.viability.ingest(reward)
        self.viability.metabolize()
        surprise = self.model.update(action, reward)
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
        self.shell.observe(record)
        return record
