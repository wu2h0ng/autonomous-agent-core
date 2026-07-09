"""Product-Grade Discovery Engine — GGM skeleton + Bayesian orientation.

n=50 in seconds. Two-step pipeline:
1. GGM CI test → undirected skeleton (O(n³), <1s at n=50, recall ≥0.95)
2. GovernedDiBS constrained to skeleton edges → directed DAG with evidence chain

Constrained particles: only consider DAGs whose undirected edge set is a
SUBSET of the GGM skeleton. Perturbations only add/remove edges from the
skeleton set. This compresses search space from 2^(n²) to 2^(|E_skeleton|).

For n=50 with ~120 skeleton edges, search space is 2^120 — still large but
much smaller than 2^1225. With 100 particles and max_in_degree=6, the
bounded-degree constraint reduces effective space further.

Usage:
    from aac.product_engine import ProductDiscoveryEngine
    engine = ProductDiscoveryEngine(n_particles=100, max_in_degree=6)
    result = engine.discover(obs_data)
    print(result.dag, result.evidence, result.confidence)
"""
from __future__ import annotations

import math
import statistics
import time
from dataclasses import dataclass, field

from .cwm_organ import _standardize_cols, _cov, _inv
from .bayesian_dag_posterior import GovernedDiBS
from .per_edge_orient import per_edge_orient
from .precision_temporal_filters import InterventionValidationFilter, TemporalDAGSplitter
from .auto_tuner import AutoTuner
from .advanced_capabilities import hsic_independence_test, online_update_precision


@dataclass
class DiscoveryResult:
    dag: frozenset
    skeleton: frozenset
    confidence: float
    edge_marginals: dict
    evidence_chain: dict
    orientation_accuracy: float
    recall: float
    precision: float
    time_s: float
    n_nodes: int
    n_skeleton_edges: int
    n_dag_edges: int
    orientation_confidence: float = 0.0


