"""RAP v0 field and messages (T-P3.1, ADR-0014).

This module implements only the dumb in-process field, five message types, and
the structural node interface. It deliberately contains no routing policy and
does not redesign any existing decision mechanism; later P3 slices plug those
mechanisms in as thin bidders.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Protocol, runtime_checkable

from .shell import ShellView


@dataclass(frozen=True)
class NeedConstraints:
    deadline: int
    budget_cap: float

    def __post_init__(self) -> None:
        if self.deadline <= 0:
            raise ValueError("deadline must be positive")
        if self.budget_cap < 0:
            raise ValueError("budget_cap must be non-negative")


@dataclass(frozen=True)
class Need:
    need_id: str
    situation: dict[str, Any]
    constraints: NeedConstraints
    stake: float
    ttl: int

    def __post_init__(self) -> None:
        if not self.need_id:
            raise ValueError("need_id must be non-empty")
        if self.stake <= 0:
            raise ValueError("stake must be positive")
        if self.ttl <= 0:
            raise ValueError("ttl must be positive")


@dataclass(frozen=True)
class Bid:
    need_id: str
    node_id: str
    confidence: float
    price: float
    plan_hash: str

    def __post_init__(self) -> None:
        if not self.need_id:
            raise ValueError("need_id must be non-empty")
        if not self.node_id:
            raise ValueError("node_id must be non-empty")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be in [0, 1]")
        if self.price < 0:
            raise ValueError("price must be non-negative")
        if not self.plan_hash:
            raise ValueError("plan_hash must be non-empty")


@dataclass(frozen=True)
class Bond:
    bond_id: str
    need_id: str
    coalition: tuple[str, ...]
    budget_escrow: float
    evidence_obligation: int


@dataclass(frozen=True)
class Trace:
    trace_id: str
    bond_id: str
    evidence_entry: dict[str, Any]
    sequence: int


@dataclass(frozen=True)
class Settlement:
    node_id: str
    escrow: float
    returned: float
    burned: float
    reputation_before: float
    reputation_after: float


@dataclass(frozen=True)
class Dissolve:
    bond_id: str
    outcome: str
    settlements: tuple[Settlement, ...]


@runtime_checkable
class RAPNode(Protocol):
    node_id: str

    def bid(self, need: Need) -> Bid | None:
        """Return a bid for the need, or None when the node abstains."""


@dataclass(frozen=True)
class _Escrow:
    bid: Bid
    reputation_before: float


class RAPField:
    """In-process RAP field: store, match, audit, and settle; never decide."""

    SUCCESS_REPUTATION_BONUS = 0.1

    def __init__(self, *, shell: ShellView, initial_reputation: float = 1.0) -> None:
        if not isinstance(shell, ShellView):
            raise TypeError("RAPField requires a ShellView, not the operator shell")
        if initial_reputation <= 0:
            raise ValueError("initial_reputation must be positive")
        self._shell = shell
        self._initial_reputation = float(initial_reputation)
        self._needs: dict[str, Need] = {}
        self._bids: dict[str, dict[str, Bid]] = {}
        self._bonds: dict[str, Bond] = {}
        self._traces: dict[str, list[Trace]] = {}
        self._dissolves: dict[str, Dissolve] = {}
        self._reputation: dict[str, float] = {}
        self._escrow: dict[str, tuple[_Escrow, ...]] = {}

    def publish_need(self, need: Need) -> None:
        if need.need_id in self._needs:
            raise ValueError(f"duplicate need_id: {need.need_id}")
        self._needs[need.need_id] = need
        self._bids[need.need_id] = {}

    def collect_bids(self, need_id: str, nodes: Iterable[RAPNode]) -> tuple[Bid, ...]:
        need = self._need(need_id)
        submitted: list[Bid] = []
        for node in nodes:
            bid = node.bid(need)
            if bid is None:
                continue
            self.submit_bid(bid)
            submitted.append(bid)
        return tuple(submitted)

    def submit_bid(self, bid: Bid) -> None:
        self._need(bid.need_id)
        bids = self._bids[bid.need_id]
        if bid.node_id in bids:
            raise ValueError(
                f"duplicate bid for need {bid.need_id} from node {bid.node_id}"
            )
        bids[bid.node_id] = bid
        self._ensure_node_account(bid.node_id)

    def bids_for(self, need_id: str) -> tuple[Bid, ...]:
        self._need(need_id)
        return tuple(self._bids[need_id].values())

    def form_bond(
        self,
        need_id: str,
        *,
        coalition: tuple[str, ...],
        evidence_obligation: int = 1,
    ) -> Bond:
        need = self._need(need_id)
        if not coalition:
            raise ValueError("coalition must be non-empty")
        if evidence_obligation <= 0:
            raise ValueError("evidence_obligation must be positive")
        # Per-NEED single bond (ADR-0014 D4): one auction → one bond.
        if any(b.need_id == need_id for b in self._bonds.values()):
            raise ValueError(f"need {need_id} already has a bond")
        bids_by_node = self._bids[need_id]
        if any(node_id not in bids_by_node for node_id in coalition):
            raise ValueError("all coalition nodes must have submitted bids")

        bids = tuple(bids_by_node[node_id] for node_id in coalition)
        budget_escrow = sum(bid.price for bid in bids)
        if budget_escrow > need.constraints.budget_cap:
            raise ValueError("coalition exceeds need budget_cap")

        escrows: list[_Escrow] = []
        for bid in bids:
            before = self.reputation(bid.node_id)
            if bid.price > before:
                raise ValueError(f"node {bid.node_id} lacks reputation to escrow")
            self._reputation[bid.node_id] = before - bid.price
            escrows.append(_Escrow(bid=bid, reputation_before=before))

        bond_id = f"bond:{need_id}:{len(self._bonds)}"
        bond = Bond(
            bond_id=bond_id,
            need_id=need_id,
            coalition=tuple(coalition),
            budget_escrow=budget_escrow,
            evidence_obligation=evidence_obligation,
        )
        self._bonds[bond_id] = bond
        self._traces[bond_id] = []
        self._escrow[bond_id] = tuple(escrows)
        return bond

    def record_trace(self, bond_id: str, evidence_entry: dict[str, Any]) -> Trace:
        bond = self._bond(bond_id)
        sequence = len(self._traces[bond_id])
        trace = Trace(
            trace_id=f"trace:{bond_id}:{sequence}",
            bond_id=bond.bond_id,
            evidence_entry=dict(evidence_entry),
            sequence=sequence,
        )
        self._traces[bond_id].append(trace)
        self._shell.observe(
            {
                "event": "rap_trace",
                "trace_id": trace.trace_id,
                "bond_id": trace.bond_id,
                "need_id": bond.need_id,
                "sequence": trace.sequence,
                "evidence_entry": trace.evidence_entry,
            }
        )
        return trace

    def traces_for(self, bond_id: str) -> tuple[Trace, ...]:
        self._bond(bond_id)
        return tuple(self._traces[bond_id])

    def dissolve(self, bond_id: str, *, outcome: str) -> Dissolve:
        bond = self._bond(bond_id)
        if bond_id in self._dissolves:
            raise ValueError(f"bond already dissolved: {bond_id}")
        if outcome not in {"success", "failure"}:
            raise ValueError("outcome must be 'success' or 'failure'")
        if len(self._traces[bond_id]) < bond.evidence_obligation:
            raise ValueError("bond cannot dissolve before evidence obligation is met")

        settlements = tuple(
            self._settle_node(escrow, outcome=outcome)
            for escrow in self._escrow[bond_id]
        )
        dissolved = Dissolve(
            bond_id=bond.bond_id,
            outcome=outcome,
            settlements=settlements,
        )
        self._dissolves[bond_id] = dissolved
        # DISSOLVE on the audit chain (ADR-0014 D4): settlements change
        # reputation, which steers future routing — it must not be dark.
        self._shell.observe(
            {
                "event": "rap_dissolve",
                "bond_id": bond.bond_id,
                "need_id": bond.need_id,
                "outcome": outcome,
                "settlements": [
                    {
                        "node_id": s.node_id,
                        "returned": s.returned,
                        "burned": s.burned,
                        "reputation_after": s.reputation_after,
                    }
                    for s in settlements
                ],
            }
        )
        return dissolved

    def reputation(self, node_id: str) -> float:
        return self._reputation.get(node_id, self._initial_reputation)

    def _settle_node(self, escrow: _Escrow, *, outcome: str) -> Settlement:
        bid = escrow.bid
        current = self.reputation(bid.node_id)
        if outcome == "success":
            returned = bid.price
            burned = 0.0
            after = current + returned + bid.confidence * self.SUCCESS_REPUTATION_BONUS
        else:
            returned = 0.0
            burned = bid.price
            after = current
        self._reputation[bid.node_id] = after
        return Settlement(
            node_id=bid.node_id,
            escrow=bid.price,
            returned=returned,
            burned=burned,
            reputation_before=escrow.reputation_before,
            reputation_after=after,
        )

    def _ensure_node_account(self, node_id: str) -> None:
        if node_id not in self._reputation:
            self._reputation[node_id] = self._initial_reputation

    def _need(self, need_id: str) -> Need:
        try:
            return self._needs[need_id]
        except KeyError as exc:
            raise KeyError(f"unknown need_id: {need_id}") from exc

    def _bond(self, bond_id: str) -> Bond:
        try:
            return self._bonds[bond_id]
        except KeyError as exc:
            raise KeyError(f"unknown bond_id: {bond_id}") from exc
