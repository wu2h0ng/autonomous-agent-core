"""Strong-locus structure crossover runner.

Runs all 7 arms on synthetic SCM worlds across seeds and k values, scores them
on held-out interventions, and emits a result JSON.

Stage 1 (default): synthetic data only, deterministic stub backend, 2 seeds x 2 k.
Stage 3: real-LLM backend support with deterministic stub fallback, 20 seeds x
5 k, typed plumbing instrumentation, and pre-registered adjudication.

Pure stdlib. Run from autonomous-agent-core root:
    PYTHONPATH=src python experiments/strong_locus_structure_crossover.py
    PYTHONPATH=src python experiments/strong_locus_structure_crossover.py --stage 3 --backend stub
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import sys
import time
from dataclasses import asdict, dataclass
from typing import Any

sys.path.insert(0, "src")
sys.path.insert(0, "experiments")

from scm_generator import generate_scm, residual_linear_gaussian_fit, SCMConfig
from aac.structure_scorer import score_structure
from aac.bayesian_dag_posterior import GovernedDiBS
from aac.governed_gate import GovernedDecisionGate
from aac.organ_tools import run_organ_tools
from aac.organ_tools_externalized import run_organ_tools_externalized
from aac.learned_select import run_learned_select
from aac.placebo_world import generate_placebo, validate_placebo_nonidentifiability
from aac.plumbing_instrument import PlumbingInstrument
from aac.llm_client import build_backend


# Byte-identical hyperparameters across all k (verified by runner output).
N_PARTICLES = 20
N_MC_SAMPLES = 3
UCB_ALPHA = 1.0
BUDGET = 3
LIKELIHOOD_MODE = "linear"  # loop likelihood is intentionally mismatched
SCORE_EFFECT_THRESHOLD = 1.5
EMPIRICAL_EFFECT_THRESHOLD = 1.5
SEEDS = [42, 43]
KS = [3, 8]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Strong-locus structure crossover runner"
    )
    parser.add_argument(
        "--stage", type=int, choices=[1, 3, 4], default=1, help="Stage to run"
    )
    parser.add_argument(
        "--spec",
        default="experiments/strong_locus_stage3.spec.json",
        help="Stage 3 spec JSON",
    )
    parser.add_argument(
        "--seeds",
        default="experiments/strong_locus_stage3.seeds.json",
        help="Stage 3 seeds JSON",
    )
    parser.add_argument(
        "--backend",
        choices=["stub", "anthropic", "openai"],
        default="stub",
        help="LLM backend for Stage 3",
    )
    parser.add_argument(
        "--result-path",
        default=None,
        help="Output result JSON path (default depends on stage)",
    )
    parser.add_argument(
        "--plumbing-path",
        default="experiments/strong_locus_stage3.plumbing.jsonl",
        help="Output plumbing events JSONL path",
    )
    parser.add_argument(
        "--preprocessed",
        default="experiments/replogle_2022_preprocessed.json",
        help="Preprocessed Perturb-seq JSON for Stage 4",
    )
    return parser.parse_args()


def _load_prompt(path: str) -> str:
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def _make_disposer(seed: int):
    """Return a deterministic disposer that ALLOWs all proposals in Stage 1.

    In Stage 3, this can be replaced with a real risk-tiered
    GovernedDecisionGate. For harness verification we use a permissive gate
    that logs every decision as ALLOW so the execution path is exercised.
    """
    from aac.governed_gate import ALLOW
    from aac.self_model import ActionRequest, AgentSelfModel

    self_model = AgentSelfModel(
        allowed_tools=frozenset({"intervene"}),
        denied_tools=frozenset(),
        risk_ceiling=5,
        approval_required_at_or_above=5,
        evidence_requirements={1: 1},
        confidence_thresholds={1: 0.0},
    )
    gate = GovernedDecisionGate(self_model=self_model)

    def decide(action_index: int, risk_tier: int = 1) -> str:
        req = ActionRequest(
            action="intervene",
            risk_tier=risk_tier,
            confidence=1.0,
            verified=True,
            evidence_count=5,
            approved=True,
            action_index=action_index,
        )
        return gate.decide(req).verdict

    return decide


def _corr_arm(
    observational: list[list[float]],
    held_out: dict[tuple[int, float], list[list[float]]],
) -> dict[tuple[int, int], float]:
    """Correlation baseline: |correlation| from observational data."""
    n_nodes = len(observational[0])
    means = [sum(row[j] for row in observational) / len(observational) for j in range(n_nodes)]
    stds = []
    for j in range(n_nodes):
        v = sum((row[j] - means[j]) ** 2 for row in observational) / len(observational)
        stds.append(math.sqrt(v) if v > 0 else 1.0)

    scores: dict[tuple[int, int], float] = {}
    for i in range(n_nodes):
        for j in range(n_nodes):
            if i == j:
                continue
            num = sum((row[i] - means[i]) * (row[j] - means[j]) for row in observational)
            denom = stds[i] * stds[j] * len(observational)
            scores[(i, j)] = abs(num / denom) if denom > 0 else 0.0
    return scores


def _organ_alone_arm(
    observational: list[list[float]],
    consultable: dict[tuple[int, float], list[list[float]]],
    budget: int,
    seed: int,
    prompt_template_path: str = "prompts/prompt_organ_alone.md",
) -> dict[tuple[int, int], float]:
    """LLM-only scratchpad arm (deterministic stub for Stage 1).

    The stub returns a correlation-based prediction to exercise the prompt
    plumbing; a real LLM run replaces the backend in Stage 3.
    """
    del consultable, seed  # unused in Stage 1 stub path
    n_nodes = len(observational[0]) if observational else 0
    template = _load_prompt(prompt_template_path)
    # Render the locked prompt to exercise the template plumbing. The actual
    # Stage 1 stub ignores the rendered text and returns correlation scores.
    _ = template.format(
        step=0,
        budget=budget,
        budget_remaining=budget,
        n_nodes=n_nodes,
        n_observations=len(observational),
        belief_summary="stub belief summary for Stage 1",
    )
    return _corr_arm(observational, {})


def _organ_alone_arm_llm(
    observational: list[list[float]],
    budget: int,
    backend: Any,
    instrument: PlumbingInstrument | None,
    prompt_template_path: str = "prompts/prompt_organ_alone.md",
) -> dict[tuple[int, int], float]:
    """Real LLM organ_alone arm for Stage 3.

    Renders the locked prompt, calls the backend with no tools, parses the
    returned `final_answer.edges`, and validates node indices and confidence
    bounds. Falls back to the correlation baseline on any plumbing or parse
    failure.
    """
    n_nodes = len(observational[0]) if observational else 0
    template = _load_prompt(prompt_template_path)
    try:
        prompt = template.format(
            step=0,
            budget=budget,
            budget_remaining=budget,
            n_nodes=n_nodes,
            n_observations=len(observational),
            belief_summary="initial belief summary",
        )
    except (KeyError, ValueError, IndexError) as exc:
        if instrument is not None:
            instrument.log_unparseable(
                "organ_alone_render", f"template formatting failed: {exc}"
            )
        prompt = json.dumps(
            {
                "step": 0,
                "budget": budget,
                "n_nodes": n_nodes,
                "n_observations": len(observational),
            },
            sort_keys=True,
        )

    response = backend.call(prompt, tools=None)
    edges = _extract_final_answer_edges(response)
    if edges is not None:
        scores: dict[tuple[int, int], float] = {
            (i, j): 0.0
            for i in range(n_nodes)
            for j in range(n_nodes)
            if i != j
        }
        valid = True
        for edge in edges:
            if not isinstance(edge, (list, tuple)) or len(edge) < 3:
                valid = False
                break
            try:
                i = int(edge[0])
                j = int(edge[1])
                c = float(edge[2])
            except (TypeError, ValueError):
                valid = False
                break
            if not (0 <= i < n_nodes and 0 <= j < n_nodes and i != j and math.isfinite(c)):
                valid = False
                break
            scores[(i, j)] = min(1.0, max(0.0, c))
        if valid:
            return scores
        if instrument is not None:
            instrument.log_unparseable(
                "organ_alone_validate", "edge list contained invalid entries"
            )
    else:
        if instrument is not None:
            instrument.log_unparseable(
                "organ_alone_parse",
                "backend response missing final_answer.edges",
                {
                    "response_keys": (
                        list(response.keys()) if isinstance(response, dict) else []
                    )
                },
            )

    # Fallback to correlation baseline so the harness never crashes.
    return _corr_arm(observational, {})


def _extract_final_answer_edges(response: Any) -> list[list[Any]] | None:
    """Extract edges list from a backend final_answer response."""
    if not isinstance(response, dict):
        return None
    final = response.get("final_answer")
    if not isinstance(final, dict):
        return None
    edges = final.get("edges")
    return edges if isinstance(edges, list) else None


def _governed_loop_arm(
    observational: list[list[float]],
    consultable: dict[tuple[int, float], list[list[float]]],
    budget: int,
    seed: int,
    likelihood_mode: str = LIKELIHOOD_MODE,
) -> dict[tuple[int, int], float]:
    """Deterministic disposer arm with info-gain selection."""
    rng = random.Random(seed)
    disposer = _make_disposer(seed)
    n_nodes = len(observational[0])
    candidate_values: dict[int, list[float]] = {}
    for (target, value), _ in consultable.items():
        candidate_values.setdefault(target, []).append(value)

    observations: list[list[float]] = [list(r) for r in observational]
    dibs = GovernedDiBS(
        n_nodes=n_nodes,
        n_particles=N_PARTICLES,
        seed=seed,
        likelihood_mode=likelihood_mode,
    )
    dibs.update(observations)

    for step in range(budget):
        node, value, eig = dibs.select_intervention(
            observations, candidate_values, n_mc_samples=N_MC_SAMPLES
        )
        if eig <= 0.0:
            break
        key = (node, value)
        if key not in consultable:
            break
        if disposer(node, risk_tier=1) != "ALLOW":
            break
        sampled = rng.choice(consultable[key])
        observations.append(list(sampled))
        dibs = GovernedDiBS(
            n_nodes=n_nodes,
            n_particles=N_PARTICLES,
            seed=seed + step + 1,
            likelihood_mode=likelihood_mode,
        )
        dibs.update(observations)

    return dibs.edge_marginals()


def _passive_loop_arm(
    observational: list[list[float]],
    consultable: dict[tuple[int, float], list[list[float]]],
    budget: int,
    seed: int,
    likelihood_mode: str = LIKELIHOOD_MODE,
) -> dict[tuple[int, int], float]:
    """Same as governed_loop but with random intervention selection."""
    rng = random.Random(seed)
    disposer = _make_disposer(seed)
    n_nodes = len(observational[0])
    keys = list(consultable.keys())

    observations: list[list[float]] = [list(r) for r in observational]
    dibs = GovernedDiBS(
        n_nodes=n_nodes,
        n_particles=N_PARTICLES,
        seed=seed,
        likelihood_mode=likelihood_mode,
    )
    dibs.update(observations)

    for step in range(budget):
        if not keys:
            break
        node, value = rng.choice(keys)
        key = (node, value)
        if disposer(node, risk_tier=1) != "ALLOW":
            break
        sampled = rng.choice(consultable[key])
        observations.append(list(sampled))
        dibs = GovernedDiBS(
            n_nodes=n_nodes,
            n_particles=N_PARTICLES,
            seed=seed + step + 1,
            likelihood_mode=likelihood_mode,
        )
        dibs.update(observations)

    return dibs.edge_marginals()


def _split_interventions(
    interventions: dict[tuple[int, float], list[list[float]]], seed: int
) -> tuple[dict[tuple[int, float], list[list[float]]], dict[tuple[int, float], list[list[float]]]]:
    """Split interventions into consultable set S and held-out set T."""
    keys = list(interventions.keys())
    rng = random.Random(seed)
    rng.shuffle(keys)
    mid = len(keys) // 2
    consultable = {k: interventions[k] for k in keys[:mid]}
    held_out = {k: interventions[k] for k in keys[mid:]}
    return consultable, held_out


def _parse_intervention_key(key: str) -> tuple[int, float]:
    """Convert 'idx:ko' string to (node_index, value) tuple."""
    parts = key.split(":")
    if len(parts) != 2:
        raise ValueError(f"Invalid intervention key: {key}")
    return int(parts[0]), 1.0


def _load_stage4_preprocessed(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    consultable = {
        _parse_intervention_key(k): [list(row) for row in v]
        for k, v in data["consultable_interventions"].items()
    }
    held_out = {
        _parse_intervention_key(k): [list(row) for row in v]
        for k, v in data["held_out_interventions"].items()
    }
    observational = [list(row) for row in data["observational_cells"]]
    return {
        "observational": observational,
        "consultable": consultable,
        "held_out": held_out,
        "selected_genes": data["selected_genes"],
        "consultable_targets": data.get("consultable_targets", []),
        "held_out_targets": data.get("held_out_targets", []),
        "metadata": {
            "accession": data.get("accession"),
            "publication": data.get("publication"),
            "pathway": data.get("pathway"),
            "pathway_id": data.get("pathway_id"),
            "sample": data.get("sample"),
        },
    }


def _score_arm(
    edge_scores: dict[tuple[int, int], float],
    held_out: dict[tuple[int, float], list[list[float]]],
    observational: list[list[float]],
    effect_threshold: float,
) -> tuple[float, int, int]:
    result = score_structure(
        edge_scores,
        held_out,
        observational,
        effect_threshold=effect_threshold,
    )
    return result.ap, result.shd, result.n_true


def _run_seed_k(
    seed: int,
    k: int,
    stage: int,
    config: dict[str, Any],
    backend: Any,
    instruments: dict[str, PlumbingInstrument],
) -> dict[str, Any]:
    """Run all arms for one (seed, k) pair."""
    n_obs = config["n_obs"]
    budget = config["budget"]
    likelihood_mode = config["likelihood_mode"]
    score_effect_threshold = config["score_effect_threshold"]
    empirical_effect_threshold = config["empirical_effect_threshold"]

    world = generate_scm(
        SCMConfig(n_nodes=k, n_obs=n_obs, seed=seed)
    )
    consultable, held_out = _split_interventions(world.interventions, seed=seed + 999)

    arm_results: dict[str, dict[str, Any]] = {}
    plumbing: dict[str, dict[str, Any]] = {}

    # corr
    corr_scores = _corr_arm(world.observational, held_out)
    ap, shd, n_true = _score_arm(corr_scores, held_out, world.observational, score_effect_threshold)
    arm_results["corr"] = {"ap": ap, "shd": shd, "interventions_spent": 0}

    # organ_alone
    start = time.perf_counter()
    if stage == 3:
        alone_scores = _organ_alone_arm_llm(
            world.observational,
            budget,
            backend,
            instruments.get("organ_alone"),
        )
    else:
        alone_scores = _organ_alone_arm(
            world.observational, consultable, budget, seed
        )
    ap, shd, _ = _score_arm(alone_scores, held_out, world.observational, score_effect_threshold)
    arm_results["organ_alone"] = {
        "ap": ap,
        "shd": shd,
        "interventions_spent": 0,
        "wall_time_ms": round((time.perf_counter() - start) * 1000, 3),
    }
    plumbing["organ_alone"] = _instrument_summary(instruments.get("organ_alone"))

    # organ_tools
    start = time.perf_counter()
    tools_result = run_organ_tools(
        world.observational,
        consultable,
        budget=budget,
        backend=backend,
        instrument=instruments.get("organ_tools"),
        n_particles=N_PARTICLES,
        seed=seed,
        n_mc_samples=N_MC_SAMPLES,
        prompt_template_path="prompts/prompt_organ_tools.md",
        likelihood_mode=likelihood_mode,
    )
    ap, shd, _ = _score_arm(tools_result.edge_scores, held_out, world.observational, score_effect_threshold)
    arm_results["organ_tools"] = {
        "ap": ap,
        "shd": shd,
        "interventions_spent": tools_result.interventions_spent,
        "wall_time_ms": round((time.perf_counter() - start) * 1000, 3),
        "plumbing_counts": tools_result.plumbing_counts,
    }
    plumbing["organ_tools"] = _instrument_summary(instruments.get("organ_tools"))

    # organ_tools_externalized
    start = time.perf_counter()
    ext_backend = _ExternalizedBackendAdapter(backend)
    ext_result = run_organ_tools_externalized(
        world.observational,
        consultable,
        budget=budget,
        backend=ext_backend,
        instrument=instruments.get("organ_tools_externalized"),
        n_particles=N_PARTICLES,
        seed=seed,
        n_mc_samples=N_MC_SAMPLES,
        likelihood_mode=likelihood_mode,
    )
    ap, shd, _ = _score_arm(ext_result.edge_scores, held_out, world.observational, score_effect_threshold)
    arm_results["organ_tools_externalized"] = {
        "ap": ap,
        "shd": shd,
        "interventions_spent": ext_result.interventions_spent,
        "wall_time_ms": round((time.perf_counter() - start) * 1000, 3),
        "plumbing_counts": ext_result.plumbing_counts,
    }
    plumbing["organ_tools_externalized"] = _instrument_summary(instruments.get("organ_tools_externalized"))

    # governed_loop
    start = time.perf_counter()
    loop_scores = _governed_loop_arm(
        world.observational, consultable, budget, seed, likelihood_mode=likelihood_mode
    )
    ap, shd, _ = _score_arm(loop_scores, held_out, world.observational, score_effect_threshold)
    arm_results["governed_loop"] = {
        "ap": ap,
        "shd": shd,
        "interventions_spent": budget,
        "wall_time_ms": round((time.perf_counter() - start) * 1000, 3),
    }

    # passive_loop
    start = time.perf_counter()
    passive_scores = _passive_loop_arm(
        world.observational, consultable, budget, seed, likelihood_mode=likelihood_mode
    )
    ap, shd, _ = _score_arm(passive_scores, held_out, world.observational, score_effect_threshold)
    arm_results["passive_loop"] = {
        "ap": ap,
        "shd": shd,
        "interventions_spent": budget,
        "wall_time_ms": round((time.perf_counter() - start) * 1000, 3),
    }

    # learned_select
    start = time.perf_counter()
    learned_result = run_learned_select(
        world.observational,
        consultable,
        budget=budget,
        seed=seed,
        n_particles=N_PARTICLES,
        ucb_alpha=UCB_ALPHA,
        disposer=_make_disposer(seed),
    )
    ap, shd, _ = _score_arm(learned_result.edge_scores, held_out, world.observational, score_effect_threshold)
    arm_results["learned_select"] = {
        "ap": ap,
        "shd": shd,
        "interventions_spent": learned_result.interventions_spent,
        "wall_time_ms": round((time.perf_counter() - start) * 1000, 3),
    }

    # Placebo sanity check
    placebo_interv, placebo_obs = generate_placebo(
        world.observational, world.interventions, seed=seed + 111
    )
    placebo_validation = validate_placebo_nonidentifiability(
        world.observational, placebo_obs, placebo_interv
    )

    return {
        "seed": seed,
        "k": k,
        "arm_results": arm_results,
        "plumbing": plumbing,
        "placebo_passes": placebo_validation.passes,
        "placebo_ap": placebo_validation.max_ap,
        "placebo_cov_distance": placebo_validation.covariance_distance,
        "n_true": n_true,
        "linear_gaussian_avg_r2": sum(
            residual_linear_gaussian_fit(world.observational, world.dag).values()
        )
        / k,
    }


def _run_stage4(
    preprocessed: dict[str, Any],
    config: dict[str, Any],
    backend: Any,
    instruments: dict[str, PlumbingInstrument],
) -> dict[str, Any]:
    """Run all arms on real preprocessed Perturb-seq data."""
    observational = preprocessed["observational"]
    consultable = preprocessed["consultable"]
    held_out = preprocessed["held_out"]
    budget = config["budget"]
    likelihood_mode = config["likelihood_mode"]
    score_effect_threshold = config["score_effect_threshold"]

    n_nodes = len(observational[0]) if observational else 0
    arm_results: dict[str, dict[str, Any]] = {}
    plumbing: dict[str, dict[str, Any]] = {}

    # corr baseline
    corr_scores = _corr_arm(observational, held_out)
    ap, shd, n_true = _score_arm(corr_scores, held_out, observational, score_effect_threshold)
    arm_results["corr"] = {"ap": ap, "shd": shd, "interventions_spent": 0}

    # organ_alone
    start = time.perf_counter()
    if getattr(backend, "stub_only", True):
        alone_scores = _organ_alone_arm(observational, consultable, budget, 0)
    else:
        alone_scores = _organ_alone_arm_llm(
            observational, budget, backend, instruments.get("organ_alone")
        )
    ap, shd, _ = _score_arm(alone_scores, held_out, observational, score_effect_threshold)
    arm_results["organ_alone"] = {
        "ap": ap,
        "shd": shd,
        "interventions_spent": 0,
        "wall_time_ms": round((time.perf_counter() - start) * 1000, 3),
    }
    plumbing["organ_alone"] = _instrument_summary(instruments.get("organ_alone"))

    # organ_tools
    start = time.perf_counter()
    tools_result = run_organ_tools(
        observational,
        consultable,
        budget=budget,
        backend=backend,
        instrument=instruments.get("organ_tools"),
        n_particles=N_PARTICLES,
        seed=0,
        n_mc_samples=N_MC_SAMPLES,
        prompt_template_path="prompts/prompt_organ_tools.md",
        likelihood_mode=likelihood_mode,
    )
    ap, shd, _ = _score_arm(tools_result.edge_scores, held_out, observational, score_effect_threshold)
    arm_results["organ_tools"] = {
        "ap": ap,
        "shd": shd,
        "interventions_spent": tools_result.interventions_spent,
        "wall_time_ms": round((time.perf_counter() - start) * 1000, 3),
        "plumbing_counts": tools_result.plumbing_counts,
    }
    plumbing["organ_tools"] = _instrument_summary(instruments.get("organ_tools"))

    # organ_tools_externalized
    start = time.perf_counter()
    ext_backend = _ExternalizedBackendAdapter(backend)
    ext_result = run_organ_tools_externalized(
        observational,
        consultable,
        budget=budget,
        backend=ext_backend,
        instrument=instruments.get("organ_tools_externalized"),
        n_particles=N_PARTICLES,
        seed=0,
        n_mc_samples=N_MC_SAMPLES,
        likelihood_mode=likelihood_mode,
    )
    ap, shd, _ = _score_arm(ext_result.edge_scores, held_out, observational, score_effect_threshold)
    arm_results["organ_tools_externalized"] = {
        "ap": ap,
        "shd": shd,
        "interventions_spent": ext_result.interventions_spent,
        "wall_time_ms": round((time.perf_counter() - start) * 1000, 3),
        "plumbing_counts": ext_result.plumbing_counts,
    }
    plumbing["organ_tools_externalized"] = _instrument_summary(instruments.get("organ_tools_externalized"))

    # governed_loop
    start = time.perf_counter()
    loop_scores = _governed_loop_arm(
        observational, consultable, budget, seed=0, likelihood_mode=likelihood_mode
    )
    ap, shd, _ = _score_arm(loop_scores, held_out, observational, score_effect_threshold)
    arm_results["governed_loop"] = {
        "ap": ap,
        "shd": shd,
        "interventions_spent": budget,
        "wall_time_ms": round((time.perf_counter() - start) * 1000, 3),
    }

    # passive_loop
    start = time.perf_counter()
    passive_scores = _passive_loop_arm(
        observational, consultable, budget, seed=0, likelihood_mode=likelihood_mode
    )
    ap, shd, _ = _score_arm(passive_scores, held_out, observational, score_effect_threshold)
    arm_results["passive_loop"] = {
        "ap": ap,
        "shd": shd,
        "interventions_spent": budget,
        "wall_time_ms": round((time.perf_counter() - start) * 1000, 3),
    }

    # learned_select
    start = time.perf_counter()
    learned_result = run_learned_select(
        observational,
        consultable,
        budget=budget,
        seed=0,
        n_particles=N_PARTICLES,
        ucb_alpha=UCB_ALPHA,
        disposer=_make_disposer(0),
    )
    ap, shd, _ = _score_arm(learned_result.edge_scores, held_out, observational, score_effect_threshold)
    arm_results["learned_select"] = {
        "ap": ap,
        "shd": shd,
        "interventions_spent": learned_result.interventions_spent,
        "wall_time_ms": round((time.perf_counter() - start) * 1000, 3),
    }

    return {
        "seed": 0,
        "k": n_nodes,
        "arm_results": arm_results,
        "plumbing": plumbing,
        "selected_genes": preprocessed["selected_genes"],
        "consultable_targets": preprocessed["consultable_targets"],
        "held_out_targets": preprocessed["held_out_targets"],
        "n_true": n_true,
    }


def _instrument_summary(instrument: PlumbingInstrument | None) -> dict[str, Any]:
    if instrument is None:
        return {"has_plumbing_failure": False, "counts": {}}
    return {
        "has_plumbing_failure": instrument.has_plumbing_failure(),
        "counts": instrument.counts(),
    }


@dataclass
class _ExternalizedBackendAdapter:
    """Wrap a chat backend as an externalized-belief decision backend."""

    inner: Any

    def decide(
        self,
        ledger_summary: dict[str, Any],
        candidate_interventions: dict[int, list[float]],
    ) -> dict[str, Any]:
        # In stub mode the inner backend cannot produce a real externalized
        # decision, so short-circuit to a deterministic info_gain request to
        # preserve the execution path without emitting spurious plumbing failures.
        if getattr(self.inner, "stub_only", False):
            return {"action": "info_gain", "n_mc_samples": N_MC_SAMPLES}
        prompt = json.dumps(
            {
                "ledger": ledger_summary,
                "candidate_interventions": candidate_interventions,
                "instruction": (
                    "Return either a tool decision "
                    '{"action": "info_gain", "n_mc_samples": N} or a final answer '
                    '{"final_answer": {"edges": [[i, j, confidence], ...]}}.'
                ),
            },
            sort_keys=True,
        )
        return dict(self.inner.call(prompt, tools=None))


def _c7_halt_test() -> bool:
    """C7 halt/rollback smoke test: a forbidden action index must be denied."""
    from aac.governed_gate import GovernedDecisionGate
    from aac.self_model import ActionRequest, AgentSelfModel

    self_model = AgentSelfModel(
        allowed_tools=frozenset({"test_forbidden"}),
        denied_tools=frozenset(),
        risk_ceiling=5,
        approval_required_at_or_above=5,
        evidence_requirements={1: 1},
        confidence_thresholds={1: 0.5},
    )
    gate = GovernedDecisionGate(self_model=self_model)
    req = ActionRequest(
        action="test_forbidden",
        risk_tier=1,
        confidence=0.9,
        verified=True,
        evidence_count=5,
        approved=True,
        action_index=999,
    )
    shell_view = type("Shell", (), {"forbidden": frozenset({999})})()
    decision = gate.decide(req, shell_view=shell_view)
    return decision.verdict == "DENY"


def _hyperparameter_hash_stage1() -> str:
    """Hash of byte-identical hyperparameters across all k (Stage 1)."""
    params = {
        "N_PARTICLES": N_PARTICLES,
        "N_MC_SAMPLES": N_MC_SAMPLES,
        "UCB_ALPHA": UCB_ALPHA,
        "BUDGET": BUDGET,
        "LIKELIHOOD_MODE": LIKELIHOOD_MODE,
        "SCORE_EFFECT_THRESHOLD": SCORE_EFFECT_THRESHOLD,
        "EMPIRICAL_EFFECT_THRESHOLD": EMPIRICAL_EFFECT_THRESHOLD,
    }
    return hashlib.sha256(
        json.dumps(params, sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]


def _hyperparameter_hash_stage3(spec: dict[str, Any], seeds: list[int]) -> str:
    """Hash of locked Stage 3 hyperparameters and seed list."""
    params = {
        "ks": spec.get("ks", []),
        "n_obs": spec.get("n_obs", 0),
        "budget": spec["budget"],
        "likelihood_mode": spec["likelihood_mode"],
        "score_effect_threshold": spec["score_effect_threshold"],
        "empirical_effect_threshold": spec["empirical_effect_threshold"],
        "model_lock": spec.get("model_lock", ""),
        "temperature": spec.get("temperature", 0.0),
        "max_tokens": spec.get("max_tokens", 0),
        "N_PARTICLES": N_PARTICLES,
        "N_MC_SAMPLES": N_MC_SAMPLES,
        "UCB_ALPHA": UCB_ALPHA,
        "seeds": seeds,
    }
    return hashlib.sha256(
        json.dumps(params, sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]


def _summarize_plumbing(instruments: list[PlumbingInstrument]) -> dict[str, Any]:
    """Aggregate plumbing event counts across all arms and seeds."""
    total_counts: dict[str, int] = {}
    total_events = 0
    total_plumbing_failures = 0
    for instr in instruments:
        for kind, count in instr.counts().items():
            total_counts[kind] = total_counts.get(kind, 0) + count
            total_events += count
        total_plumbing_failures += sum(
            1 for e in instr.events if e.kind in {"truncated", "timeout", "unparseable"}
        )
    return {
        "total_counts": total_counts,
        "total_events": total_events,
        "total_plumbing_failures": total_plumbing_failures,
        "total_organ_calls": total_events,
        "failure_rate": (
            total_plumbing_failures / total_events if total_events > 0 else 0.0
        ),
    }


def _load_stage3_seeds(path: str) -> list[int]:
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    seeds = data["seeds"]
    expected = data["sha256"]
    actual = hashlib.sha256(
        json.dumps(seeds).encode("utf-8")
    ).hexdigest()
    if actual != expected:
        raise ValueError(
            f"Seed digest mismatch in {path}: expected {expected}, got {actual}"
        )
    return seeds


def _load_stage3_spec(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _make_stage3_config(spec: dict[str, Any]) -> dict[str, Any]:
    return {
        "n_obs": spec.get("n_obs", 0),
        "budget": spec["budget"],
        "likelihood_mode": spec["likelihood_mode"],
        "score_effect_threshold": spec["score_effect_threshold"],
        "empirical_effect_threshold": spec["empirical_effect_threshold"],
    }


def _make_stage4_config(spec: dict[str, Any]) -> dict[str, Any]:
    return {
        "budget": spec["budget"],
        "likelihood_mode": spec["likelihood_mode"],
        "score_effect_threshold": spec["score_effect_threshold"],
        "empirical_effect_threshold": spec["empirical_effect_threshold"],
    }


def main() -> int:
    args = _parse_args()

    if args.stage == 1:
        seeds = SEEDS
        ks = KS
        spec: dict[str, Any] | None = None
        result_path = args.result_path or "experiments/strong_locus_structure_crossover.result.json"
        backend = build_backend("stub")
        hyperparameter_hash = _hyperparameter_hash_stage1()
        config = {
            "n_obs": 200,
            "budget": BUDGET,
            "likelihood_mode": LIKELIHOOD_MODE,
            "score_effect_threshold": SCORE_EFFECT_THRESHOLD,
            "empirical_effect_threshold": EMPIRICAL_EFFECT_THRESHOLD,
        }
    elif args.stage == 4:
        spec = _load_stage3_spec(args.spec)
        preprocessed = _load_stage4_preprocessed(args.preprocessed)
        result_path = args.result_path or "experiments/strong_locus_stage4.result.json"
        backend = build_backend(args.backend)
        hyperparameter_hash = _hyperparameter_hash_stage3(spec, [0])
        config = _make_stage4_config(spec)
    else:
        spec = _load_stage3_spec(args.spec)
        seeds = _load_stage3_seeds(args.seeds)
        ks = spec["ks"]
        result_path = args.result_path or "experiments/strong_locus_stage3.result.json"
        backend = build_backend(args.backend)
        hyperparameter_hash = _hyperparameter_hash_stage3(spec, seeds)
        config = _make_stage3_config(spec)

    stub_only = getattr(backend, "stub_only", False)

    all_instruments: list[PlumbingInstrument] = []
    results: list[dict[str, Any]] = []

    if args.stage == 4:
        print("Running Stage 4 real-data harness ...")
        instruments = {
            "organ_alone": PlumbingInstrument(run_id="stage4-0", arm="organ_alone"),
            "organ_tools": PlumbingInstrument(run_id="stage4-0", arm="organ_tools"),
            "organ_tools_externalized": PlumbingInstrument(
                run_id="stage4-0", arm="organ_tools_externalized"
            ),
        }
        all_instruments.extend(instruments.values())
        results.append(_run_stage4(preprocessed, config, backend, instruments))
        for instr in instruments.values():
            instr.dump(args.plumbing_path)
    else:
        for seed in seeds:
            for k in ks:
                print(f"Running seed={seed}, k={k} ...")
                instruments = {
                    "organ_alone": PlumbingInstrument(run_id=f"{seed}-{k}", arm="organ_alone"),
                    "organ_tools": PlumbingInstrument(run_id=f"{seed}-{k}", arm="organ_tools"),
                    "organ_tools_externalized": PlumbingInstrument(
                        run_id=f"{seed}-{k}", arm="organ_tools_externalized"
                    ),
                }
                all_instruments.extend(instruments.values())
                results.append(
                    _run_seed_k(seed, k, args.stage, config, backend, instruments)
                )
                for instr in instruments.values():
                    instr.dump(args.plumbing_path)

    c7_passes = _c7_halt_test()

    plumbing_summary = _summarize_plumbing(all_instruments)

    output: dict[str, Any] = {
        "experiment": "strong-locus-structure-crossover",
        "stage": args.stage,
        "backend": args.backend if args.stage in (3, 4) else "stub",
        "stub_only": stub_only,
        "hyperparameter_hash": hyperparameter_hash,
        "c7_halt_test_passes": c7_passes,
        "plumbing_summary": plumbing_summary,
        "results": results,
    }

    if args.stage == 1:
        output["hyperparameters"] = {
            "N_PARTICLES": N_PARTICLES,
            "N_MC_SAMPLES": N_MC_SAMPLES,
            "UCB_ALPHA": UCB_ALPHA,
            "BUDGET": BUDGET,
            "LIKELIHOOD_MODE": LIKELIHOOD_MODE,
            "SCORE_EFFECT_THRESHOLD": SCORE_EFFECT_THRESHOLD,
            "EMPIRICAL_EFFECT_THRESHOLD": EMPIRICAL_EFFECT_THRESHOLD,
            "SEEDS": SEEDS,
            "KS": KS,
        }
    elif args.stage == 4:
        output["hyperparameters"] = {
            "N_PARTICLES": N_PARTICLES,
            "N_MC_SAMPLES": N_MC_SAMPLES,
            "UCB_ALPHA": UCB_ALPHA,
            "BUDGET": config["budget"],
            "LIKELIHOOD_MODE": config["likelihood_mode"],
            "SCORE_EFFECT_THRESHOLD": config["score_effect_threshold"],
            "EMPIRICAL_EFFECT_THRESHOLD": config["empirical_effect_threshold"],
            "MODEL_LOCK": spec["model_lock"] if spec else None,
            "TEMPERATURE": spec["temperature"] if spec else None,
            "MAX_TOKENS": spec["max_tokens"] if spec else None,
            "PREPROCESSED": args.preprocessed,
        }
        output["spec_path"] = args.spec
        output["plumbing_path"] = args.plumbing_path
        output["preprocessed_metadata"] = preprocessed["metadata"]
    else:
        output["hyperparameters"] = {
            "N_PARTICLES": N_PARTICLES,
            "N_MC_SAMPLES": N_MC_SAMPLES,
            "UCB_ALPHA": UCB_ALPHA,
            "BUDGET": config["budget"],
            "LIKELIHOOD_MODE": config["likelihood_mode"],
            "SCORE_EFFECT_THRESHOLD": config["score_effect_threshold"],
            "EMPIRICAL_EFFECT_THRESHOLD": config["empirical_effect_threshold"],
            "SEEDS": seeds,
            "KS": ks,
            "MODEL_LOCK": spec["model_lock"] if spec else None,
            "TEMPERATURE": spec["temperature"] if spec else None,
            "MAX_TOKENS": spec["max_tokens"] if spec else None,
        }
        output["spec_path"] = args.spec
        output["seeds_path"] = args.seeds
        output["plumbing_path"] = args.plumbing_path

    with open(result_path, "w", encoding="utf-8") as fh:
        json.dump(output, fh, indent=2, sort_keys=True)

    print(json.dumps(output, indent=2, sort_keys=True))
    print(f"\nWrote {result_path}")
    return 0 if c7_passes else 1


if __name__ == "__main__":
    raise SystemExit(main())
