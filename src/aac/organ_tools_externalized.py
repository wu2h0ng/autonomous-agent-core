"""Externalized-belief variant of the organ-tools causal discovery arm.

Same tools as `organ_tools`, but the belief state is stored outside the LLM
context window in a structured ledger. The LLM (or deterministic stub) reads a
compact ledger summary and writes a decision; it never sees the raw particle
posterior.

Pure stdlib.
"""
from __future__ import annotations

import json
import math
import random
from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol

try:
    from .organ_tools import (
        PosteriorState,
        belief_update,
        info_gain,
    )
    from .plumbing_instrument import PlumbingInstrument
except ImportError:
    from organ_tools import (
        PosteriorState,
        belief_update,
        info_gain,
    )
    from plumbing_instrument import PlumbingInstrument


class ExternalizedBackend(Protocol):
    def decide(
        self,
        ledger_summary: Mapping[str, Any],
        candidate_interventions: Mapping[int, list[float]],
    ) -> Mapping[str, Any]:
        """Return a decision given only the externalized ledger summary."""


@dataclass
class DeterministicStubExternalizedBackend:
    """Offline deterministic stand-in for the externalized-belief arm."""

    seed: int = 0

    def decide(
        self,
        ledger_summary: Mapping[str, Any],
        candidate_interventions: Mapping[int, list[float]],
    ) -> Mapping[str, Any]:
        return {"action": "info_gain", "n_mc_samples": 3}


@dataclass
class BeliefLedger:
    """Externalized belief ledger — the only state the LLM may read/write."""

    step: int = 0
    budget_remaining: int = 0
    n_observations: int = 0
    posterior_entropy: float = 0.0
    last_selected_node: int | None = None
    last_selected_value: float | None = None
    last_eig: float | None = None
    top_edge_predictions: list[tuple[tuple[int, int], float]] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        return {
            "step": self.step,
            "budget_remaining": self.budget_remaining,
            "n_observations": self.n_observations,
            "posterior_entropy": round(self.posterior_entropy, 4),
            "last_selected_node": self.last_selected_node,
            "last_selected_value": self.last_selected_value,
            "last_eig": self.last_eig,
            "top_edge_predictions": [
                [list(e), round(s, 4)] for e, s in self.top_edge_predictions
            ],
        }


@dataclass
class OrganToolsExternalizedResult:
    edge_scores: dict[tuple[int, int], float]
    interventions_spent: int
    posterior_state: PosteriorState
    ledger: BeliefLedger
    trace: list[dict[str, Any]] = field(default_factory=list)
    plumbing_counts: dict[str, int] = field(default_factory=dict)


