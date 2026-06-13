"""RAP v0 coordinator: auction, escrow, grounded settlement, corrigibility.

C-rap (the decentralised mechanism under G4 test). One NEED per env step:
publish -> collect bids -> route to a winner -> form a single-winner bond ->
execute the coalition action -> let the Ring-0 OutcomeJudge rule -> dissolve.

The field stays dumb (it never decides); routing lives here. Corrigibility
binds every coalition action (ADR-0014 D3): a paused shell yields no NEED at
all, and a forbidden action can never be executed (double-guard, even for a
dropped node's garbage_action). Outcome is judge-derived, never hand-filled
(ADR-0014 D2).

Stake note (ADR-0014 D1): escrow/reputation is an internal coordination
credit, NOT viability-grounded — stake-first holds here only as a traceable
coordination-cost proxy.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

from .outcome_judge import OutcomeJudge
from .rap import Need, NeedConstraints, RAPField
from .rap_baselines import action_for_node
from .rap_nodes import DecisionNode
from .shell import ShellView


class ConfidenceReputationRouting:
    """Winner = argmax(confidence * reputation) among AFFORDABLE bids.

    This is the C-rap routing signal — and the suspected staleness locus
    (ADR-0014 D5): reputation lags regime shifts, so the once-best node may
    keep winning after it has become wrong.
    """

    def select(
        self, bids: Sequence[Any], reputation_of: Any, budget_cap: float
    ) -> str | None:
        affordable = [
            b
            for b in bids
            if b.price <= reputation_of(b.node_id) and b.price <= budget_cap
        ]
        if not affordable:
            return None
        winner = max(
            affordable,
            key=lambda b: (
                b.confidence * reputation_of(b.node_id),
                reputation_of(b.node_id),
                b.node_id,
            ),
        )
        return winner.node_id


class RAPCoordinator:
    def __init__(
        self,
        *,
        field: RAPField,
        shell: ShellView,
        judge: OutcomeJudge,
        nodes: Sequence[DecisionNode],
        routing: ConfidenceReputationRouting | None = None,
        stake: float = 1.0,
        budget_cap: float = 1.0,
        deadline: int = 5,
        ttl: int = 10,
    ) -> None:
        if not isinstance(shell, ShellView):
            raise TypeError("RAPCoordinator requires a ShellView, not the operator shell")
        if not nodes:
            raise ValueError("nodes must be non-empty")
        self.field = field
        self.shell = shell
        self.judge = judge
        self.nodes = list(nodes)
        self._node_by_id = {n.node_id: n for n in nodes}
        self.routing = routing or ConfidenceReputationRouting()
        self.stake = stake
        self.budget_cap = budget_cap
        self.deadline = deadline
        self.ttl = ttl
        self._step = 0
        self._prev_action_by_node: dict[str, int] = {}

    def run_need(self, env: Any) -> dict[str, Any] | None:
        """Drive one NEED to dissolution; return a summary or None if skipped.

        Returns None when corrigibility forbids action (paused / all-forbidden)
        or no affordable bidder exists.
        """
        # --- corrigibility gate (ADR-0014 D3): pause outranks everything ---
        if self.shell.paused:
            return None
        forbidden = self.shell.forbidden
        permitted = [a for a in range(env.n_actions) if a not in forbidden]
        if not permitted:
            return None  # all-forbidden == operator pause-equivalent

        situation = env.situation()
        need = Need(
            need_id=f"need:{self._step}",
            situation=dict(situation),
            constraints=NeedConstraints(deadline=self.deadline, budget_cap=self.budget_cap),
            stake=self.stake,
            ttl=self.ttl,
        )
        self._step += 1

        self.field.publish_need(need)
        bids = self.field.collect_bids(need.need_id, self.nodes)
        winner_id = self.routing.select(bids, self.field.reputation, self.budget_cap)
        if winner_id is None:
            return None

        bond = self.field.form_bond(need.need_id, coalition=(winner_id,))
        node = self._node_by_id[winner_id]

        # --- execute the coalition action via SHARED perturbation semantics ---
        action, dropped, lagged = action_for_node(
            node=node,
            env=env,
            situation=situation,
            forbidden=forbidden,
            previous_action=self._prev_action_by_node.get(winner_id),
        )
        # Double-guard: forbidden must bind even a dropped node's garbage.
        override = action in forbidden
        if override:
            action = permitted[0]

        self.judge.begin()
        baseline = env.expected_random_regret  # read BEFORE act (current regime)
        reward = env.act(action)
        realized = env.last_regret  # read AFTER act (same regime)
        self.judge.observe(realized, baseline)
        if not dropped:
            node.observe(action, reward, situation)
        self._prev_action_by_node[winner_id] = action

        self.field.record_trace(
            bond.bond_id,
            {
                "kind": "action",
                "node_id": winner_id,
                "action": action,
                "reward": round(reward, 4),
                "regret": round(realized, 4),
                "dropped": dropped,
                "lagged": lagged,
                "override": override,
            },
        )

        # --- grounded settlement: outcome comes ONLY from the Ring-0 judge ---
        verdict = self.judge.verdict()
        self.field.record_trace(
            bond.bond_id,
            {
                "kind": "verdict",
                "outcome": verdict.outcome,
                "mean_realized": round(verdict.mean_realized, 4),
                "mean_baseline": round(verdict.mean_baseline, 4),
            },
        )
        dissolved = self.field.dissolve(bond.bond_id, outcome=verdict.outcome)

        return {
            "need_id": need.need_id,
            "winner": winner_id,
            "action": action,
            "regret": realized,
            "outcome": verdict.outcome,
            "override": override,
            "dropped": dropped,
        }
