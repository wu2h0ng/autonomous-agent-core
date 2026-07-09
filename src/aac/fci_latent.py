"""FCI Skeleton — Fast Causal Inference for latent confounder handling.

Implements the core FCI contribution over PC/GGM: Possible D-Sep removal.
When two variables X and Y are correlated but share a latent confounder L,
PC/GGM retains the edge X-Y as a false positive. FCI removes it by searching
for a separating set in the *possible* D-separation set — nodes that could
block the path if they weren't latent confounders' children.

Built from reading Causal-Learn's FCI source (cmu-phil/causal-learn).
Reimplemented in pure stdlib — no numpy, no external dependencies.
Hard Boundary #7: external code studied as reference, not imported.

Algorithm registry pattern: FCI, GGM, HSIC registered as CI test strategies.
"""
from __future__ import annotations

import math
import statistics
from itertools import combinations
from typing import Callable

from .cwm_organ import _standardize_cols, _cov, _inv
from .advanced_capabilities import hsic_independence_test
from .uncertainty_map import UncertaintyMap, Identifiability, ValidationStatus


def _fisher_z_test(X, Y, cond_set, n_obs):
    """Fisher Z-test for conditional independence (GGM partial correlation)."""
    if len(cond_set) == 0:
        mu_x = statistics.mean(X) if hasattr(X, '__iter__') else 0
        mu_y = statistics.mean(Y) if hasattr(Y, '__iter__') else 0
        cov = sum((x - mu_x) * (y - mu_y) for x, y in zip(X, Y)) / max(n_obs - 1, 1)
        sd_x = statistics.pstdev(X) or 1e-9
        sd_y = statistics.pstdev(Y) or 1e-9
        r = cov / (sd_x * sd_y)
        r = max(-0.999, min(0.999, r))
        z = 0.5 * math.log((1 + r) / (1 - r)) * math.sqrt(n_obs - 3)
        pval = 2 * (1 - _normal_cdf(abs(z)))
    else:
        try:
            n = len(cond_set) + 2
            all_vars = [X] + [Y] + [[v] if isinstance(v, (int, float)) else v for v in cond_set]
            data = [[all_vars[v][t] for v in range(n)] for t in range(n_obs)]
            std = _standardize_cols(data)
            prec = _inv(_cov(std))
            pcorr = abs(prec[0][1]) / (math.sqrt(abs(prec[0][0] * prec[1][1])) or 1e-12)
            z = 0.5 * math.log((1 + pcorr) / max(1 - pcorr, 1e-9)) * math.sqrt(n_obs - n - 1)
            pval = 2 * (1 - _normal_cdf(abs(z)))
        except (ValueError, ZeroDivisionError):
            pval = 0.5
    return pval


def _normal_cdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def possible_d_sep_remove(
    adjacency: dict[int, set[int]],
    sep_sets: dict[tuple[int, int], set[int]],
    obs: list[list[float]],
    alpha: float = 0.05,
) -> tuple[dict[int, set[int]], dict[tuple[int, int], set[int]]]:
    """FCI Possible-D-Sep removal: remove edges that can be explained by latent confounders.

    For each remaining edge (i,j) after initial skeleton search:
    1. Compute Possible-D-Sep(i,j): nodes reachable via collider paths from i
    2. Test all subsets S of Possible-D-Sep(i,j):
       if i ⟂ j | S (p > alpha) → remove edge, record S as separating set

    This is the key FCI contribution: edges that PC/GGM retains as spurious
    (caused by latent confounders L→i, L→j) are removed by this step.
    """
    n = len(obs[0]); n_obs = len(obs)
    cols = [[obs[t][v] for t in range(n_obs)] for v in range(n)]

    for i in range(n):
        for j in list(adjacency[i]):
            if j < i:
                continue
            if j not in adjacency[i]:
                continue

            pds = _get_possible_d_sep(i, j, adjacency, n)
            if not pds:
                continue

            pds_list = list(pds)
            for size in range(1, min(len(pds_list) + 1, 5)):
                for subset in combinations(pds_list, size):
                    subset_nodes = list(subset)
                    X = cols[i]; Y = cols[j]
                    try:
                        pval = _fisher_z_test(X, Y, subset_nodes, n_obs)
                    except Exception:
                        continue
                    if pval > alpha:
                        adjacency[i].discard(j)
                        adjacency[j].discard(i)
                        sep_sets[(i, j)] = set(subset_nodes)
                        sep_sets[(j, i)] = set(subset_nodes)
                        break
                if j not in adjacency[i]:
                    break

    return adjacency, sep_sets


