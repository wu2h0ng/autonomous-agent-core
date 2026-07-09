"""Engine Upgrades — HSIC CI, Intervention Generator, Text Causal Understanding.

Three upgrades for the three bottlenecks:
1. HSIC nonlinear skeleton — replace GGM partial correlation in nonlinear domains
2. Interventional data generator — synthesize do() rows from fitted mechanisms
3. Text causal understanding — CausalRAG-style claim extraction + verification

All pure stdlib (1,2) + LLM optional (3). Plugs into ProductDiscoveryEngine.
"""
from __future__ import annotations

import json
import math
import random
import statistics
from typing import Any

from .cwm_organ import _standardize_cols, _cov, _inv
from .advanced_capabilities import hsic_independence_test


def hsic_skeleton(obs: list[list[float]], tau_pvalue: float = 0.05,
                  max_pairs: int = 200) -> set[frozenset]:
    """Build skeleton using HSIC nonlinear CI test for ALL pairs.

    For smaller n_vars (≤20): tests all pairs. For larger: random subsample.
    Returns undirected edge set where HSIC p-value < tau_pvalue.

    Key advantage over GGM: detects NON-MONOTONE dependencies
    (e.g., XOR, sin, saturation patterns) that partial correlation misses.
    """
    n = len(obs[0]); n_pairs = n * (n - 1) // 2
    edges = set()
    cols = [[obs[t][v] for t in range(len(obs))] for v in range(n)]

    pairs = [(i, j) for i in range(n) for j in range(i + 1, n)]
    if n_pairs > max_pairs:
        rng = random.Random(42)
        pairs = rng.sample(pairs, max_pairs)

    for i, j in pairs:
        _, pval = hsic_independence_test(cols[i], cols[j], "rbf", n_permutations=50)
        if pval < tau_pvalue:
            edges.add(frozenset({i, j}))
    return edges


def generate_interventional_data(
    dag: frozenset[tuple[int, int]], obs: list[list[float]],
    n_interventions: int = 20, n_nodes: int = 3,
    seed: int = 42,
) -> list[list[float]]:
    """Generate synthetic intervention rows from fitted mechanisms.

    For each intervenable node (up to n_nodes), fit OLS mechanism from obs,
    then simulate do(node=val) at values ±1σ from mean. The downstream values
    propagate through the DAG's causal mechanisms.

    This augments the training data with INTERVENTIONAL information that
    helps GovernedDiBS distinguish causal direction from correlation.
    """
    n = len(obs[0]); n_obs = len(obs)
    if n_obs < 10:
        return []
    rng = random.Random(seed)
    parents = {j: [] for j in range(n)}
    for u, v in dag:
        parents[v].append(u)

    coefs = {}
    for j in range(n):
        pa = parents[j]
        if pa:
            X = [[obs[t][p] for p in pa] for t in range(n_obs)]
            y = [obs[t][j] for t in range(n_obs)]
            from .bayesian_dag_posterior import _ols_coefficients
            try:
                coefs[j] = _ols_coefficients(X, y)
            except (ValueError, ZeroDivisionError):
                coefs[j] = []
        else:
            coefs[j] = []

    topo = list(range(n))
    indeg = {i: len([u for u, v in dag if v == i]) for i in range(n)}
    q = [i for i in range(n) if indeg[i] == 0]
    order = []
    while q:
        u = q.pop(0); order.append(u)
        for v in [v for u2, v in dag if u2 == u]:
            indeg[v] -= 1
            if indeg[v] == 0: q.append(v)

    intervenable = rng.sample(range(n), min(n_nodes, n))
    int_rows = []
    for k in intervenable:
        col_k = [obs[t][k] for t in range(n_obs)]
        mu = statistics.mean(col_k); sd = statistics.pstdev(col_k) or 1.0
        for do_val in [mu - sd, mu, mu + sd]:
            for _ in range(max(1, n_interventions // (3 * n_nodes))):
                row = [0.0] * n
                baseline = [statistics.mean([obs[t][v] for t in range(n_obs)]) for v in range(n)]
                baseline[k] = do_val
                for j in order:
                    if j == k:
                        row[j] = do_val; continue
                    pa = parents[j]; coef = coefs.get(j, [])
                    if coef and len(coef) == len(pa):
                        row[j] = sum(coef[pi] * baseline[p] for pi, p in enumerate(pa))
                        row[j] += rng.gauss(0, 0.1 * max(abs(row[j]), 1.0))
                    else:
                        row[j] = baseline[j]
                int_rows.append(row)
    return int_rows


class TextCausalExtractor:
    """CausalRAG-style: extract causal claims from text → verify against DAG.

    Given a text passage (report, paper, article), uses LLM to extract
    causal claims (X→Y). Each claim is then verified against the discovered
    DAG:
      - data_supported: edge (X,Y) or (Y,X) exists in DAG
      - direction_match: X→Y specifically exists (not just Y→X)
      - conflict: DAG has opposing direction
      - unverified: neither direction in DAG

    This closes the loop between text-based knowledge and data-driven discovery.
    """

    def __init__(self, backend: Any = None, variable_names: list[str] | None = None):
        self.backend = backend
        self.names = variable_names or []

    def extract_claims(self, text: str) -> list[dict]:
        if not self.backend:
            return []
        prompt = (
            f"Extract causal claims from this text as triples (cause, effect, confidence).\n"
            f"Text: \"{text[:2000]}\"\n"
            f"Return ONLY JSON: {{\"claims\": [{{\"cause\": \"X\", \"effect\": \"Y\", \"confidence\": 0.8}}, ...]}}"
        )
        try:
            raw = self.backend.propose(prompt)
            content = str(raw) if isinstance(raw, str) else raw.get("content", "{}")
            if content.startswith("```"): content = content.split("```")[1]
            if content.startswith("json"): content = content[4:]
            return json.loads(content).get("claims", [])
        except Exception:
            return []

    def verify_against_dag(self, claims: list[dict], dag: frozenset,
                           ) -> list[dict]:
        verified = []
        for c in claims:
            cause = str(c.get("cause", "")); effect = str(c.get("effect", ""))
            ci = self._find_var(cause); ei = self._find_var(effect)
            status = "unverified"
            if ci >= 0 and ei >= 0:
                if (ci, ei) in dag:
                    status = "data_supported"
                elif (ei, ci) in dag:
                    status = "conflict"
                elif (ci, ei) not in dag and (ei, ci) not in dag:
                    status = "unverified"
            verified.append({**c, "cause_idx": ci, "effect_idx": ei, "verification": status})
        return verified

    def _find_var(self, name: str) -> int:
        name_l = name.lower()
        for i, n in enumerate(self.names):
            if name_l == n.lower() or name_l in n.lower() or n.lower() in name_l:
                return i
        return -1

    def verify_text(self, text: str, dag: frozenset) -> dict:
        claims = self.extract_claims(text)
        verified = self.verify_against_dag(claims, dag)
        n_supported = sum(1 for v in verified if v["verification"] == "data_supported")
        n_conflict = sum(1 for v in verified if v["verification"] == "conflict")
        n_unverified = sum(1 for v in verified if v["verification"] == "unverified")
        return {
            "total_claims": len(verified),
            "data_supported": n_supported,
            "conflicts": n_conflict,
            "unverified": n_unverified,
            "claims": verified,
        }
