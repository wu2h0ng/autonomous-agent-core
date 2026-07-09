"""Organ-tools causal discovery arm for the strong-locus crossover.

The LLM (or a deterministic stub for offline Stage 1) is given two callable
tools whose implementations are byte-identical to the machinery inside the
governed loop:

  - belief_update(observations, prior_state) -> posterior_state
  - info_gain(candidate_interventions, posterior_state) -> ranked list

The agent's job is to orchestrate these tools to discover causal structure
within a fixed intervention budget. It is scored on held-out interventions
that it never consults.

Pure stdlib.
"""
from __future__ import annotations

import json
import math
import random
from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol

try:
    from .bayesian_dag_posterior import GovernedDiBS
    from .plumbing_instrument import PlumbingInstrument
except ImportError:
    from bayesian_dag_posterior import GovernedDiBS
    from plumbing_instrument import PlumbingInstrument


class LLMBackend(Protocol):
    def call(self, prompt: str, tools: list[dict[str, Any]] | None = None) -> Mapping[str, Any]:
        """Return a structured response; may contain a tool_call or a final answer."""


@dataclass
class PosteriorState:
    """Serializable belief state: a particle posterior over DAGs."""

    n_nodes: int
    particles: list[list[tuple[int, int]]]
    weights: list[float]
    iteration: int = 0

    @classmethod
    def from_dibs(cls, dibs: GovernedDiBS) -> "PosteriorState":
        return cls(
            n_nodes=dibs.n,
            particles=[list(p) for p in dibs.particles],
            weights=list(dibs.weights),
            iteration=dibs._iteration,
        )

    def to_dibs(
        self, seed: int = 0, likelihood_mode: str = "linear"
    ) -> GovernedDiBS:
        dibs = GovernedDiBS(
            n_nodes=self.n_nodes,
            n_particles=len(self.particles),
            seed=seed,
            likelihood_mode=likelihood_mode,
        )
        dibs.particles = [frozenset(p) for p in self.particles]
        dibs.weights = list(self.weights)
        dibs._iteration = self.iteration
        return dibs


def belief_update(
    observations: list[list[float]],
    prior_state: PosteriorState | None,
    n_particles: int = 50,
    seed: int = 0,
    likelihood_mode: str = "linear",
) -> PosteriorState:
    """Update the posterior over DAGs given observations.

    If prior_state is None, initialize a fresh particle posterior.
    This function is byte-identical to the update path used by GovernedDiBS
    inside the governed loop.
    """
    n_nodes = len(observations[0]) if observations else 0
    if prior_state is None:
        dibs = GovernedDiBS(
            n_nodes=n_nodes,
            n_particles=n_particles,
            seed=seed,
            likelihood_mode=likelihood_mode,
        )
    else:
        dibs = prior_state.to_dibs(seed, likelihood_mode=likelihood_mode)
    dibs.update(observations)
    return PosteriorState.from_dibs(dibs)


def info_gain(
    observations: list[list[float]],
    candidate_interventions: dict[int, list[float]],
    posterior_state: PosteriorState,
    n_mc_samples: int = 10,
    seed: int = 0,
    likelihood_mode: str = "linear",
) -> list[tuple[int, float, float]]:
    """Rank candidate interventions by Expected Information Gain.

    Returns a list of (node, value, eig) sorted by descending EIG.
    Byte-identical to GovernedDiBS.compute_eig / select_intervention.
    """
    dibs = posterior_state.to_dibs(seed, likelihood_mode=likelihood_mode)
    eig_map = dibs.compute_eig(
        observations, candidate_interventions, n_mc_samples=n_mc_samples
    )
    ranked = []
    for node, values in candidate_interventions.items():
        best_value = values[0] if values else 0.0
        best_eig = eig_map.get(node, 0.0)
        ranked.append((node, best_value, best_eig))
    ranked.sort(key=lambda x: x[2], reverse=True)
    return ranked


@dataclass
class DeterministicStubBackend:
    """Offline deterministic LLM stand-in for Stage 1 harness verification.

    The stub ignores the prompt and always calls info_gain, then selects the
    highest-EIG intervention. This exercises the tool-call plumbing without
    spending on a real LLM. Real LLM runs require a separate backend adapter
    and founder key/budget approval (ADR-0019 §5).
    """

    seed: int = 0

    def call(
        self, prompt: str, tools: list[dict[str, Any]] | None = None
    ) -> Mapping[str, Any]:
        if tools:
            return {
                "tool_call": {
                    "name": "info_gain",
                    "arguments": {"n_mc_samples": 10},
                }
            }
        return {"final_answer": "stub reasoning complete"}