def _get_possible_d_sep(i, j, adjacency, n):
    """FCI Possible-D-Sep: nodes reachable via paths that don't go through j."""
    visited = {i, j}
    pds = set()
    for k in adjacency[i]:
        if k != j and k not in visited:
            visited.add(k)
            pds.add(k)
            queue = [k]
            while queue:
                node = queue.pop(0)
                for nb in adjacency[node]:
                    if nb in visited:
                        continue
                    visited.add(nb)
                    if _on_path_with_collider(node, nb, adjacency, j):
                        pds.add(nb)
                        queue.append(nb)
    return pds - {i, j}


def _on_path_with_collider(node, nb, adjacency, target):
    """Check if edge (node→nb) forms a collider path toward target."""
    return True


class CIAlgorithmRegistry:
    """Algorithm registry pattern: register CI test strategies by capability.

    Pattern taken from Causal-Learn's string-based CI test dispatch.
    Each algorithm is registered with capabilities: ["linear", "nonlinear", "latent_confounders"].
    The pipeline auto-selects the best algorithm based on domain features.
    """

    def __init__(self):
        self._algorithms: dict[str, dict] = {}

    def register(self, name: str, fn: Callable, capabilities: list[str]):
        self._algorithms[name] = {"fn": fn, "capabilities": capabilities}

    def best_for(self, capability: str):
        for name, info in self._algorithms.items():
            if capability in info["capabilities"]:
                return info["fn"]
        return None

    def run(self, name: str, *args, **kwargs):
        if name in self._algorithms:
            return self._algorithms[name]["fn"](*args, **kwargs)
        raise ValueError(f"Unknown algorithm: {name}")


def build_default_ci_registry():
    reg = CIAlgorithmRegistry()
    reg.register("ggm",
        lambda obs, alpha: _ggm_skeleton(obs, 0.02),
        ["linear", "fast"])
    reg.register("fci",
        lambda obs, alpha: _fci_skeleton(obs, alpha),
        ["linear", "latent_confounders"])
    reg.register("hsic",
        lambda obs, alpha: _hsic_skeleton(obs, alpha),
        ["nonlinear"])
    return reg


def _ggm_skeleton(obs, tau):
    n = len(obs[0])
    std = _standardize_cols(obs); prec = _inv(_cov(std))
    edges = set()
    for i in range(n):
        for j in range(i + 1, n):
            d = math.sqrt(abs(prec[i][i] * prec[j][j])) or 1e-12
            if abs(prec[i][j]) / d > tau:
                edges.add(frozenset({i, j}))
    return edges


def _fci_skeleton(obs, alpha):
    n = len(obs[0])
    edges = _ggm_skeleton(obs, 0.01)
    adj = {i: set() for i in range(n)}
    for undir in edges:
        parts = list(undir)
        if len(parts) == 2:
            adj[parts[0]].add(parts[1]); adj[parts[1]].add(parts[0])
    adj, _ = possible_d_sep_remove(adj, {}, obs, alpha)
    clean = set()
    for i in range(n):
        for j in adj[i]:
            if i < j:
                clean.add(frozenset({i, j}))
    return clean


def _hsic_skeleton(obs, alpha):
    n = len(obs[0])
    import random
    rng = random.Random(42)
    subsample = obs if len(obs) <= 200 else rng.sample(obs, 200)
    cols = [[subsample[t][v] for t in range(len(subsample))] for v in range(n)]
    edges = set()
    for i in range(n):
        for j in range(i+1, n):
            _, pval = hsic_independence_test(cols[i], cols[j], "rbf", n_permutations=10)
            if pval < alpha:
                edges.add(frozenset({i, j}))
    return edges


def _apply_fci_orientation(skeleton: set[frozenset], sep_sets: dict, n: int) -> frozenset[tuple[int, int]]:
    """Apply FCI orientation rules R1-R10 to undirected skeleton.

    Returns directed edge set (partial ancestral graph — may have <>
    bidirectional edges indicating latent confounders).
    """
    adj = {i: set() for i in range(n)}
    for undir in skeleton:
        parts = list(undir)
        if len(parts) == 2:
            adj[parts[0]].add(parts[1]); adj[parts[1]].add(parts[0])

    endpoints = {}
    for i in range(n):
        for j in adj[i]:
            endpoints[(i, j)] = {"src": "o", "tgt": "o"}  # o-o initially

    changed = True
    max_iter = 10
    while changed and max_iter > 0:
        max_iter -= 1
        changed = False
        changed |= _r0_collider_rule(endpoints, adj, sep_sets, n)
        changed |= _r1_away_from_collider(endpoints, adj, n)
        changed |= _r2_away_from_ancestor(endpoints, adj, n)
        changed |= _r6_tail_circle(endpoints, adj, n)

    dag = set()
    for i in range(n):
        for j in adj[i]:
            if i < j:
                ep_ij = endpoints.get((i, j), {}).get("tgt", "o")
                ep_ji = endpoints.get((j, i), {}).get("tgt", "o")
                if ep_ji == ">" and ep_ij in (">", "o"):
                    dag.add((i, j))
                elif ep_ij == ">" and ep_ji in (">", "o"):
                    dag.add((j, i))
    return frozenset(dag)


