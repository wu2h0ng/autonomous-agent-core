"""End-to-end harness: simulation env → external queue adapter → CWM loop → metrics.

This demonstrates the full ADR-0052/0053 pipeline in a controlled setting:

1. A ``CausalSimulationEnv`` acts as the real world.
2. A ``QueueInterventionAdapter`` + worker thread act as the external adapter.
3. A ``GovernedInterventionBinding`` enforces C7 policy.
4. ``OnlineInteractiveDiscoveryLoop`` proposes interventions, receives samples, and
   updates the CWM posterior.
5. ``predictive_validation_score`` / ``interventional_agreement_score`` score the
   predicted DAG without ground truth.

The simulation is the only source of truth; the loop only sees what the adapter
returns.  No real external system is contacted.
"""
from __future__ import annotations

import queue
import threading
from dataclasses import dataclass, field
from typing import Any, Callable

from adapters.queue_adapter import QueueInterventionAdapter
from aac.cwm_evaluation import (
    interventional_agreement_score,
    predictive_validation_score,
)
from aac.interactive_discovery_loop import OnlineInteractiveDiscoveryLoop
from aac.live_env_harness import _precision_recall_f1
from aac.live_intervention_env import CausalSimulationEnv
from aac.real_data_intervention_env import (
    GovernedInterventionBinding,
    InterventionOutcome,
)


@dataclass
class AdapterLoopResult:
    """Result of a closed-loop adapter harness run."""

    predicted_edges: set[tuple[int, int]]
    ground_truth_edges: set[tuple[int, int]]
    shd: int
    precision: float
    recall: float
    f1: float
    confidence: float
    interventions_spent: int
    predictive_validation: dict[str, Any]
    interventional_agreement: dict[str, Any]
    obs: list[list[float]] = field(repr=False)
    int_data: list[tuple[int, float, list[float]]] = field(repr=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "predicted_edges": sorted(self.predicted_edges),
            "ground_truth_edges": sorted(self.ground_truth_edges),
            "shd": self.shd,
            "precision": self.precision,
            "recall": self.recall,
            "f1": self.f1,
            "confidence": self.confidence,
            "interventions_spent": self.interventions_spent,
            "predictive_validation": self.predictive_validation,
            "interventional_agreement": self.interventional_agreement,
        }


def run_queue_adapter_harness(
    env_factory: Callable[[int], CausalSimulationEnv],
    seed: int = 42,
    n_obs_initial: int = 80,
    rounds: int = 3,
    n_obs_per_round: int = 60,
    interventions_per_round: int = 4,
    budget: int = 12,
    n_particles: int = 40,
    confidence_threshold: float = 0.95,
    worker_timeout: float = 10.0,
) -> AdapterLoopResult:
    """Run the online discovery loop through a queue adapter against a simulator.

    The worker thread is the "external system": it consumes intervention
    requests from the request queue, applies them in the simulator, and puts the
    resulting sample on the read-back queue.
    """
    env = env_factory(seed)
    n_nodes = env.n_nodes

    # Pre-fill the observation queue with enough rows for the whole run.
    total_obs = n_obs_initial + rounds * n_obs_per_round
    obs = env.observe(total_obs)
    obs_queue: queue.Queue = queue.Queue()
    for row in obs:
        obs_queue.put(row)

    req_queue: queue.Queue = queue.Queue()
    rb_queue: queue.Queue = queue.Queue()

    int_data: list[tuple[int, float, list[float]]] = []

    def audit_callback(outcome: InterventionOutcome) -> None:
        if outcome.sample is not None and outcome.status == "applied":
            int_data.append(
                (outcome.proposal.node, outcome.proposal.value, outcome.sample)
            )

    def worker() -> None:
        while True:
            try:
                req = req_queue.get(timeout=worker_timeout)
            except queue.Empty:
                break
            if req is None:
                break
            sample = env.intervene(req["node"], req["value"])
            rb_queue.put(sample)

    worker_thread = threading.Thread(target=worker)
    worker_thread.start()

    adapter = QueueInterventionAdapter(
        n_nodes=n_nodes,
        observed_variables=[f"x{i}" for i in range(n_nodes)],
        allowed_handles=set(range(n_nodes)),
        safe_value_ranges={i: (-3.0, 3.0) for i in range(n_nodes)},
        observe_queue=obs_queue,
        intervene_request_queue=req_queue,
        readback_queue=rb_queue,
        timeout=5.0,
    )

    binding = GovernedInterventionBinding(
        env=adapter,
        dry_run=False,
        budget=budget,
        approval=lambda _p: True,
        audit=audit_callback,
    )

    loop = OnlineInteractiveDiscoveryLoop(
        organs=[],
        environment=binding,
        budget=budget,
        confidence_threshold=confidence_threshold,
        seed=seed,
        n_particles=n_particles,
        likelihood_mode="linear",
        max_window_size=120,
    )

    try:
        results = loop.discover_online(
            rounds=rounds,
            n_obs_per_round=n_obs_per_round,
            interventions_per_round=interventions_per_round,
        )
    finally:
        req_queue.put(None)
        worker_thread.join(timeout=worker_timeout + 2.0)

    final = results[-1]
    predicted = set(final.best_dag or [])
    truth = env.ground_truth_edges
    precision, recall, f1 = _precision_recall_f1(predicted, truth, n_nodes)

    pv = predictive_validation_score(obs, int_data, predicted)
    ia = interventional_agreement_score(obs, int_data, predicted)

    return AdapterLoopResult(
        predicted_edges=predicted,
        ground_truth_edges=truth,
        shd=env.structural_hamming_distance(predicted),
        precision=precision,
        recall=recall,
        f1=f1,
        confidence=round(final.confidence, 4),
        interventions_spent=sum(r.interventions_spent for r in results),
        predictive_validation=pv,
        interventional_agreement=ia,
        obs=obs,
        int_data=int_data,
    )