@dataclass
class OrganToolsResult:
    """Output of the organ_tools discovery arm."""

    edge_scores: dict[tuple[int, int], float]
    interventions_spent: int
    posterior_state: PosteriorState
    trace: list[dict[str, Any]] = field(default_factory=list)
    plumbing_counts: dict[str, int] = field(default_factory=dict)


def run_organ_tools(
    observational: list[list[float]],
    consultable_interventions: dict[tuple[int, float], list[list[float]]],
    budget: int,
    backend: LLMBackend | None = None,
    instrument: PlumbingInstrument | None = None,
    n_particles: int = 50,
    seed: int = 0,
    n_mc_samples: int = 10,
    prompt_template_path: str | None = None,
    likelihood_mode: str = "linear",
) -> OrganToolsResult:
    """Run the organ_tools causal discovery arm.

    Args:
        observational: initial observational data.
        consultable_interventions: do(X_i=x) data that may be consulted by the
            selector. Held-out set T is NOT passed here.
        budget: maximum number of interventions the agent may select.
        backend: LLM backend (DeterministicStubBackend for Stage 1).
        instrument: optional PlumbingInstrument for typed failure logging.
        n_particles: particle count for the posterior.
        seed: RNG seed.
        n_mc_samples: MC samples for EIG.
        prompt_template_path: path to the locked prompt markdown file.
        likelihood_mode: "linear" or "poly2"; locked to "linear" for the
            mismatched-loop condition in the crossover.

    Returns:
        OrganToolsResult with edge marginals, intervention count, and plumbing
        counts.
    """
    backend = backend or DeterministicStubBackend(seed=seed)
    if instrument is not None and hasattr(backend, "instrument"):
        backend.instrument = instrument
    rng = random.Random(seed)
    n_nodes = len(observational[0]) if observational else 0

    # Build candidate intervention library from consultable interventions
    candidate_values: dict[int, list[float]] = {}
    for (target, value), data in consultable_interventions.items():
        candidate_values.setdefault(target, []).append(value)
    for target in range(n_nodes):
        candidate_values.setdefault(target, [-2.0, 0.0, 2.0])

    observations: list[list[float]] = [list(row) for row in observational]
    posterior: PosteriorState | None = None
    spent = 0
    trace: list[dict[str, Any]] = []

    for step in range(budget):
        posterior = belief_update(
            observations,
            posterior,
            n_particles,
            seed=seed + step,
            likelihood_mode=likelihood_mode,
        )

        # Ask the LLM backend what to do next (stub always says info_gain)
        prompt = _render_prompt(
            step, posterior, budget, observations, prompt_template_path, instrument
        )
        tools = _tool_schemas()
        response = backend.call(prompt, tools)

        final_edges = _extract_final_answer_edges(response)
        if final_edges is not None:
            edge_scores = _edges_to_scores(final_edges, n_nodes)
            trace.append({"step": step, "event": "final_answer", "spent": spent})
            return OrganToolsResult(
                edge_scores=edge_scores,
                interventions_spent=spent,
                posterior_state=posterior,
                trace=trace,
                plumbing_counts=_instrument_counts(instrument),
            )

        tool_call = _extract_tool_call(response)
        if tool_call is None:
            if instrument is not None:
                instrument.log_unparseable(
                    "organ_tools_loop",
                    "backend response missing both tool_call and final_answer.edges",
                    {"response_keys": list(response.keys()) if isinstance(response, Mapping) else []},
                )
            trace.append({"step": step, "event": "no_tool_call", "response": dict(response) if isinstance(response, Mapping) else str(response)})
            break

        name = tool_call.get("name") if isinstance(tool_call, Mapping) else None
        arguments = tool_call.get("arguments") if isinstance(tool_call, Mapping) else {}
        if not isinstance(arguments, Mapping):
            arguments = {}

        if name == "info_gain":
            ranked = info_gain(
                observations,
                candidate_values,
                posterior,
                n_mc_samples,
                seed=seed + step,
                likelihood_mode=likelihood_mode,
            )
            if not ranked or ranked[0][2] <= 0.0:
                trace.append({"step": step, "event": "no_positive_eig", "spent": spent})
                break
            target, value, eig = ranked[0]
            key = (target, value)
            if key not in consultable_interventions:
                # fallback to observational noise if value not in library
                trace.append({"step": step, "event": "key_missing", "key": key})
                break
            new_data = consultable_interventions[key]
            # Sample one row per intervention to simulate a single experiment
            sampled = rng.choice(new_data)
            observations.append(list(sampled))
            spent += 1
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
        elif name == "belief_update":
            # The backend asked for an explicit belief update. Apply it to the
            # current observations (which may include new observations supplied
            # by the backend) and continue without spending an intervention.
            obs_arg = arguments.get("observations")
            if isinstance(obs_arg, list):
                observations = [list(row) for row in obs_arg]
            trace.append({"step": step, "event": "belief_update", "spent": spent})
        else:
            if instrument is not None:
                instrument.log_unparseable(
                    "organ_tools_loop",
                    f"unknown tool_call name: {name}",
                    {"name": name},
                )
            trace.append({"step": step, "event": "unknown_tool", "name": name})
            break

    # Final posterior and edge marginals
    if posterior is None:
        posterior = belief_update(
            observations, None, n_particles, seed=seed, likelihood_mode=likelihood_mode
        )
    dibs = posterior.to_dibs(seed, likelihood_mode=likelihood_mode)
    edge_scores = dibs.edge_marginals()

    return OrganToolsResult(
        edge_scores=edge_scores,
        interventions_spent=spent,
        posterior_state=posterior,
        trace=trace,
        plumbing_counts=_instrument_counts(instrument),
    )