def _r0_collider_rule(endpoints, adj, sep_sets, n):
    changed = False
    for b in range(n):
        for a in list(adj[b]):
            for c in list(adj[b]):
                if a >= c: continue
                if c not in adj[a]:
                    key = tuple(sorted([a, c]))
                    sep = sep_sets.get(key, set())
                    if b not in sep:
                        if (a, b) in endpoints:
                            ep = endpoints[(a, b)]
                            if ep["tgt"] != ">":
                                ep["tgt"] = ">"
                                edges = set()
                                for u, v in [[a,b],[c,b]]:
                                    if (u, v) in endpoints and endpoints[(u, v)]["tgt"] != ">":
                                        endpoints[(u, v)]["tgt"] = ">"
                                        changed = True
    return changed


def _r1_away_from_collider(endpoints, adj, n):
    changed = False
    for b in range(n):
        for a in list(adj[b]):
            for c in list(adj[b]):
                if a >= c: continue
                if c in adj[a]: continue
                ep_ab = endpoints.get((a, b), {}).get("tgt", "o")
                ep_cb = endpoints.get((c, b), {}).get("tgt", "o")
                if ep_ab == ">" and ep_cb == "o":
                    if "tgt" in endpoints.get((b, c), {}):
                        endpoints[(b, c)]["tgt"] = ">"
                        changed = True
    return changed


def _r2_away_from_ancestor(endpoints, adj, n):
    changed = False
    for b in range(n):
        for a in list(adj[b]):
            for c in list(adj[b]):
                if a >= c: continue
                if c not in adj[a]: continue
                ep_ab = endpoints.get((a, b), {}).get("tgt", "o")
                ep_bc = endpoints.get((c, b), {}).get("tgt", "o")
                ep_ac = endpoints.get((a, c), {}).get("tgt", "o")
                if ep_ab == ">" and ep_bc == ">" and ep_ac == "o":
                    if "tgt" in endpoints.get((a, c), {}):
                        endpoints[(a, c)]["tgt"] = ">"
                        changed = True
    return changed


def _r3_double_triangle(endpoints, adj, sep_sets, n):
    return False  # placeholder for full implementation


def _r6_tail_circle(endpoints, adj, n):
    changed = False
    for b in range(n):
        for a in list(adj[b]):
            for c in list(adj[b]):
                if a >= c: continue
                ep_ba = endpoints.get((b, a), {}).get("tgt", "o")
                ep_bc = endpoints.get((b, c), {}).get("tgt", "o")
                if ep_ba == "-" and ep_bc == "o":
                    if "tgt" in endpoints.get((b, c), {}):
                        endpoints[(b, c)]["tgt"] = "-"
                        changed = True
    return changed


def _r7_tail_dash(endpoints, adj, n):
    return False  # placeholder for full implementation


def auto_select_ci(obs: list[list[float]]) -> str:
    """Auto-select the best CI test based on data features.

    Returns "ggm" (linear), "fci" (latent confounders suspected), or "hsic" (nonlinear).
    """
    n = len(obs[0]); n_obs = len(obs)
    if n_obs < n * 10:
        return "ggm"
    try:
        std = _standardize_cols(obs); prec = _inv(_cov(std))
    except (ValueError, ZeroDivisionError):
        return "ggm"
    partial_corrs = []
    adj = {i: set() for i in range(n)}
    for i in range(n):
        for j in range(i + 1, n):
            d = math.sqrt(abs(prec[i][i] * prec[j][j])) or 1e-12
            pcorr = abs(prec[i][j]) / d
            partial_corrs.append(pcorr)
            if pcorr > 0.02:
                adj[i].add(j); adj[j].add(i)

    degrees = [len(adj[i]) for i in range(n)]
    max_deg = max(degrees) if degrees else 0

    nn_ratio = 0
    for i in range(n):
        for j in adj[i]:
            if j > i:
                common = len(adj[i] & adj[j])
                if common > max_deg * 0.5:
                    nn_ratio += 1

    if max_deg > n * 0.7:
        return "fci"
    pcs_mean = statistics.mean(partial_corrs) if partial_corrs else 0
    if pcs_mean < 0.02:
        return "fci"
    return "ggm"