def _default_env_factory(seed: int) -> CausalSimulationEnv:
    return CausalSimulationEnv(
        n_nodes=4,
        edges={(0, 1), (1, 2), (2, 3)},
        seed=seed,
        noise_std=0.2,
        coef_range=(0.8, 0.8),
    )


def run_csv_adapter_harness(
    env_factory: Callable[[int], CausalSimulationEnv],
    seed: int = 42,
    n_obs: int = 200,
    budget: int = 12,
    rounds: int = 3,
    n_obs_per_round: int = 60,
    interventions_per_round: int = 4,
    n_particles: int = 40,
    confidence_threshold: float = 0.95,
) -> AdapterLoopResult:
    """Run the online discovery loop through a CSV adapter against a simulator.

    This simulates the real-world CSV workflow: an external process has already
    collected observations into a CSV and produced a read-back CSV of
    post-intervention samples for a grid of candidate interventions.  The loop
    queries observations and reads back samples from the CSV files.
    """
    import csv
    import os
    import statistics
    import tempfile

    from adapters.csv_adapter import CSVInterventionAdapter

    env = env_factory(seed)
    n_nodes = env.n_nodes
    obs = env.observe(n_obs)

    with tempfile.TemporaryDirectory() as tmp:
        obs_path = os.path.join(tmp, "obs.csv")
        rb_path = os.path.join(tmp, "readback.csv")
        log_path = os.path.join(tmp, "interventions.csv")

        # Write observations CSV.
        with open(obs_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([f"x{i}" for i in range(n_nodes)])
            for row in obs:
                writer.writerow(row)

        # Build a read-back grid from observational marginals.
        candidate_values: dict[int, list[float]] = {}
        for j in range(n_nodes):
            col = [row[j] for row in obs]
            mu = statistics.mean(col)
            sd = statistics.pstdev(col) or 1.0
            lo = round(mu - 3 * sd, 1)
            hi = round(mu + 3 * sd, 1)
            candidate_values[j] = sorted(
                {round(lo + 0.1 * k, 1) for k in range(int((hi - lo) * 10) + 1)}
            )

        with open(rb_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["node", "value"] + [f"x{i}" for i in range(n_nodes)])
            for node in range(n_nodes):
                for value in candidate_values[node]:
                    sample = env.intervene(node, value)
                    writer.writerow([node, value] + sample)

        int_data: list[tuple[int, float, list[float]]] = []

        def audit_callback(outcome: InterventionOutcome) -> None:
            if outcome.sample is not None and outcome.status == "applied":
                int_data.append(
                    (outcome.proposal.node, outcome.proposal.value, outcome.sample)
                )

        adapter = CSVInterventionAdapter(
            n_nodes=n_nodes,
            observed_variables=[f"x{i}" for i in range(n_nodes)],
            allowed_handles=set(range(n_nodes)),
            safe_value_ranges={i: (-3.0, 3.0) for i in range(n_nodes)},
            observation_path=obs_path,
            intervention_log_path=log_path,
            readback_path=rb_path,
        )

        binding = GovernedInterventionBinding(
            env=adapter,
            dry_run=False,
            budget=budget,
            approval=lambda _p: True,
            audit=audit_callback,
        )

        loop = OnlineInteractiveDiscoveryLoop(
            organs=[],
            environment=binding,
            budget=budget,
            confidence_threshold=confidence_threshold,
            seed=seed,
            n_particles=n_particles,
            likelihood_mode="linear",
            max_window_size=120,
        )

        results = loop.discover_online(
            rounds=rounds,
            n_obs_per_round=n_obs_per_round,
            interventions_per_round=interventions_per_round,
        )

    final = results[-1]
    predicted = set(final.best_dag or [])
    truth = env.ground_truth_edges
    precision, recall, f1 = _precision_recall_f1(predicted, truth, n_nodes)

    pv = predictive_validation_score(obs, int_data, predicted)
    ia = interventional_agreement_score(obs, int_data, predicted)

    return AdapterLoopResult(
        predicted_edges=predicted,
        ground_truth_edges=truth,
        shd=env.structural_hamming_distance(predicted),
        precision=precision,
        recall=recall,
        f1=f1,
        confidence=round(final.confidence, 4),
        interventions_spent=sum(r.interventions_spent for r in results),
        predictive_validation=pv,
        interventional_agreement=ia,
        obs=obs,
        int_data=int_data,
    )


if __name__ == "__main__":
    import json

    output = {
        "queue": run_queue_adapter_harness(_default_env_factory, seed=42).to_dict(),
        "csv": run_csv_adapter_harness(_default_env_factory, seed=42).to_dict(),
    }
    print(json.dumps(output, indent=2))
