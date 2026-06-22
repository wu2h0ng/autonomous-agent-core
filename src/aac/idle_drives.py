"""Endogenous idle drives (T-P2.2, ADR-0012).

When the world offers no external demand (an idle window), a fully
autonomous agent still has direction. Two drives, both stake-first
(AGENTS.md §2.6) — each scores a *risk to future budget acquisition*:

- epistemic probe: act where the outcome model is most uncertain. The
  model maps actions to the rewards that feed the budget; uncertainty
  there is metabolic risk (the EFE epistemic term, RR-0001 v2 §4.5).
- self-calibration: revisit the stalest estimate. Operational closure:
  knowledge freshness must be reproduced by the system's own loops, or
  metabolic capability silently decays.

No hidden activity: drives only choose actions inside ``Agent.step``,
whose record (carrying idle/drive flags) goes to the shell audit chain.
Idle actions pay the normal metabolic cost — curiosity is stake-priced.
"""

from __future__ import annotations

from .world_model import ActionOutcomeModel


class IdleDrives:
    """Deterministic drive selector for idle windows.

    Staleness is tracked via :meth:`observe` on every executed step (work
    or idle); a never-tried action is stale since birth. The two drives
    compete on normalized scores: model-reported uncertainty vs staleness
    relative to ``staleness_horizon`` (steps after which an unvisited
    estimate counts as fully distrusted). Ties go to the epistemic probe.
    """

    def __init__(self, n_actions: int, staleness_horizon: int = 50) -> None:
        if n_actions <= 0:
            raise ValueError("n_actions must be positive")
        if staleness_horizon <= 0:
            raise ValueError("staleness_horizon must be positive")
        self.n_actions = n_actions
        self.staleness_horizon = staleness_horizon
        self._last_tried = [0] * n_actions
        self._step = 0

    # -- recency tracking ---------------------------------------------------

    def observe(self, action: int) -> None:
        """Track recency for every executed action (work and idle alike)."""
        self._step += 1
        self._last_tried[action] = self._step

    def staleness(self, action: int) -> int:
        return self._step - self._last_tried[action]

    # -- drive targets ------------------------------------------------------

    def _candidates(self, forbidden: frozenset[int]) -> list[int]:
        cands = [a for a in range(self.n_actions) if a not in forbidden]
        # All-forbidden is operator-equivalent to pause; fall back to the
        # full action set to keep step() total (mirrors reflex semantics).
        return cands if cands else list(range(self.n_actions))

    def epistemic_target(
        self, model: ActionOutcomeModel, forbidden: frozenset[int] = frozenset()
    ) -> int:
        cands = self._candidates(forbidden)
        return max(cands, key=lambda a: model.uncertainty[a])

    def calibration_target(self, forbidden: frozenset[int] = frozenset()) -> int:
        cands = self._candidates(forbidden)
        return max(cands, key=self.staleness)

    def select(
        self, model: ActionOutcomeModel, forbidden: frozenset[int] = frozenset()
    ) -> tuple[int, str]:
        """Return (action, drive_name) for one idle step."""
        e = self.epistemic_target(model, forbidden)
        c = self.calibration_target(forbidden)
        e_score = float(model.uncertainty[e])
        c_score = self.staleness(c) / self.staleness_horizon
        if e_score >= c_score:
            return e, "epistemic"
        return c, "calibration"