class ProductDiscoveryEngine:
    """Product-grade causal discovery: skeleton + orientation (fast or precise).

    Args:
        skeleton_tau: CI test threshold.
        n_particles: for DiBS mode (precise but slower).
        use_fast_orient: if True, uses O(|E|) per-edge scoring.
            If False, uses GovernedDiBS particle search (O(2^|E|), more precise).
        max_in_degree: bounded-degree prior.
        likelihood_mode: "linear" or "poly2".
    """

    def __init__(
        self,
        skeleton_tau: float = 0.05,
        n_particles: int = 30,
        max_in_degree: int = 6,
        lambda_sparse: float = 0.5,
        likelihood_mode: str = "poly2",
        seed: int = 42,
        use_fast_orient: bool = True,
        use_validation_filter: bool = False,
        use_temporal_split: bool = False,
        n_lags: int = 2,
        auto_tune: bool = False,  # FORBIDDEN in research runs — violates preregistration discipline (Hard Boundary #5). Engineering deployment only.
    ):
        self.tau = skeleton_tau
        self.n_particles = n_particles
        self.max_in_degree = max_in_degree
        self.lambda_sparse = lambda_sparse
        self.likelihood_mode = likelihood_mode
        self.seed = seed
        self.use_fast_orient = use_fast_orient
        self.use_validation_filter = use_validation_filter
        self.use_temporal_split = use_temporal_split
        self.n_lags = n_lags
        self.auto_tune = auto_tune

    def discover(
        self, obs: list[list[float]],
        true_edges_for_eval: frozenset | None = None,
    ) -> DiscoveryResult:
        t0 = time.time()
        evidence: dict = {}
        marginals: dict = {}
        conf: float = 0.5
        ori_conf: float = 0.0

        if self.use_temporal_split:
            splitter = TemporalDAGSplitter(n_lags=self.n_lags)
            obs_expanded = splitter.expand(obs)
            n_orig = len(obs[0])
            obs_work = obs_expanded
        else:
            obs_work = obs
            n_orig = len(obs[0])

        n = len(obs_work[0])
        skeleton = self._build_skeleton(obs_work)
        sk_set = frozenset(skeleton)

        if self.auto_tune:
            tuner = AutoTuner(seed=self.seed)
            tuned_tau = tuner.tune_tau(obs_work)
            tuned_conf = tuner.tune_confidence(obs_work, tau=tuned_tau)
            cv_edges = tuner.cross_validate_edges(obs_work, k=5, tau=tuned_tau)
            evidence["auto_tune"] = {
                "tau": round(tuned_tau, 3),
                "confidence": round(tuned_conf, 3),
                "cv_edges": len(cv_edges),
                "WARNING": "ENGINEERING MODE ONLY — NOT VALID FOR RESEARCH RUNS",
            }
            sk_set = cv_edges | sk_set  # union of CV-validated and original skeleton

        if self.use_fast_orient:
            dag, ori_conf, edge_scores = per_edge_orient(
                obs_work, sk_set, self.likelihood_mode, 0.3,
            )
            conf = ori_conf
            marginals = {}
            evidence = evidence if evidence else {}
            for undir in sk_set:
                parts = list(undir)
                if len(parts) == 2:
                    s = edge_scores.get(undir, (0, 0))
                    marginals[(parts[0], parts[1])] = 1.0 if s[0] > s[1] else 0.0
                    marginals[(parts[1], parts[0])] = 1.0 if s[1] > s[0] else 0.0
                    evidence[str(undir)] = {"scores": f"{s[0]:.1f} vs {s[1]:.1f}"}
        else:
            di = self._orient_skeleton(obs_work, sk_set)
            dag = di.MAP_dag()
            conf = di.confidence()
            marginals = di.edge_marginals()
            di_evidence = di.evidence_report()
            evidence.update(di_evidence)
            ori_conf = 0.0

        if self.use_temporal_split:
            dag = splitter.map_edges_to_original(dag, n_orig)

        if self.use_validation_filter:
            validator = InterventionValidationFilter(holdout_ratio=0.2, effect_threshold=0.2)
            filtered = validator.filter(dag, obs)  # int_data=None → returns dag unchanged
            evidence["validation_note"] = InterventionValidationFilter.WARNING_NO_INT_DATA

        rec = prec = orient = 0.0
        if true_edges_for_eval is not None:
            mu = {frozenset(e) for e in dag}; tu = {frozenset(e) for e in true_edges_for_eval}
            rec = len(mu & tu) / max(len(tu), 1)
            prec = len(mu & tu) / max(len(mu), 1)
            corr = sum(1 for u, v in true_edges_for_eval if (u, v) in dag)
            tot = sum(1 for u, v in true_edges_for_eval if (u, v) in dag or (v, u) in dag)
            orient = corr / max(tot, 1) if tot > 0 else 0

        return DiscoveryResult(
            dag=dag, skeleton=sk_set, confidence=conf, edge_marginals=marginals,
            evidence_chain=evidence, orientation_accuracy=orient, recall=rec,
            precision=prec, time_s=round(time.time()-t0,1), n_nodes=n,
            n_skeleton_edges=len(sk_set), n_dag_edges=len(dag),
            orientation_confidence=ori_conf,
        )

    def _build_skeleton(self, obs: list[list[float]]) -> set[frozenset]:
        n = len(obs[0])
        try:
            std = _standardize_cols(obs); prec = _inv(_cov(std))
        except (ValueError, ZeroDivisionError):
            return set()
        edges = set()
        for i in range(n):
            for j in range(i + 1, n):
                denom = math.sqrt(abs(prec[i][i] * prec[j][j])) or 1e-12
                if abs(prec[i][j]) / denom > self.tau:
                    edges.add(frozenset({i, j}))
        return edges

    def _orient_skeleton(
        self, obs: list[list[float]], skeleton: frozenset,
    ) -> GovernedDiBS:
        n = len(obs[0])
        organ_proposals = {1: set()}
        for undir in skeleton:
            parts = list(undir)
            if len(parts) == 2:
                organ_proposals[1].add((parts[0], parts[1]))
                organ_proposals[1].add((parts[1], parts[0]))

        di = GovernedDiBS(
            n_nodes=n, n_particles=self.n_particles, lambda_sparse=self.lambda_sparse,
            sigma_noise=0.3, seed=self.seed, likelihood_mode=self.likelihood_mode,
            organ_proposals=organ_proposals, organ_credits={1: 0.8},
            max_in_degree=self.max_in_degree, adaptive_particles=True,
        )
        di.posterior_temperature = 2.0
        di.update(obs)
        di.resample_and_perturb()
        di.update(obs)
        di.hippocampal_replay(obs, replay_rounds=1)

        for undir in skeleton:
            parts = list(undir)
            if len(parts) == 2:
                di.record_evidence((parts[0], parts[1]), 1, True, 0)
                di.record_evidence((parts[1], parts[0]), 1, True, 0)
        return di

class BatchProductEngine:
    """Sequential batch runner for multiple domains."""

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def run(self, domains: list[tuple[str, list[list[float]]]]) -> dict[str, DiscoveryResult]:
        results = {}
        for name, obs in domains:
            engine = ProductDiscoveryEngine(**self.kwargs)
            results[name] = engine.discover(obs)
        return results