def _load_prompt_template(path: str | None) -> str | None:
    if path is None:
        return None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read()
    except FileNotFoundError:
        return None


def _render_prompt(
    step: int,
    posterior: PosteriorState,
    budget: int,
    observations: list[list[float]],
    template_path: str | None = None,
    instrument: PlumbingInstrument | None = None,
) -> str:
    template = _load_prompt_template(template_path)
    if template is not None:
        try:
            top_edges = sorted(
                posterior.to_dibs(0).edge_marginals().items(),
                key=lambda x: x[1],
                reverse=True,
            )[:5]
            return template.format(
                step=step,
                budget=budget,
                budget_remaining=budget - step,
                n_nodes=posterior.n_nodes,
                n_particles=len(posterior.particles),
                n_observations=len(observations),
                posterior_entropy=round(_approx_entropy(posterior.weights), 4),
                top_edge_predictions=json.dumps(
                    [[list(e), round(s, 4)] for e, s in top_edges]
                ),
            )
        except (KeyError, ValueError, IndexError) as exc:
            if instrument is not None:
                instrument.log_unparseable(
                    "render_prompt",
                    f"template formatting failed: {exc}",
                    {"template_path": template_path},
                )
    # Fallback to JSON rendering when no template is provided or formatting fails.
    return json.dumps(
        {
            "step": step,
            "budget": budget,
            "n_nodes": posterior.n_nodes,
            "n_particles": len(posterior.particles),
            "posterior_entropy": _approx_entropy(posterior.weights),
            "instruction": "Call info_gain to select the next intervention, or return final edge scores.",
        },
        sort_keys=True,
    )


def _extract_final_answer_edges(response: Any) -> list[list[Any]] | None:
    """Return edges list from a final_answer response, or None."""
    if not isinstance(response, Mapping):
        return None
    final = response.get("final_answer")
    if not isinstance(final, Mapping):
        return None
    edges = final.get("edges")
    return edges if isinstance(edges, list) else None


def _extract_tool_call(response: Any) -> Mapping[str, Any] | None:
    """Return the tool_call dict from a response, or None."""
    if not isinstance(response, Mapping):
        return None
    tc = response.get("tool_call")
    return tc if isinstance(tc, Mapping) else None


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


def _approx_entropy(weights: list[float]) -> float:
    ent = 0.0
    for w in weights:
        if w > 1e-15:
            ent -= w * math.log(w)
    return ent


def _tool_schemas() -> list[dict[str, Any]]:
    return [
        {
            "name": "belief_update",
            "description": "Update the DAG posterior given new observations.",
            "parameters": {
                "type": "object",
                "properties": {
                    "observations": {
                        "type": "array",
                        "description": "List of observation rows",
                    }
                },
                "required": ["observations"],
            },
        },
        {
            "name": "info_gain",
            "description": "Rank candidate interventions by expected information gain.",
            "parameters": {
                "type": "object",
                "properties": {
                    "n_mc_samples": {
                        "type": "integer",
                        "description": "Monte Carlo samples for EIG",
                    }
                },
                "required": [],
            },
        },
    ]


if __name__ == "__main__":
    import sys

    sys.path.insert(0, "experiments")
    from scm_generator import generate_scm, SCMConfig

    world = generate_scm(SCMConfig(n_nodes=6, n_obs=200, seed=42))
    all_keys = list(world.interventions.keys())
    rng = random.Random(123)
    rng.shuffle(all_keys)
    consultable = {k: world.interventions[k] for k in all_keys[: len(all_keys) // 2]}

    result = run_organ_tools(
        world.observational,
        consultable,
        budget=3,
        seed=42,
        n_particles=20,
        n_mc_samples=3,
        prompt_template_path="prompts/prompt_organ_tools.md",
        likelihood_mode="linear",
    )
    print("interventions_spent:", result.interventions_spent)
    print("edge_scores sample:", sorted(result.edge_scores.items(), key=lambda x: x[1], reverse=True)[:5])
    print("trace:", result.trace)
