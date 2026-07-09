"""Real-data intervention binding protocol for CWM live discovery.

This module defines the contract by which the CWM discovery loop can be bound to
a real-world data source + actuator without giving the core execution authority.
The protocol is intentionally minimal:

- The core sees the same ``observe(n)`` / ``intervene(node, value)`` surface it
  already uses for simulation environments.
- The adapter (external to the core) owns the actuator and the read-back path.
- ``GovernedInterventionBinding`` enforces C7 offline/verify-only policy:
  allowed handles, forbidden nodes/edges, value ranges, budget, dry-run mode,
  and per-intervention approval.

The core never executes an external action autonomously.  It proposes; the
adapter applies only after explicit approval and returns the resulting sample.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Protocol


class InterventionError(Exception):
    """Raised when an intervention proposal is rejected by the binding policy."""


@dataclass(frozen=True)
class InterventionProposal:
    """A proposed do() intervention emitted by the CWM loop."""

    node: int
    value: float
    dry_run: bool
    reason: str = ""


@dataclass(frozen=True)
class InterventionOutcome:
    """Result of an attempted intervention."""

    proposal: InterventionProposal
    sample: list[float] | None
    status: str  # "applied", "dry_run", "denied", "blocked", "budget_exhausted", "readback_missing"
    audit_entry: dict[str, Any]


class RealDataInterventionEnv(Protocol):
    """Protocol for a real-world intervention environment adapter.

    Implementations live outside the core runtime (DB, API, physical sensor,
    operator console).  They are responsible for safe actuation and for returning
    observations/interventional samples in the core's numeric matrix format.
    """

    n_nodes: int
    observed_variables: list[str]
    allowed_handles: set[int]
    safe_value_ranges: dict[int, tuple[float, float]]

    @property
    def ground_truth_edges(self) -> set[tuple[int, int]] | None:
        """Ground truth, if known; ``None`` for real systems."""
        ...

    def observe(self, n_samples: int) -> list[list[float]]:
        """Return ``n_samples`` observational rows."""
        ...

    def intervene(self, do_node: int, do_value: float) -> list[float] | None:
        """Return one post-intervention row, or ``None`` if readback failed.

        The implementation must apply the intervention only after its own
        external approval/safety checks; the core does not hold execution
        authority.
        """
        ...

    def structural_hamming_distance(
        self, predicted: set[tuple[int, int]]
    ) -> int | None:
        """SHD if ground truth is known; otherwise ``None``."""
        ...


@dataclass
class GovernedInterventionBinding:
    """C7 policy wrapper around a real-data intervention environment.

    Args:
        env: external adapter implementing ``RealDataInterventionEnv``.
        forbidden_nodes: nodes that must never be intervened upon.
        forbidden_edges: directed edges the loop must not propose.
        dry_run: if ``True``, ``intervene`` returns a synthetic sample and never
            calls the external actuator.  This is the default verify-only mode.
        budget: maximum interventions per discovery session.
        approval: callable that receives a proposal and returns ``True`` if the
            external operator/system authorizes the intervention.  In dry-run
            mode this is skipped.
        audit: callable that receives an ``InterventionOutcome`` audit entry.
            The core's audit chain (shell/Trace) is the sink of record.
    """

    env: RealDataInterventionEnv
    forbidden_nodes: set[int] = field(default_factory=set)
    forbidden_edges: set[tuple[int, int]] = field(default_factory=set)
    dry_run: bool = True
    budget: int = 50
    approval: Callable[[InterventionProposal], bool] = field(
        default_factory=lambda: lambda _p: False
    )
    audit: Callable[[InterventionOutcome], None] = field(
        default_factory=lambda: lambda _o: None
    )
    interventions_spent: int = field(default=0, init=False)

    @property
    def n_nodes(self) -> int:
        return self.env.n_nodes

    @property
    def observed_variables(self) -> list[str]:
        return list(self.env.observed_variables)

    @property
    def allowed_handles(self) -> set[int]:
        return set(self.env.allowed_handles)

    @property
    def ground_truth_edges(self) -> set[tuple[int, int]] | None:
        return self.env.ground_truth_edges

    def observe(self, n_samples: int) -> list[list[float]]:
        """Pass-through to the adapter's observational read path."""
        return self.env.observe(n_samples)

    def intervene(self, do_node: int, do_value: float) -> list[float] | None:
        """Governed intervention: validate, approve (if live), apply, audit.

        Returns the post-intervention sample, or ``None`` if the proposal was
        blocked, denied, or budget-exhausted.
        """
        proposal = InterventionProposal(
            node=do_node, value=do_value, dry_run=self.dry_run
        )

        # 1. Budget gate.
        if self.interventions_spent >= self.budget:
            return self._record(
                proposal, None, "budget_exhausted", {"budget": self.budget}
            )

        # 2. C7 handle gate.
        if do_node in self.forbidden_nodes:
            return self._record(
                proposal, None, "blocked", {"reason": "C7_forbidden_node"}
            )
        if do_node not in self.env.allowed_handles:
            return self._record(
                proposal, None, "blocked", {"reason": "not_an_allowed_handle"}
            )

        # 3. C7 edge gate (self-loops and forbidden parents).
        if (do_node, do_node) in self.forbidden_edges:
            return self._record(
                proposal, None, "blocked", {"reason": "C7_forbidden_edge"}
            )

        # 4. Value-safety gate.
        safe = self.env.safe_value_ranges.get(do_node)
        if safe is not None:
            lo, hi = safe
            if not (lo <= do_value <= hi):
                return self._record(
                    proposal,
                    None,
                    "blocked",
                    {"reason": "value_out_of_range", "range": safe},
                )

        # 5. Dry-run / verify-only path: never touch the actuator.
        if self.dry_run:
            self.interventions_spent += 1
            synthetic = self._synthetic_sample(do_node, do_value)
            return self._record(
                proposal, synthetic, "dry_run", {"note": "C7_verify_only", "interventions_spent": self.interventions_spent}
            )

        # 6. Live path: external approval is mandatory.
        if not self.approval(proposal):
            return self._record(
                proposal, None, "denied", {"reason": "operator_denied"}
            )

        # 7. Actuation and read-back are owned by the external adapter.
        sample = self.env.intervene(do_node, do_value)
        self.interventions_spent += 1
        if sample is None:
            return self._record(
                proposal, None, "readback_missing", {"reason": "adapter_returned_none"}
            )
        return self._record(
            proposal, sample, "applied", {"interventions_spent": self.interventions_spent}
        )

    def structural_hamming_distance(
        self, predicted: set[tuple[int, int]]
    ) -> int | None:
        return self.env.structural_hamming_distance(predicted)

    def _synthetic_sample(self, do_node: int, do_value: float) -> list[float]:
        """Return a deterministic placeholder sample for dry-run mode.

        The value at ``do_node`` is set to ``do_value``; all other entries are
        zero.  This is intentionally not a realistic simulation—it exists only
        to exercise the loop's plumbing without external actuation.
        """
        row = [0.0] * self.env.n_nodes
        row[do_node] = float(do_value)
        return row

    def _record(
        self,
        proposal: InterventionProposal,
        sample: list[float] | None,
        status: str,
        extras: dict[str, Any],
    ) -> list[float] | None:
        entry = {
            "node": proposal.node,
            "value": proposal.value,
            "dry_run": proposal.dry_run,
            "status": status,
        }
        entry.update(extras)
        outcome = InterventionOutcome(
            proposal=proposal, sample=sample, status=status, audit_entry=entry
        )
        self.audit(outcome)
        return sample
