"""Causal Prior Transfer v2 — scaled, adaptive, multi-modal.

v2 improvements:
1. SCALE: 2000 training domains (6s→25s, linear scaling)
2. ADAPTIVE: add_domain() feeds discovered structures back into prior library
3. MULTI-MODAL FEATURES: topological (degree distribution, clustering) + mechanism type

Pure stdlib. No external dependencies.
"""
from __future__ import annotations

import json
import math
import random
import statistics
from dataclasses import dataclass, field
from pathlib import Path

from .cwm_organ import StructureProposal, CWMOrgan, _standardize_cols, _cov, _inv


@dataclass
class DomainFeatures:
    n_nodes: int
    n_obs: int
    mean_partial_corr: float
    std_partial_corr: float
    max_partial_corr: float
    ci_threshold_01_density: float
    ci_threshold_05_density: float
    avg_degree_at_01: float
    max_degree_at_01: int
    clustering_coeff_at_01: float
    degree_entropy_at_01: float
    mechanism_type: int


_MECHANISM_MAP = {"linear": 0, "tanh": 1, "poly": 2, "sin": 3}


def extract_domain_features(
    obs: list[list[float]], mechanism: str = "linear",
    ci_thresholds: tuple[float, ...] = (0.01, 0.05),
) -> DomainFeatures:
    n_nodes = len(obs[0])
    n_obs = len(obs)
    try:
        std = _standardize_cols(obs)
        prec = _inv(_cov(std))
    except (ValueError, ZeroDivisionError):
        return DomainFeatures(n_nodes, n_obs, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)

    partial_corrs = []
    adj_01: dict[int, set[int]] = {}
    for i in range(n_nodes):
        adj_01[i] = set()
    for i in range(n_nodes):
        for j in range(i + 1, n_nodes):
            denom = math.sqrt(abs(prec[i][i] * prec[j][j])) or 1e-12
            pcorr = abs(prec[i][j]) / denom
            partial_corrs.append(pcorr)
            if pcorr > 0.01:
                adj_01[i].add(j)
                adj_01[j].add(i)

    mean_pc = statistics.mean(partial_corrs) if partial_corrs else 0.0
    std_pc = statistics.pstdev(partial_corrs) if len(partial_corrs) > 1 else 0.0
    max_pc = max(partial_corrs) if partial_corrs else 0.0
    n_pairs = max(n_nodes * (n_nodes - 1) // 2, 1)
    density_01 = sum(1 for p in partial_corrs if p > 0.01) / n_pairs
    density_05 = sum(1 for p in partial_corrs if p > 0.05) / n_pairs

    degrees = [len(adj_01[i]) for i in range(n_nodes)]
    avg_deg = statistics.mean(degrees) if degrees else 0
    max_deg = max(degrees) if degrees else 0

    triangles = 0
    for i in range(n_nodes):
        for j in adj_01[i]:
            if j > i:
                for k in (adj_01[i] & adj_01[j]):
                    if k > j:
                        triangles += 1
    n_triples = sum(d * (d - 1) for d in degrees)
    clustering = (3.0 * triangles / max(n_triples, 1)) if n_triples > 0 else 0.0

    deg_probs = [d / max(sum(degrees), 1) for d in degrees]
    ent = -sum(p * math.log(max(p, 1e-12)) for p in deg_probs) / max(math.log(n_nodes), 1)

    return DomainFeatures(
        n_nodes=n_nodes, n_obs=n_obs,
        mean_partial_corr=mean_pc, std_partial_corr=std_pc, max_partial_corr=max_pc,
        ci_threshold_01_density=density_01, ci_threshold_05_density=density_05,
        avg_degree_at_01=avg_deg, max_degree_at_01=max_deg,
        clustering_coeff_at_01=clustering, degree_entropy_at_01=ent,
        mechanism_type=_MECHANISM_MAP.get(mechanism, 0),
    )


def _features_to_vector(f: DomainFeatures) -> list[float]:
    return [
        f.n_nodes / 15.0,
        math.log(max(f.n_obs, 1)) / 10.0,
        f.mean_partial_corr,
        f.std_partial_corr,
        f.max_partial_corr,
        f.ci_threshold_01_density,
        f.ci_threshold_05_density,
        f.avg_degree_at_01 / 10.0,
        f.max_degree_at_01 / 10.0,
        f.clustering_coeff_at_01,
        f.degree_entropy_at_01,
        f.mechanism_type / 3.0,
    ]


def _vector_distance(a: list[float], b: list[float]) -> float:
    return math.sqrt(sum((ai - bi) ** 2 for ai, bi in zip(a, b)))


class CausalPriorLearner:
    """Learns edge probability priors from synthetic SCM experience.

    v2: scaled to 2000 domains, adaptive updates, multi-modal features.
    """

    def __init__(self, n_train_domains: int = 2000, seed: int = 42):
        self._rng = random.Random(seed)
        self._features: list[list[float]] = []
        self._edge_probs: list[list[float]] = []
        self._domain_metadata: list[dict] = []
        self._generate_training_data(n_train_domains)

    def _generate_training_data(self, n: int):
        for _ in range(n):
            n_nodes = self._rng.randint(4, 12)
            n_obs = self._rng.randint(30, 600)
            noise = self._rng.uniform(0.1, 1.0)
            mechanism = self._rng.choice(["linear", "tanh", "poly"])
            edges = set()
            for i in range(n_nodes):
                for j in range(i + 1, n_nodes):
                    if self._rng.random() < self._rng.uniform(0.1, 0.5):
                        edges.add((i, j))
            if len(edges) < 2:
                edges = {(0, 1), (1, 2)}
            obs = self._generate_domain_data(n_nodes, frozenset(edges), n_obs, noise, mechanism)
            self._add_domain_internal(obs, frozenset(edges), n_nodes, n_obs, mechanism)

    def _add_domain_internal(
        self, obs: list[list[float]], true_edges: frozenset,
        n_nodes: int, n_obs: int, mechanism: str,
    ):
        feats = extract_domain_features(obs, mechanism)
        self._features.append(_features_to_vector(feats))
        prob_vec = self._make_edge_vector(obs, n_nodes, true_edges)
        self._edge_probs.append(prob_vec)
        self._domain_metadata.append({
            "n_nodes": n_nodes, "n_obs": n_obs, "mechanism": mechanism,
            "n_edges": len(true_edges),
        })

    def add_domain(
        self, obs: list[list[float]], discovered_dag: frozenset,
        n_nodes: int | None = None, mechanism: str = "linear",
    ):
        """Feed a newly discovered structure back into the prior library.
        This is the ADAPTIVE update: the prior grows with experience.

        Args:
            obs: observational data from the discovered domain.
            discovered_dag: the MAP DAG output from GovernedDiBS.
            n_nodes: number of nodes (inferred from obs if None).
            mechanism: mechanism type guessed from domain context.
        """
        if n_nodes is None:
            n_nodes = len(obs[0])
        n_obs = len(obs)
        self._add_domain_internal(obs, discovered_dag, n_nodes, n_obs, mechanism)

    def _generate_domain_data(
        self, n_nodes: int, edges: frozenset, n_obs: int,
        noise_std: float, mechanism: str,
    ) -> list[list[float]]:
        if mechanism == "linear":
            from .bayesian_dag_posterior import generate_linear_scm_data
            obs, _ = generate_linear_scm_data(n_nodes, edges, n_obs, noise_std, rng=self._rng)
            return obs
        parents = {j: [] for j in range(n_nodes)}
        coefs = {}
        for u, v in edges:
            parents[v].append(u)
            coefs[(u, v)] = self._rng.uniform(0.4, 1.0) * self._rng.choice([1.0, -1.0])
        obs = []
        for _ in range(n_obs):
            row = [0.0] * n_nodes
            for j in range(n_nodes):
                val = self._rng.gauss(0, noise_std)
                for p in parents[j]:
                    beta = coefs[(p, j)]
                    if mechanism == "tanh":
                        val += beta * math.tanh(row[p] * 1.5)
                    elif mechanism == "poly":
                        val += beta * (row[p] + 0.3 * row[p] ** 2)
                row[j] = val
            obs.append(row)
        return obs

    def _make_edge_vector(
        self, obs: list[list[float]], n_nodes: int,
        true_edges: frozenset,
    ) -> list[float]:
        max_nodes = 15
        max_pairs = max_nodes * (max_nodes - 1) // 2
        if max_pairs <= 0:
            return [0.5]
        vec = [0.1] * max_pairs
        try:
            std = _standardize_cols(obs)
            prec = _inv(_cov(std))
        except (ValueError, ZeroDivisionError):
            return vec
        true_set = frozenset(true_edges)
        idx = 0
        for i in range(n_nodes):
            for j in range(i + 1, n_nodes):
                denom = math.sqrt(abs(prec[i][i] * prec[j][j])) or 1e-12
                pcorr = abs(prec[i][j]) / denom
                is_true = 1.0 if frozenset({i, j}) in {frozenset(e) for e in true_set} else 0.0
                vec[idx] = pcorr * 0.5 + is_true * 0.5
                idx += 1
        return vec

    def predict_edge_priors(
        self, obs: list[list[float]], mechanism: str = "linear", k: int = 15,
    ) -> dict[tuple[int, int], float]:
        n_nodes = len(obs[0])
        feats = extract_domain_features(obs, mechanism)
        query_vec = _features_to_vector(feats)
        distances = [
            (_vector_distance(query_vec, f), idx)
            for idx, f in enumerate(self._features)
        ]
        distances.sort(key=lambda x: x[0])
        k_eff = min(k, len(distances))
        n_pairs = n_nodes * (n_nodes - 1) // 2
        prior_vec = [0.1] * max(n_pairs, 1)
        if k_eff > 0 and self._edge_probs:
            weights = [1.0 / max(d[0], 1e-6) for d in distances[:k_eff]]
            total_w = sum(weights)
            if total_w > 0:
                weights = [w / total_w for w in weights]
            for w, (_, idx) in zip(weights, distances[:k_eff]):
                vec = self._edge_probs[idx]
                for vi in range(min(len(prior_vec), len(vec))):
                    prior_vec[vi] += w * vec[vi]

        result = {}
        idx = 0
        for i in range(n_nodes):
            for j in range(i + 1, n_nodes):
                prob = prior_vec[idx] if idx < len(prior_vec) else 0.1
                result[(i, j)] = max(0.01, min(0.99, prob))
                idx += 1
        return result

    def save(self, path: str | Path):
        data = {
            "features": self._features,
            "edge_probs": self._edge_probs,
            "metadata": self._domain_metadata,
        }
        Path(path).write_text(json.dumps(data), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> CausalPriorLearner:
        data = json.loads(Path(path).read_text())
        learner = cls.__new__(cls)
        learner._rng = random.Random(0)
        learner._features = data["features"]
        learner._edge_probs = data["edge_probs"]
        learner._domain_metadata = data.get("metadata", [])
        return learner

    @property
    def n_domains(self) -> int:
        return len(self._features)


class TransferOrgan(CWMOrgan):
    """CWM organ using pre-trained causal prior for edge proposals."""

    def __init__(self, learner: CausalPriorLearner, mechanism: str = "linear",
                 min_prob: float = 0.05):
        self.learner = learner
        self.mechanism = mechanism
        self.min_prob = min_prob

    def propose_skeleton(self, obs: list[list[float]]) -> list[StructureProposal]:
        n_nodes = len(obs[0])
        priors = self.learner.predict_edge_priors(obs, self.mechanism, k=15)
        edges = set()
        for (i, j), prob in priors.items():
            if prob >= self.min_prob:
                edges.add(frozenset({i, j}))
        score = len(edges) / max(n_nodes * (n_nodes - 1) / 2, 1)
        return [StructureProposal(
            edges=frozenset(edges),
            score=score,
            provenance=f"TransferOrgan_{self.learner.n_domains}_domains",
        )]

    def confidence(self) -> float:
        return 0.6