def run_organ_tools_externalized(
    observational: list[list[float]],
    consultable_interventions: dict[tuple[int, float], list[list[float]]],
    budget: int,
    backend: ExternalizedBackend | None = None,
    instrument: PlumbingInstrument | None = None,
    n_particles: int = 50,
    seed: int = 0,
    n_mc_samples: int = 10,
    likelihood_mode: str = "linear",
) -> OrganToolsExternalizedResult:
    """Run the externalized-belief organ_tools arm.

    The LLM/stub sees only the BeliefLedger summary; the raw particle posterior
    never enters the prompt context.
    """
    backend = backend or DeterministicStubExternalizedBackend(seed=seed)
    if instrument is not None and hasattr(backend, "instrument"):
        backend.instrument = instrument
    rng = random.Random(seed)
    n_nodes = len(observational[0]) if observational else 0

    candidate_values: dict[int, list[float]] = {}
    for (target, value), _ in consultable_interventions.items():
        candidate_values.setdefault(target, []).append(value)
    for target in range(n_nodes):
        candidate_values.setdefault(target, [-2.0, 0.0, 2.0])

    observations: list[list[float]] = [list(row) for row in observational]
    posterior: PosteriorState | None = None
    spent = 0
    trace: list[dict[str, Any]] = []
    ledger = BeliefLedger()

    for step in range(budget):
        posterior = belief_update(
            observations,
            posterior,
            n_particles,
            seed=seed + step,
            likelihood_mode=likelihood_mode,
        )
        entropy = _approx_entropy(posterior.weights)
        edge_scores = posterior.to_dibs(seed, likelihood_mode=likelihood_mode).edge_marginals()
        top_edges = sorted(edge_scores.items(), key=lambda x: x[1], reverse=True)[:5]

        ledger.step = step
        ledger.budget_remaining = budget - spent
        ledger.n_observations = len(observations)
        ledger.posterior_entropy = entropy
        ledger.top_edge_predictions = top_edges

        decision = backend.decide(ledger.summary(), candidate_values)
        final_edges = _extract_decision_edges(decision)
        if final_edges is not None:
            final_scores = _edges_to_scores(final_edges, n_nodes)
            trace.append({"step": step, "event": "final_answer", "spent": spent})
            return OrganToolsExternalizedResult(
                edge_scores=final_scores,
                interventions_spent=spent,
                posterior_state=posterior,
                ledger=ledger,
                trace=trace,
                plumbing_counts=_instrument_counts(instrument),
            )

        action = decision.get("action") if isinstance(decision, Mapping) else None

        if action == "info_gain":
            mc = decision.get("n_mc_samples", n_mc_samples)
            ranked = info_gain(
                observations,
                candidate_values,
                posterior,
                mc,
                seed=seed + step,
                likelihood_mode=likelihood_mode,
            )
            if not ranked or ranked[0][2] <= 0.0:
                trace.append({"step": step, "event": "no_positive_eig", "spent": spent})
                break
            target, value, eig = ranked[0]
            key = (target, value)
            if key not in consultable_interventions:
                trace.append({"step": step, "event": "key_missing", "key": key})
                break
            sampled = rng.choice(consultable_interventions[key])
            observations.append(list(sampled))
            spent += 1
            ledger.last_selected_node = target
            ledger.last_selected_value = value
            ledger.last_eig = eig
            trace.append(
                {
                    "step": step,
                    "event": "intervene",
                    "target": target,
                    "value": value,
                    "eig": eig,
                    "spent": spent,
                }
            )
        elif action == "belief_update":
            # Backend asked for an explicit belief update; continue without spend.
            trace.append({"step": step, "event": "belief_update", "spent": spent})
        else:
            if instrument is not None:
                instrument.log_unparseable(
                    "organ_tools_externalized_loop",
                    f"unrecognized decision action: {action}",
                    {"decision_keys": list(decision.keys()) if isinstance(decision, Mapping) else []},
                )
            trace.append({"step": step, "event": "halt", "decision": dict(decision) if isinstance(decision, Mapping) else str(decision)})
            break

    if posterior is None:
        posterior = belief_update(
            observations, None, n_particles, seed=seed, likelihood_mode=likelihood_mode
        )
    final_scores = posterior.to_dibs(seed, likelihood_mode=likelihood_mode).edge_marginals()
    ledger.budget_remaining = budget - spent
    ledger.n_observations = len(observations)
    ledger.posterior_entropy = _approx_entropy(posterior.weights)
    ledger.top_edge_predictions = sorted(
        final_scores.items(), key=lambda x: x[1], reverse=True
    )[:5]

    return OrganToolsExternalizedResult(
        edge_scores=final_scores,
        interventions_spent=spent,
        posterior_state=posterior,
        ledger=ledger,
        trace=trace,
        plumbing_counts=_instrument_counts(instrument),
    )


def _approx_entropy(weights: list[float]) -> float:
    ent = 0.0
    for w in weights:
        if w > 1e-15:
            ent -= w * math.log(w)
    return ent


def _extract_decision_edges(decision: Any) -> list[list[Any]] | None:
    """Return edges list from a decision final_answer, or None."""
    if not isinstance(decision, Mapping):
        return None
    final = decision.get("final_answer")
    if isinstance(final, Mapping):
        edges = final.get("edges")
        return edges if isinstance(edges, list) else None
    # Also accept a top-level "edges" key as a robustness concession.
    edges = decision.get("edges")
    return edges if isinstance(edges, list) else None


def _edges_to_scores(
    edges: list[Any], n_nodes: int
) -> dict[tuple[int, int], float]:
    """Convert a list of [i, j, confidence] into an edge-score dict."""
    scores: dict[tuple[int, int], float] = {
        (i, j): 0.0
        for i in range(n_nodes)
        for j in range(n_nodes)
        if i != j
    }
    for edge in edges:
        if not isinstance(edge, (list, tuple)) or len(edge) < 3:
            continue
        try:
            i = int(edge[0])
            j = int(edge[1])
            c = float(edge[2])
        except (TypeError, ValueError):
            continue
        if 0 <= i < n_nodes and 0 <= j < n_nodes and i != j and math.isfinite(c):
            scores[(i, j)] = min(1.0, max(0.0, c))
    return scores


def _instrument_counts(instrument: PlumbingInstrument | None) -> dict[str, int]:
    if instrument is None:
        return {}
    return instrument.counts()


if __name__ == "__main__":
    import sys

    sys.path.insert(0, "experiments")
    from scm_generator import generate_scm, SCMConfig

    world = generate_scm(SCMConfig(n_nodes=6, n_obs=200, seed=42))
    all_keys = list(world.interventions.keys())
    rng = random.Random(123)
    rng.shuffle(all_keys)
    consultable = {k: world.interventions[k] for k in all_keys[: len(all_keys) // 2]}

    result = run_organ_tools_externalized(
        world.observational,
        consultable,
        budget=3,
        seed=42,
        n_particles=20,
        n_mc_samples=3,
    )
    print("interventions_spent:", result.interventions_spent)
    print("ledger:", json.dumps(result.ledger.summary(), sort_keys=True))
    print("trace:", result.trace)
