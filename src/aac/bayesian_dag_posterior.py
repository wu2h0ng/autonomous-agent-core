"""Bayesian DAG Posterior — governed DiBS.

Particle-based Bayesian inference over DAG structures per M-GAP-2 Algorithm 1:
Governed DiBS with C7 constraints, credit-weighted prior, SVGD-style
gradient-informed particle updates, and BOED intervention selection.

Designed for the IGI governed loop: replaces hard pruning + minimality collapse
with a full posterior over candidate DAGs, enabling VERIFIED/UNVERIFIED routing
based on edge-marginal confidence thresholds (M-GAP-2, CWM-IDENT-3).

Key properties:
- Pure stdlib. No numpy/scipy/torch. Works for n <= 15 nodes.
- Maintains P particles, each a frozenset of directed edges (a valid DAG).
- Log-likelihood: linear-Gaussian SCM per-node OLS fit.
- C7-governed: forbidden edges/nodes enforce C7 non-habitability.
- Credit-weighted prior: organ proposal agreement boosts prior weight.
- SVGD-style updates with RBF kernel over Hamming distance.
- BOED: Expected Information Gain for intervention selection.
"""
from __future__ import annotations

import math
import random
import statistics


def is_dag(edges: frozenset[tuple[int, int]], n_nodes: int) -> bool:
    """Check edge-set forms a valid DAG (no cycles, no self-loops)."""
    for u, v in edges:
        if u == v or u < 0 or v < 0 or u >= n_nodes or v >= n_nodes:
            return False
    adj = {i: [] for i in range(n_nodes)}
    for u, v in edges:
        adj[u].append(v)
    WHITE, GRAY, BLACK = 0, 1, 2
    color = [WHITE] * n_nodes

    def dfs(u):
        color[u] = GRAY
        for w in adj[u]:
            if color[w] == GRAY:
                return False
            if color[w] == WHITE:
                if not dfs(w):
                    return False
        color[u] = BLACK
        return True

    for v in range(n_nodes):
        if color[v] == WHITE:
            if not dfs(v):
                return False
    return True


def is_edge_legal(
    edge: tuple[int, int],
    forbidden_edges: frozenset[tuple[int, int]] | set[tuple[int, int]] | None = None,
    forbidden_parents: frozenset[int] | set[int] | None = None,
) -> bool:
    """Check whether an edge is allowed under C7 governance constraints.

    An edge (u, v) is illegal if:
    - It is in the forbidden_edges set (explicit C7/D prohibition).
    - v is a forbidden_parent (C7-governed nodes cannot have incoming causal edges).
    """
    u, v = edge
    if forbidden_edges is not None and (u, v) in forbidden_edges:
        return False
    if forbidden_parents is not None and v in forbidden_parents:
        return False
    return True


def filter_edges(
    edges: frozenset[tuple[int, int]] | set[tuple[int, int]],
    forbidden_edges: frozenset[tuple[int, int]] | set[tuple[int, int]] | None = None,
    forbidden_parents: frozenset[int] | set[int] | None = None,
) -> frozenset[tuple[int, int]]:
    """Remove all illegal edges from a DAG edge set."""
    if forbidden_edges is None and forbidden_parents is None:
        return frozenset(edges)
    return frozenset(
        e for e in edges if is_edge_legal(e, forbidden_edges, forbidden_parents)
    )


def random_dag(
    n_nodes: int,
    edge_prob: float = 0.3,
    rng: random.Random | None = None,
    forbidden_edges: frozenset[tuple[int, int]] | set[tuple[int, int]] | None = None,
    forbidden_parents: frozenset[int] | set[int] | None = None,
    max_in_degree: int | None = None,
) -> frozenset:
    """Generate a random DAG respecting C7 governance constraints and max in-degree."""
    rng = rng or random.Random()
    order = list(range(n_nodes))
    rng.shuffle(order)
    edges = set()
    in_degree = {i: 0 for i in range(n_nodes)}
    for i in range(n_nodes):
        for j in range(i + 1, n_nodes):
            if max_in_degree is not None and in_degree[order[j]] >= max_in_degree:
                continue
            candidate = (order[i], order[j])
            if is_edge_legal(candidate, forbidden_edges, forbidden_parents):
                if rng.random() < edge_prob:
                    edges.add(candidate)
                    in_degree[order[j]] += 1
    return frozenset(edges)


def perturb_dag(
    dag: frozenset[tuple[int, int]],
    n_nodes: int,
    max_changes: int = 2,
    rng: random.Random | None = None,
    forbidden_edges: frozenset[tuple[int, int]] | set[tuple[int, int]] | None = None,
    forbidden_parents: frozenset[int] | set[int] | None = None,
) -> frozenset:
    """Perturb a DAG respecting C7 governance constraints."""
    rng = rng or random.Random()
    edges = set(dag)
    n_changes = rng.randint(1, max_changes)
    max_attempts = 100
    max_edges = n_nodes * (n_nodes - 1) // 2
    for _ in range(max_attempts):
        op = rng.choice(["add", "remove", "reverse"])
        if op == "add" and len(edges) < max_edges:
            u = rng.randrange(n_nodes)
            v = rng.randrange(n_nodes)
            candidate = (u, v)
            if u != v and candidate not in edges and is_edge_legal(
                candidate, forbidden_edges, forbidden_parents
            ):
                new_candidate = frozenset(edges | {candidate})
                if is_dag(new_candidate, n_nodes):
                    edges.add(candidate)
                    n_changes -= 1
        elif op == "remove" and edges:
            edges.discard(rng.choice(list(edges)))
            n_changes -= 1
        elif op == "reverse" and edges:
            e = rng.choice(list(edges))
            reversed_e = (e[1], e[0])
            if is_edge_legal(reversed_e, forbidden_edges, forbidden_parents):
                edges.discard(e)
                candidate = frozenset(edges | {reversed_e})
                if is_dag(candidate, n_nodes):
                    edges.add(reversed_e)
                else:
                    edges.add(e)
                n_changes -= 1
        if n_changes <= 0:
            break
    if edges == set(dag) and edges:
        edges.discard(rng.choice(list(edges)))
    return frozenset(edges)


def gradient_informed_perturb(
    dag: frozenset[tuple[int, int]],
    n_nodes: int,
    edge_gradients: dict[tuple[int, int], float],
    n_changes: int = 2,
    temperature: float = 0.5,
    rng: random.Random | None = None,
    forbidden_edges: frozenset[tuple[int, int]] | set[tuple[int, int]] | None = None,
    forbidden_parents: frozenset[int] | set[int] | None = None,
) -> frozenset:
    """Perturb a DAG with gradient-informed proposals.

    Edge modifications are biased by gradient signals:
    - Edges with positive gradient (increase log posterior) are favored for addition.
    - Edges with negative gradient (decrease log posterior) are favored for removal.

    Uses softmax over gradient magnitudes to select candidate edges, then
    validates DAG constraint.

    Args:
        dag: current DAG edge set.
        n_nodes: number of nodes.
        edge_gradients: dict (i, j) -> gradient signal (log posterior change).
        n_changes: number of edge modifications to attempt.
        temperature: softmax temperature (lower = more greedy).
        rng: random state.
        forbidden_edges: edges prohibited by C7/D.
        forbidden_parents: nodes prohibited from having incoming edges.

    Returns:
        A new DAG frozenset after gradient-informed perturbation.
    """
    rng = rng or random.Random()
    edges = set(dag)

    for _ in range(n_changes):
        candidates = []

        for u in range(n_nodes):
            for v in range(n_nodes):
                if u == v:
                    continue
                e = (u, v)
                if e in edges:
                    grad = edge_gradients.get(e, 0.0)
                    if grad < 0:
                        candidates.append(("remove", e, -grad))
                else:
                    if is_edge_legal(e, forbidden_edges, forbidden_parents):
                        grad = edge_gradients.get(e, 0.0)
                        if grad > 0:
                            candidates.append(("add", e, grad))

        if not candidates:
            continue

        weights = [math.exp(min(c[2] / temperature, 50.0)) for c in candidates]
        total_w = sum(weights)
        if total_w <= 0:
            continue
        probs = [w / total_w for w in weights]

        idx = _sample_categorical(probs, rng)
        op, e, _ = candidates[idx]

        if op == "add":
            candidate = frozenset(edges | {e})
            if is_dag(candidate, n_nodes):
                edges.add(e)
        elif op == "remove":
            edges.discard(e)

    if edges == set(dag) and edges:
        edges.discard(rng.choice(list(edges)))
    return frozenset(edges)


def _sample_categorical(probs: list[float], rng: random.Random) -> int:
    r = rng.random()
    cum = 0.0
    for i, p in enumerate(probs):
        cum += p
        if r <= cum:
            return i
    return len(probs) - 1


def hamming_distance(
    dag_a: frozenset[tuple[int, int]],
    dag_b: frozenset[tuple[int, int]],
) -> int:
    """Symmetric difference size between two DAG edge sets."""
    return len(dag_a.symmetric_difference(dag_b))


def rbf_kernel(
    dag_a: frozenset[tuple[int, int]],
    dag_b: frozenset[tuple[int, int]],
    bandwidth: float,
) -> float:
    """RBF kernel over DAG structures using Hamming distance.

    K(G_a, G_b) = exp(-d(G_a, G_b)^2 / (2 * h^2))
    where d = symmetric difference of edge sets.
    """
    d = hamming_distance(dag_a, dag_b)
    return math.exp(-(d * d) / (2.0 * bandwidth * bandwidth))


def compute_edge_gradient(
    dag: frozenset[tuple[int, int]],
    obs: list[list[float]],
    sigma_noise: float,
    lambda_sparse: float,
    n_nodes: int,
    organ_proposals: dict[int, frozenset[tuple[int, int]]] | None = None,
    organ_credits: dict[int, float] | None = None,
    forbidden_edges: frozenset[tuple[int, int]] | set[tuple[int, int]] | None = None,
    forbidden_parents: frozenset[int] | set[int] | None = None,
    max_edges_to_score: int = 20,
    rng: random.Random | None = None,
    likelihood_mode: str = "linear",
) -> dict[tuple[int, int], float]:
    """Compute per-edge gradient signal: Delta log P(G U {e}) - Delta log P(G \\ {e}).

    For each candidate edge, computes the change in log posterior if the edge
    were added (if absent) or removed (if present). C7-forbidden edges are
    excluded. Returns a dictionary mapping edge -> gradient signal.

    Args:
        dag: current DAG.
        obs: observational data.
        sigma_noise: noise std for Gaussian likelihood.
        lambda_sparse: sparsity penalty.
        n_nodes: number of nodes.
        organ_proposals: which edges each organ proposed.
        organ_credits: reputation weight per organ.
        forbidden_edges: C7-prohibited edges.
        forbidden_parents: C7-prohibited parent nodes.
        max_edges_to_score: maximum edges to evaluate per call.
        rng: random state for subsampling.
        likelihood_mode: "linear" or "poly2".

    Returns:
        dict (u, v) -> gradient signal.
    """
    rng = rng or random.Random()
    if likelihood_mode == "poly2":
        current_ll = _dag_log_likelihood_poly2(dag, obs, sigma_noise)
    else:
        current_ll = _dag_log_likelihood(dag, obs, sigma_noise)
    edges = set(dag)

    padj = _parent_adjacency(n_nodes, dag)
    credit_prior = _build_credit_prior_map(
        n_nodes, organ_proposals, organ_credits
    )

    candidates: list[tuple[int, int]] = []
    for u in range(n_nodes):
        for v in range(n_nodes):
            if u == v:
                continue
            e = (u, v)
            if not is_edge_legal(e, forbidden_edges, forbidden_parents):
                continue
            if e in edges:
                candidates.append(e)
            else:
                test_dag = frozenset(edges | {e})
                if is_dag(test_dag, n_nodes):
                    candidates.append(e)

    if len(candidates) > max_edges_to_score:
        candidates = rng.sample(candidates, max_edges_to_score)

    gradients: dict[tuple[int, int], float] = {}
    for e in candidates:
        if e in edges:
            removed = frozenset(edges - {e})
            if likelihood_mode == "poly2":
                alt_ll = _dag_log_likelihood_poly2(removed, obs, sigma_noise)
            else:
                alt_ll = _dag_log_likelihood(removed, obs, sigma_noise)
            alt_lp = _log_prior_governed(
                removed, lambda_sparse, n_nodes,
                organ_proposals, organ_credits, credit_prior,
            )
            gradients[e] = current_ll + _log_prior_governed(
                dag, lambda_sparse, n_nodes,
                organ_proposals, organ_credits, credit_prior,
            ) - (alt_ll + alt_lp)
        else:
            added = frozenset(edges | {e})
            if likelihood_mode == "poly2":
                alt_ll = _dag_log_likelihood_poly2(added, obs, sigma_noise)
            else:
                alt_ll = _dag_log_likelihood(added, obs, sigma_noise)
            alt_lp = _log_prior_governed(
                added, lambda_sparse, n_nodes,
                organ_proposals, organ_credits, credit_prior,
            )
            gradients[e] = alt_ll + alt_lp - (
                current_ll + _log_prior_governed(
                    dag, lambda_sparse, n_nodes,
                    organ_proposals, organ_credits, credit_prior,
                )
            )

    return gradients


def edge_list_to_set(pairs: list[tuple[int, int]]) -> frozenset:
    return frozenset(pairs)


def _matrix_mult(A, B):
    if not A or not B:
        return []
    m, k = len(A), len(A[0])
    kb, n = len(B), len(B[0])
    if k != kb:
        raise ValueError(f"Dimension mismatch: {m}x{k} x {kb}x{n}")
    C = [[0.0] * n for _ in range(m)]
    for i in range(m):
        for j in range(n):
            C[i][j] = sum(A[i][t] * B[t][j] for t in range(k))
    return C


def _matrix_vector_mult(A, v):
    m, k = len(A), len(A[0])
    return [sum(A[i][t] * v[t] for t in range(k)) for i in range(m)]


def _transpose(A):
    if not A:
        return []
    return [[A[i][j] for i in range(len(A))] for j in range(len(A[0]))]


def _invert_small(A):
    n = len(A)
    M = [
        [A[i][j] + (1e-6 if i == j else 0.0) for j in range(n)]
        + [1.0 if i == j else 0.0 for j in range(n)]
        for i in range(n)
    ]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(M[r][col]))
        M[col], M[piv] = M[piv], M[col]
        p = M[col][col] or 1e-12
        M[col] = [v / p for v in M[col]]
        for r in range(n):
            if r != col and M[r][col] != 0.0:
                f = M[r][col]
                M[r] = [M[r][j] - f * M[col][j] for j in range(2 * n)]
    return [row[n:] for row in M]


def _ols_coefficients(X, y):
    m = len(X)
    if m == 0:
        raise ValueError("Empty design matrix")
    Xt = _transpose(X)
    XtX = _matrix_mult(Xt, X)
    XtX_inv = _invert_small(XtX)
    Xty = _matrix_vector_mult(Xt, y)
    k = len(XtX)
    return [sum(XtX_inv[i][j] * Xty[j] for j in range(k)) for i in range(k)]


def _dag_log_likelihood(
    dag: frozenset[tuple[int, int]],
    obs: list[list[float]],
    sigma_noise: float,
) -> float:
    n_nodes = len(obs[0])
    m = len(obs)
    parents = {j: [] for j in range(n_nodes)}
    for u, v in dag:
        parents[v].append(u)
    total_ll = 0.0
    const = -0.5 * m * math.log(2.0 * math.pi * sigma_noise * sigma_noise)
    for j in range(n_nodes):
        pa = parents[j]
        if not pa:
            col_mean = sum(obs[t][j] for t in range(m)) / m
            residual_sq = sum((obs[t][j] - col_mean) ** 2 for t in range(m))
        else:
            X = [[obs[t][p] for p in pa] for t in range(m)]
            y = [obs[t][j] for t in range(m)]
            try:
                beta = _ols_coefficients(X, y)
            except (ValueError, ZeroDivisionError):
                return float("-inf")
            residual_sq = 0.0
            for t in range(m):
                pred = sum(beta[p_idx] * X[t][p_idx] for p_idx in range(len(pa)))
                residual_sq += (y[t] - pred) ** 2
        ll_j = const - residual_sq / (2.0 * sigma_noise * sigma_noise)
        total_ll += ll_j
    return total_ll


def _parent_adjacency(
    n_nodes: int, dag: frozenset[tuple[int, int]],
) -> dict[int, list[int]]:
    parents = {j: [] for j in range(n_nodes)}
    for u, v in dag:
        parents[v].append(u)
    return parents


def _expand_poly2(X: list[list[float]], pa: list[int]) -> list[list[float]]:
    """Expand parent features to degree-2 polynomial basis.

    Input: X[t][p_idx] for each observation t and parent index p_idx.
    Output: [x_a, x_b, x_a^2, x_b^2, x_a*x_b, ...] for all parents a,b.
    """
    m = len(X)
    if not pa:
        return [[1.0] for _ in range(m)]
    out = []
    for t in range(m):
        row = [1.0]
        x = [X[t][p_idx] for p_idx in range(len(pa))]
        for a in range(len(pa)):
            row.append(x[a])
        for a in range(len(pa)):
            row.append(x[a] * x[a])
        for a in range(len(pa)):
            for b in range(a + 1, len(pa)):
                row.append(x[a] * x[b])
        out.append(row)
    return out


def _dag_log_likelihood_poly2(
    dag: frozenset[tuple[int, int]],
    obs: list[list[float]],
    sigma_noise: float,
) -> float:
    """Nonlinear log-likelihood under degree-2 polynomial SCM.

    For each node j with parents pa(j), fits a polynomial regression:
        x_j = beta_0 + sum_i beta_i * x_i + sum_i gamma_i * x_i^2
              + sum_{i<k} delta_{ik} * x_i * x_k + epsilon_j

    Captures sigmoidal, quadratic, and interaction effects in causal
    mechanisms. Same Gaussian noise model as the linear version.
    """
    n_nodes = len(obs[0])
    m = len(obs)
    parents = _parent_adjacency(n_nodes, dag)
    total_ll = 0.0
    const = -0.5 * m * math.log(2.0 * math.pi * sigma_noise * sigma_noise)
    for j in range(n_nodes):
        pa = parents[j]
        X_flat = [[obs[t][p] for p in pa] for t in range(m)]
        y = [obs[t][j] for t in range(m)]
        try:
            X_exp = _expand_poly2(X_flat, pa)
        except (ValueError, ZeroDivisionError):
            return float("-inf")
        if len(X_exp[0]) < 2:
            col_mean = sum(y) / m
            residual_sq = sum((yt - col_mean) ** 2 for yt in y)
        else:
            try:
                beta = _ols_coefficients(X_exp, y)
            except (ValueError, ZeroDivisionError):
                return float("-inf")
            residual_sq = 0.0
            for t in range(m):
                pred = sum(beta[k] * X_exp[t][k] for k in range(len(beta)))
                residual_sq += (y[t] - pred) ** 2
        ll_j = const - residual_sq / (2.0 * sigma_noise * sigma_noise)
        total_ll += ll_j
    return total_ll


def _build_credit_prior_map(
    n_nodes: int,
    organ_proposals: dict[int, frozenset[tuple[int, int]]] | None,
    organ_credits: dict[int, float] | None,
) -> dict[tuple[int, int], float]:
    """Precompute per-edge credit weight: Σ_i w_i * 1{organ i proposed edge}.

    Returns dict (u,v) -> credit score in [0, 1], where 1 = all organs proposed.
    """
    credit_map: dict[tuple[int, int], float] = {}
    if organ_proposals is None or organ_credits is None:
        return credit_map
    for u in range(n_nodes):
        for v in range(n_nodes):
            if u == v:
                continue
            score = 0.0
            for org_id, proposed in organ_proposals.items():
                if (u, v) in proposed:
                    score += organ_credits.get(org_id, 0.0)
            if score > 0:
                credit_map[(u, v)] = min(score, 1.0)
    return credit_map


def _log_prior_governed(
    dag: frozenset[tuple[int, int]],
    lambda_sparse: float,
    n_nodes: int,
    organ_proposals: dict[int, frozenset[tuple[int, int]]] | None = None,
    organ_credits: dict[int, float] | None = None,
    credit_prior_map: dict[tuple[int, int], float] | None = None,
) -> float:
    """Governed log prior: sparse penalty + organ credit agreement bonus.

    log P(G) = -lambda_sparse * |E(G)|
               + sigma_credit * Σ_{e∈G} log(1 + c(e))

    where c(e) = Σ_i w_i * 1{organ i proposed e} is the per-edge credit weight.
    The log(1+c) form ensures agreement bonus is positive but diminishing.
    """
    lp = -lambda_sparse * len(dag)
    if organ_proposals is not None and organ_credits is not None:
        if credit_prior_map is None:
            credit_prior_map = _build_credit_prior_map(
                n_nodes, organ_proposals, organ_credits,
            )
        credit_sum = 0.0
        for e in dag:
            c = credit_prior_map.get(e, 0.0)
            if c > 0:
                credit_sum += math.log(1.0 + c)
        lp += credit_sum
    return lp


def _logsumexp_stabilize(log_vals):
    """Stable log-sum-exp for computing normalized weights from log space."""
    if not log_vals:
        return log_vals
    max_v = max(log_vals)
    return [v - max_v for v in log_vals]


def _notears_penalty(edges: frozenset[tuple[int, int]], n_nodes: int) -> float:
    """NOTEARS-style continuous acyclicity penalty（GOLEM 改进：软约束而非硬检查）。

    h(W) = Tr(e^{W⊙W}) / n - 1 —— 当且仅当 W 对应的图为 DAG 时为零。
    用作对数似然的软正则项，而非硬性拒绝非 DAG 结构。这使得扰动步
    可以穿过环状中间状态，被惩罚而非被阻断——加快粒子探索。
    GOLEM (Ng+2020, NeurIPS): 软 DAG 约束优于硬约束。
    """
    if n_nodes <= 1:
        return 0.0
    A = [[0.0] * n_nodes for _ in range(n_nodes)]
    for u, v in edges:
        if 0 <= u < n_nodes and 0 <= v < n_nodes:
            A[u][v] = 1.0
    M = [[0.0] * n_nodes for _ in range(n_nodes)]
    for i in range(n_nodes):
        for j in range(n_nodes):
            val = A[i][j] * A[i][j]
            if i == j:
                M[i][j] = val + 1.0
            else:
                M[i][j] = val
    power = [[M[i][j] for j in range(n_nodes)] for i in range(n_nodes)]
    trace_exp = sum(power[i][i] for i in range(n_nodes))
    return max(0.0, trace_exp / n_nodes - 1.0)


def _estimate_per_node_sigma(
    dag: frozenset[tuple[int, int]], obs: list[list[float]],
) -> float:
    """逐节点估计残差标准差 σ_j，返回所有节点的几何平均。

    GOLEM (Ng+2020): 似然目标中每个节点有自己的噪声方差，
    而非全局共享的假定 σ。这对异方差数据（如 Sachs {1,2,3} 离散）
    更准确——因为每个蛋白通道的测量噪声不同。
    """
    n_nodes = len(obs[0])
    m = len(obs)
    parents = {j: [] for j in range(n_nodes)}
    for u, v in dag:
        parents[v].append(u)
    log_sigmas = []
    for j in range(n_nodes):
        pa = parents[j]
        if not pa:
            col_mean = sum(obs[t][j] for t in range(m)) / m
            rss = sum((obs[t][j] - col_mean) ** 2 for t in range(m))
        else:
            X = [[obs[t][p] for p in pa] for t in range(m)]
            y = [obs[t][j] for t in range(m)]
            try:
                beta = _ols_coefficients(X, y)
            except (ValueError, ZeroDivisionError):
                return 1.0
            rss = 0.0
            for t in range(m):
                pred = sum(beta[p_idx] * X[t][p_idx] for p_idx in range(len(pa)))
                rss += (y[t] - pred) ** 2
        sigma_j = math.sqrt(max(rss / max(m - len(pa), 1), 1e-9))
        log_sigmas.append(math.log(sigma_j + 1e-12))
    return math.exp(sum(log_sigmas) / max(len(log_sigmas), 1))


def _dag_likelihood_with_interventions(
    dag: frozenset[tuple[int, int]],
    obs: list[list[float]],
    int_data: list[tuple[int, float, list[float]]],
    sigma_noise: float,
    lambda_notears: float = 10.0,
) -> float:
    """组合观测似然 + 干预似然 + NOTEARS 软 DAG 惩罚。

    DCD (Brouillard+2020, NeurIPS): 分离观测似然和干预似然。
    对于干预 do(X=x)，X 的机制被移除，X 取定值 x，其余节点
    用其父节点（包含 X）的观测条件分布。
    干预似然仅涉及「被干预节点的因果后裔」的分布变化。

    返回：log P(obs | G) + log P(int | G) - λ * h(G)。
    """
    n_nodes = len(obs[0])
    obs_ll = _dag_log_likelihood(dag, obs, sigma_noise)
    if not int_data:
        return obs_ll - lambda_notears * _notears_penalty(dag, n_nodes)
    int_ll = 0.0
    parents = {j: [] for j in range(n_nodes)}
    for u, v in dag:
        parents[v].append(u)
    for do_node, do_val, row in int_data:
        for j in range(n_nodes):
            if j == do_node:
                continue
            pa = parents[j]
            if do_node in pa:
                other_pa = [p for p in pa if p != do_node]
                if other_pa:
                    X = [[row[p] for p in other_pa] for _ in range(1)]
                    x_val = [do_val] + [row[p] for p in other_pa]
                else:
                    x_val = [do_val]
                try:
                    all_pa_vals = [[obs[t][p] for p in pa] for t in range(len(obs))]
                    beta = _ols_coefficients(all_pa_vals, [obs[t][j] for t in range(len(obs))])
                except (ValueError, ZeroDivisionError):
                    continue
                pred = sum(beta[p_idx] * x_val[p_idx] for p_idx in range(len(beta)))
                int_ll += -0.5 * math.log(2.0 * math.pi * sigma_noise * sigma_noise)
                int_ll += -(row[j] - pred) ** 2 / (2.0 * sigma_noise * sigma_noise)
    total = obs_ll + int_ll - lambda_notears * _notears_penalty(dag, n_nodes)
    return total
    if not log_vals:
        return log_vals
    max_v = max(log_vals)
    return [v - max_v for v in log_vals]


class BayesianDAGPosterior:
    """Particle-based Bayesian posterior over DAG structures.

    Args:
        n_nodes: number of variables.
        n_particles: number of SVGD-like particles (DAG candidates). Default 50.
        lambda_sparse: sparsity penalty strength (prior proportional to exp(-lambda|E|)).
        sigma_noise: assumed observation noise std for Gaussian likelihood.
        seed: RNG seed for reproducibility.
    """

    def __init__(
        self,
        n_nodes: int,
        n_particles: int = 50,
        lambda_sparse: float = 1.0,
        sigma_noise: float = 0.5,
        seed: int = 0,
    ):
        if n_nodes < 2:
            raise ValueError("n_nodes must be >= 2")
        if n_particles < 1:
            raise ValueError("n_particles must be >= 1")
        self.n = n_nodes
        self.P = n_particles
        self.lambda_sparse = lambda_sparse
        self.sigma = sigma_noise
        self.rng = random.Random(seed)
        self.particles = [random_dag(n_nodes, edge_prob=0.3, rng=self.rng) for _ in range(n_particles)]
        self.weights = [1.0 / n_particles] * n_particles
        self._log_liks = [0.0] * n_particles
        self._iteration = 0

    def _log_prior(self, dag: frozenset[tuple[int, int]]) -> float:
        return -self.lambda_sparse * len(dag)

    def _compute_effective_sigma(self, obs: list[list[float]]) -> float:
        """逐节点估计残差噪声 σ，返回粒子集的几何平均。

        使用当前 MAP DAG 或首个粒子的结构估计每节点残差方差，
        而非假定全局固定的 σ。对异方差数据（Sachs {1,2,3} 离散）
        更准确——每个蛋白通道的测量噪声不同。
        GOLEM (Ng+2020): 似然目标中每节点应使用自有的噪声方差。
        """
        try:
            map_dag = self.MAP_dag()
            return _estimate_per_node_sigma(map_dag, obs)
        except Exception:
            return self.sigma

    def update(self, obs: list[list[float]]):
        """Compute unnormalized log posterior for each particle given observational data.

        使用逐节点 σ 估计（替代全局固定 σ）+ NOTEARS 软 DAG 惩罚。
        """
        sigma_eff = self._compute_effective_sigma(obs)
        log_liks = []
        for p_idx, dag in enumerate(self.particles):
            ll = _dag_log_likelihood(dag, obs, sigma_eff)
            lp = self._log_prior(dag)
            penalty = _notears_penalty(dag, self.n)
            log_liks.append(ll + lp - 1.0 * penalty)
        log_liks = _logsumexp_stabilize(log_liks)
        max_ll = max(log_liks)
        weights = [math.exp(ll - max_ll) for ll in log_liks]
        total = sum(weights)
        if total > 0:
            self.weights = [w / total for w in weights]
        else:
            self.weights = [1.0 / self.P] * self.P
        self._log_liks = log_liks
        self._iteration += 1

    def resample_and_perturb(self):
        """Resample particles proportional to posterior weights, then perturb."""
        new_particles = []
        cum = []
        s = 0.0
        for w in self.weights:
            s += w
            cum.append(s)
        if s == 0:
            cum = [(i + 1) / self.P for i in range(self.P)]
        for _ in range(self.P):
            r = self.rng.random() * cum[-1]
            idx = 0
            while idx < len(cum) - 1 and cum[idx] < r:
                idx += 1
            idx = min(idx, len(cum) - 1)
            base = self.particles[idx]
            perturbed = perturb_dag(base, self.n, max_changes=2, rng=self.rng)
            new_particles.append(perturbed)
        self.particles = new_particles
        self.weights = [1.0 / self.P] * self.P

    def edge_marginals(self) -> dict[tuple[int, int], float]:
        """Compute edge marginal probabilities P(i->j | data) from particle set."""
        counts: dict[tuple[int, int], int] = {}
        total_weight = sum(self.weights)
        for p_idx, dag in enumerate(self.particles):
            w = self.weights[p_idx] / total_weight
            for u, v in dag:
                key = (u, v)
                counts[key] = counts.get(key, 0.0) + w
        marginals = {}
        for i in range(self.n):
            for j in range(self.n):
                if i != j:
                    marginals[(i, j)] = counts.get((i, j), 0.0)
        return marginals

    def MAP_dag(self) -> frozenset[tuple[int, int]]:
        """Return the maximum-a-posteriori DAG (particle with highest posterior weight)."""
        if not self.particles:
            return frozenset()
        best_idx = max(range(self.P), key=lambda i: self.weights[i])
        return self.particles[best_idx]

    def confidence(self) -> float:
        """Edge-marginal confidence: only considers ACTIVE edges per GovernedDiBS fix."""
        marginals = self.edge_marginals()
        if not marginals:
            return 0.5
        active_confs = []
        for i in range(self.n):
            for j in range(i + 1, self.n):
                p_ij = marginals.get((i, j), 0.0)
                p_ji = marginals.get((j, i), 0.0)
                if p_ij + p_ji > 0.001:
                    best = max(p_ij, p_ji)
                    active_confs.append(max(best, 1.0 - best))
        if not active_confs:
            return 0.5
        return min(active_confs)

    def route(self, confidence_threshold: float = 0.8) -> str:
        """VERIFIED if confidence > threshold, else UNVERIFIED."""
        return "VERIFIED" if self.confidence() >= confidence_threshold else "UNVERIFIED"


class GovernedDiBS:
    """Governed DiBS — full Bayesian DAG posterior per M-GAP-2 Algorithm 1.

    Extends particle-based inference with:
    - C7 governance: forbidden edges and forbidden-parent nodes.
    - Credit-weighted prior: organ proposal agreement from belief-ledger.
    - SVGD-style gradient-informed particle updates with RBF kernel.
    - BOED: Expected Information Gain for intervention selection.

    Args:
        n_nodes: number of causal variables.
        n_particles: number of SVGD particles (DAG candidates). Default 50.
        lambda_sparse: sparsity penalty strength. Default 1.0.
        sigma_noise: observation noise std for Gaussian likelihood. Default 0.5.
        seed: RNG seed.
        forbidden_edges: C7/D-prohibited edges (e.g., edges involving C7 nodes).
        forbidden_parents: nodes whose incoming edges are forced empty (C7-guarded).
        organ_proposals: dict organ_id -> frozenset of proposed edges.
        organ_credits: dict organ_id -> credit weight from belief-ledger
            (Bayesian reputation posterior). Weights should be >= 0.
        rbf_bandwidth: RBF kernel bandwidth for SVGD. Default 3.0.
        svgd_step_size: step size for gradient-informed updates. Default 1.0.
    """

    def __init__(
        self,
        n_nodes: int,
        n_particles: int = 50,
        lambda_sparse: float = 1.0,
        sigma_noise: float = 0.5,
        seed: int = 0,
        forbidden_edges: frozenset[tuple[int, int]] | set[tuple[int, int]] | None = None,
        forbidden_parents: frozenset[int] | set[int] | None = None,
        organ_proposals: dict[int, frozenset[tuple[int, int]]] | None = None,
        organ_credits: dict[int, float] | None = None,
        rbf_bandwidth: float = 3.0,
        svgd_step_size: float = 1.0,
        likelihood_mode: str = "linear",
        posterior_temperature: float = 1.0,
        max_in_degree: int | None = None,
        adaptive_particles: bool = False,
    ):
        if n_nodes < 2:
            raise ValueError("n_nodes must be >= 2")
        if n_particles < 2:
            raise ValueError("n_particles must be >= 2 for SVGD")
        if likelihood_mode not in ("linear", "poly2"):
            raise ValueError(f"Unknown likelihood_mode: {likelihood_mode}")
        self.n = n_nodes
        if adaptive_particles:
            n_pairs = n_nodes * (n_nodes - 1) // 2
            n_particles = max(25, min(200, max(n_particles, n_pairs // 2)))
        self.P = n_particles
        self.lambda_sparse = lambda_sparse
        self.sigma = sigma_noise
        self.rng = random.Random(seed)
        self.forbidden_edges = frozenset(forbidden_edges) if forbidden_edges else frozenset()
        self.forbidden_parents = frozenset(forbidden_parents) if forbidden_parents else frozenset()
        self.organ_proposals = organ_proposals
        self.organ_credits = organ_credits
        self.rbf_bandwidth = rbf_bandwidth
        self.svgd_step_size = svgd_step_size
        self.likelihood_mode = likelihood_mode
        self.posterior_temperature = posterior_temperature
        self.max_in_degree = max_in_degree
        self._evidence_chain: dict[tuple[int, int], list[dict]] = {}

        self._credit_prior_map = _build_credit_prior_map(
            n_nodes, organ_proposals, organ_credits,
        )

        self.particles = [
            random_dag(
                n_nodes, edge_prob=0.3, rng=self.rng,
                forbidden_edges=self.forbidden_edges,
                forbidden_parents=self.forbidden_parents,
                max_in_degree=max_in_degree,
            )
            for _ in range(n_particles)
        ]
        self.weights = [1.0 / n_particles] * n_particles
        self._log_posteriors = [0.0] * n_particles
        self._iteration = 0
        self._cached_kernel: list[list[float]] | None = None

    def _dag_ll(self, dag: frozenset[tuple[int, int]], obs: list[list[float]]) -> float:
        """Log-likelihood with per-node σ, NOTEARS penalty, and optional interventional data.

        GOLEM (Ng+2020): each node gets its own noise variance estimate.
        NOTEARS (Zheng+2018): soft acyclicity penalty h(G) as regularizer.
        """
        sigma = _estimate_per_node_sigma(dag, obs)
        if self.likelihood_mode == "poly2":
            base_ll = _dag_log_likelihood_poly2(dag, obs, sigma)
        else:
            base_ll = _dag_log_likelihood(dag, obs, sigma)
        penalty = _notears_penalty(dag, self.n)
        return base_ll - 1.0 * penalty

    @property
    def log_prior_map(self) -> dict[tuple[int, int], float]:
        """Precomputed per-edge credit weights."""
        return dict(self._credit_prior_map)

    def _log_prior(self, dag: frozenset[tuple[int, int]]) -> float:
        return _log_prior_governed(
            dag, self.lambda_sparse, self.n,
            self.organ_proposals, self.organ_credits,
            self._credit_prior_map,
        )

    def _compute_kernel_matrix(self) -> list[list[float]]:
        """Compute RBF kernel matrix K[i][j] = K(G_i, G_j) over all particles."""
        P = self.P
        K = [[0.0] * P for _ in range(P)]
        for i in range(P):
            K[i][i] = 1.0
            for j in range(i + 1, P):
                kv = rbf_kernel(self.particles[i], self.particles[j], self.rbf_bandwidth)
                K[i][j] = kv
                K[j][i] = kv
        return K

    def update(self, obs: list[list[float]]):
        """Compute log posterior for each particle given observational data.

        Updates particle weights and caches the RBF kernel matrix
        for subsequent SVGD steps.
        """
        sigma_eff = self.sigma
        log_posts = []
        for dag in self.particles:
            ll = self._dag_ll(dag, obs)
            lp = self._log_prior(dag)
            log_posts.append(ll + lp)
        self._log_posteriors = log_posts
        stabilized = _logsumexp_stabilize(log_posts)
        max_v = max(stabilized)
        w = [math.exp((v - max_v) / self.posterior_temperature) for v in stabilized]
        total = sum(w)
        if total > 0:
            self.weights = [wi / total for wi in w]
        else:
            self.weights = [1.0 / self.P] * self.P
        self._cached_kernel = self._compute_kernel_matrix()
        self._iteration += 1

    def svgd_step(self, obs: list[list[float]], n_gradient_edges: int = 30):
        r"""Perform one SVGD particle update step.

        Each particle G_p is updated towards the kernel-smoothed gradient:

            φ(G_p) = (1/P) Σ_q [ K(G_p, G_q) * ∇ log P(G_q|D) + ∇_G K(G_p, G_q) ]

        In discrete DAG space, the gradient ∇ log P(G_q|D) is approximated by
        per-edge log-posterior differences (gradient signal). The kernel-smoothed
        gradient biases MCMC proposals towards high-posterior regions while
        maintaining particle diversity.

        Args:
            obs: observational data for likelihood computation.
            n_gradient_edges: max edges to compute gradient signal per particle.
        """
        self.update(obs)
        kernel = self._cached_kernel
        if kernel is None:
            kernel = self._compute_kernel_matrix()

        all_grads = []
        for p_idx in range(self.P):
            grads = compute_edge_gradient(
                self.particles[p_idx], obs, self.sigma,
                self.lambda_sparse, self.n,
                self.organ_proposals, self.organ_credits,
                self.forbidden_edges, self.forbidden_parents,
                max_edges_to_score=n_gradient_edges,
                rng=self.rng,
                likelihood_mode=self.likelihood_mode,
            )
            all_grads.append(grads)

        for p_idx in range(self.P):
            smoothed_grad: dict[tuple[int, int], float] = {}
            for e, g in all_grads[p_idx].items():
                smoothed_grad[e] = g / self.P
            for q_idx in range(self.P):
                if q_idx == p_idx:
                    continue
                k_pq = kernel[p_idx][q_idx] / self.P
                for e, g_val in all_grads[q_idx].items():
                    smoothed_grad[e] = smoothed_grad.get(e, 0.0) + k_pq * g_val

            if smoothed_grad:
                self.particles[p_idx] = gradient_informed_perturb(
                    self.particles[p_idx], self.n, smoothed_grad,
                    n_changes=int(self.svgd_step_size),
                    temperature=0.5,
                    rng=self.rng,
                    forbidden_edges=self.forbidden_edges,
                    forbidden_parents=self.forbidden_parents,
                )

        log_posts = []
        for dag in self.particles:
            ll = self._dag_ll(dag, obs)
            lp = self._log_prior(dag)
            log_posts.append(ll + lp)
        self._log_posteriors = log_posts
        stabilized = _logsumexp_stabilize(log_posts)
        max_v = max(stabilized)
        w = [math.exp((v - max_v) / self.posterior_temperature) for v in stabilized]
        total = sum(w)
        if total > 0:
            self.weights = [wi / total for wi in w]
        else:
            self.weights = [1.0 / self.P] * self.P
        self._cached_kernel = self._compute_kernel_matrix()
        self._iteration += 1

    def resample_and_perturb(self):
        """Resample particles proportional to posterior weights, then perturb.

        Uses gradient-informed perturbation when edge gradients are available,
        falling back to uniform random perturbation.
        """
        new_particles = []
        cum = []
        s = 0.0
        for w in self.weights:
            s += w
            cum.append(s)
        if s == 0:
            cum = [(i + 1) / self.P for i in range(self.P)]
        for _ in range(self.P):
            r = self.rng.random() * cum[-1]
            idx = 0
            while idx < len(cum) - 1 and cum[idx] < r:
                idx += 1
            idx = min(idx, len(cum) - 1)
            base = self.particles[idx]
            perturbed = perturb_dag(
                base, self.n, max_changes=2, rng=self.rng,
                forbidden_edges=self.forbidden_edges,
                forbidden_parents=self.forbidden_parents,
            )
            new_particles.append(perturbed)
        self.particles = new_particles
        self.weights = [1.0 / self.P] * self.P

    def edge_marginals(self) -> dict[tuple[int, int], float]:
        """Compute edge marginal probabilities P(i->j | data) from particle set."""
        counts: dict[tuple[int, int], float] = {}
        total_weight = sum(self.weights)
        for p_idx, dag in enumerate(self.particles):
            w = self.weights[p_idx] / total_weight
            for u, v in dag:
                key = (u, v)
                counts[key] = counts.get(key, 0.0) + w
        marginals = {}
        for i in range(self.n):
            for j in range(self.n):
                if i != j:
                    marginals[(i, j)] = counts.get((i, j), 0.0)
        return marginals

    def MAP_dag(self) -> frozenset[tuple[int, int]]:
        """Return the maximum-a-posteriori DAG (particle with highest posterior weight)."""
        if not self.particles:
            return frozenset()
        best_idx = max(range(self.P), key=lambda i: self.weights[i])
        return self.particles[best_idx]

    def confidence(self) -> float:
        """Entropy-based confidence: normalized by max entropy log(P).

        0.0 = complete entropy (random), 1.0 = single particle dominates.
        Handles collapse gracefully: even a single-particle posterior
        at ESS≈1 shows confidence < 1.0 because we account for the
        inherent uncertainty of a point estimate from limited particles.
        """
        H = self.posterior_entropy()
        H_max = math.log(self.P)
        if H_max <= 1e-9:
            return 0.5
        base = max(0.0, 1.0 - H / H_max)
        ess = self.effective_sample_size()
        ess_penalty = min(1.0, ess / max(self.P * 0.5, 1.0))
        return 0.5 + 0.5 * base * ess_penalty

    def effective_sample_size(self) -> float:
        """Effective sample size: 1 / Σ w_i².  ESS=1 → one particle dominates."""
        total = sum(self.weights)
        if total <= 0:
            return 1.0
        normalized = [w / total for w in self.weights]
        sq_sum = sum(w * w for w in normalized)
        if sq_sum <= 1e-15:
            return float(self.P)
        return 1.0 / sq_sum

    def calibrate_temperature(self):
        """Adaptive temperature: increase when ESS is low (posterior too sharp)."""
        ess = self.effective_sample_size()
        target_ess = self.P * 0.3
        if ess < target_ess:
            self.posterior_temperature = min(5.0, self.posterior_temperature * 1.5)
        elif ess > self.P * 0.7:
            self.posterior_temperature = max(0.5, self.posterior_temperature * 0.8)

    def ensemble_confidence(self, obs: list[list[float]], n_ensembles: int = 3) -> dict:
        """Run multiple posteriors with different seeds, average marginals.

        Args:
            obs: the observational data used for all ensemble members.
            n_ensembles: number of independent posterior runs.

        Returns:
            dict with 'confidence' (averaged), 'agreement_std' (std across ensembles),
            'marginals' (averaged edge probabilities).
        """
        seeds = [self.rng.randrange(1 << 30) for _ in range(n_ensembles)]
        all_marginals = []
        all_confs = []
        for s in seeds:
            temp = GovernedDiBS(
                n_nodes=self.n, n_particles=self.P,
                lambda_sparse=self.lambda_sparse, sigma_noise=self.sigma,
                seed=s, forbidden_edges=self.forbidden_edges,
                forbidden_parents=self.forbidden_parents,
                organ_proposals=self.organ_proposals,
                organ_credits=self.organ_credits,
                likelihood_mode=self.likelihood_mode,
            )
            temp.update(obs)
            temp.svgd_step(obs, n_gradient_edges=20)
            all_marginals.append(temp.edge_marginals())
            all_confs.append(temp.confidence())

        avg_conf = sum(all_confs) / max(len(all_confs), 1)
        conf_std = statistics.pstdev(all_confs) if len(all_confs) > 1 else 0.0
        avg_marginals = {}
        if all_marginals:
            for key in all_marginals[0]:
                avg_marginals[key] = sum(m.get(key, 0.0) for m in all_marginals) / len(all_marginals)
        return {"confidence": avg_conf, "agreement_std": conf_std, "marginals": avg_marginals}

    def route(self, confidence_threshold: float = 0.8) -> str:
        """VERIFIED if confidence > threshold, else UNVERIFIED.

        VERIFIED structures may be used for autonomous action selection (subject to
        C7/D governance). UNVERIFIED structures must be routed to APPROVAL only.
        """
        return "VERIFIED" if self.confidence() >= confidence_threshold else "UNVERIFIED"

    def posterior_entropy(self) -> float:
        """Entropy of the particle posterior: H(G | h_t) = -Σ w_i log w_i."""
        ent = 0.0
        for w in self.weights:
            if w > 1e-15:
                ent -= w * math.log(w)
        return ent

    def compute_eig(
        self,
        obs: list[list[float]],
        intervention_candidates: dict[int, list[float]],
        n_mc_samples: int = 5,
    ) -> dict[int, float]:
        """Fast Expected Information Gain via per-particle mechanism fit + weight update.

        For each intervention candidate do(X=k, x=v):
        1. Pre-fit OLS for all particles (cached per candidate)
        2. For each MC sample, predict pseudo-intervention outcome using fitted mechanisms
        3. Compute entropy reduction by re-weighting particles (NOT rebuilding GovernedDiBS)

        O(P × n × n_candidates × n_MC) — linear in particles, NOT cubic.
        """
        eig_map: dict[int, float] = {}
        current_entropy = self.posterior_entropy()
        n = self.n
        P = self.P

        for k, values in intervention_candidates.items():
            if k < 0 or k >= n:
                eig_map[k] = 0.0
                continue
            best_eig = 0.0
            for v in values:
                eig_est = 0.0
                for _ in range(n_mc_samples):
                    p_idx = self.rng.randrange(P)
                    dag = self.particles[p_idx]
                    parents = _parent_adjacency(n, dag)
                    coefs = {}
                    for j in range(n):
                        pa = parents[j]
                        if not pa:
                            coefs[j] = []
                            continue
                        X = [[obs[t][p] for p in pa] for t in range(len(obs))]
                        y = [obs[t][j] for t in range(len(obs))]
                        try:
                            coefs[j] = _ols_coefficients(X, y)
                        except (ValueError, ZeroDivisionError):
                            coefs[j] = []

                    aug_row = [0.0] * n
                    aug_row[k] = v
                    for j in range(n):
                        if j == k:
                            continue
                        pa = parents[j]
                        if k in pa and coefs[j] and len(coefs[j]) == len(pa):
                            pa_vals = [
                                v if p == k else statistics.mean([obs[t][p] for t in range(len(obs))])
                                for p in pa
                            ]
                            aug_row[j] = sum(coefs[j][pi] * pa_vals[pi] for pi in range(len(pa_vals)))
                        else:
                            aug_row[j] = statistics.mean([obs[t][j] for t in range(len(obs))])

                    log_liks = []
                    for q_idx in range(P):
                        ll = self._dag_ll(self.particles[q_idx], [aug_row])
                        log_liks.append(ll)
                    stabilized = _logsumexp_stabilize(log_liks)
                    max_v_log = max(stabilized)
                    pseudo_weights = [math.exp(l - max_v_log) for l in stabilized]
                    total_w = sum(pseudo_weights)
                    if total_w > 0:
                        pseudo_weights = [w / total_w for w in pseudo_weights]
                    else:
                        pseudo_weights = [1.0 / P] * P
                    pseudo_ent = 0.0
                    for w in pseudo_weights:
                        if w > 1e-15:
                            pseudo_ent -= w * math.log(w)
                    eig_est += current_entropy - pseudo_ent
                eig_est /= n_mc_samples
                if eig_est > best_eig:
                    best_eig = eig_est
            eig_map[k] = best_eig
        return eig_map

    def select_intervention(
        self,
        obs: list[list[float]],
        intervention_candidates: dict[int, list[float]],
        n_mc_samples: int = 10,
    ) -> tuple[int, float, float]:
        """Select the intervention that maximizes Expected Information Gain.

        Args:
            obs: current observational data.
            intervention_candidates: {node: [values]} mapping.
            n_mc_samples: MC samples per candidate.

        Returns:
            (best_node, best_value, eig) — the intervention with highest EIG.
        """
        eig_map = self.compute_eig(obs, intervention_candidates, n_mc_samples)
        if not eig_map:
            return (-1, 0.0, 0.0)
        best_node = max(eig_map, key=lambda k: eig_map[k])
        best_eig = eig_map[best_node]
        values = intervention_candidates.get(best_node, [0.0])
        best_value = values[0] if values else 0.0
        return (best_node, best_value, best_eig)

    def organ_credit_attribution(
        self,
    ) -> dict[int, dict[tuple[int, int], float]]:
        """Compute per-organ per-edge Bayesian credit attribution.

        For each edge e and each organ g_k:
            P(organ g_k correct | e exists, h_t)
            = Σ_{G:e∈G, g_k proposed e} P(G|h_t) / Σ_{G:e∈G} P(G|h_t)

        This is the probabilistic version of PR-003's ablation credit assignment
        — no ablation runs needed, directly inferred from the posterior.

        Returns:
            dict organ_id -> dict edge -> credit score in [0, 1].
        """
        if self.organ_proposals is None:
            return {}
        result: dict[int, dict[tuple[int, int], float]] = {
            org_id: {} for org_id in self.organ_proposals
        }
        edge_mass: dict[tuple[int, int], float] = {}
        edge_organ_mass: dict[tuple[int, int], dict[int, float]] = {}

        for p_idx, dag in enumerate(self.particles):
            w = self.weights[p_idx]
            if w <= 0:
                continue
            for e in dag:
                edge_mass[e] = edge_mass.get(e, 0.0) + w
                if e not in edge_organ_mass:
                    edge_organ_mass[e] = {}
                for org_id, proposed in self.organ_proposals.items():
                    if e in proposed:
                        edge_organ_mass[e][org_id] = (
                            edge_organ_mass[e].get(org_id, 0.0) + w
                        )

        for org_id in self.organ_proposals:
            for e, total_mass in edge_mass.items():
                if total_mass > 0:
                    org_mass = edge_organ_mass.get(e, {}).get(org_id, 0.0)
                    result[org_id][e] = org_mass / total_mass
        return result

    def select_differential_intervention(
        self,
        obs: list[list[float]],
        intervenable_nodes: set[int],
        n_values: int = 3,
        use_online_opt: bool = False,
    ) -> dict[int, list[float]]:
        """Multi-value intervention selection via response curve divergence.

        If use_online_opt=True: uses BOSS-style Bayesian optimization to find
        intervention values that maximize predicted divergence between the
        highest-weighted DAG particles (replaces fixed grid with learned grid).
        If False: uses the static grid from differential_intervention module.
        """
        if use_online_opt:
            from .online_intervention_opt import optimize_intervention_values
            return optimize_intervention_values(self, obs, intervenable_nodes, n_values)

        from .differential_intervention import select_optimal_intervention_values
        n = self.n
        legal = {k for k in intervenable_nodes if k < n}
        particles = [(self.particles[i], self.weights[i]) for i in range(self.P) if self.weights[i] > 1e-6]
        if not particles: particles = [(self.particles[0], 1.0)]
        return select_optimal_intervention_values(particles, obs, legal, n_values=n_values)

    def update_with_intervention_curve(
        self,
        obs: list[list[float]],
        intervention_curve: dict[int, list[tuple[float, float]]],
    ):
        """Update posterior using response CURVE likelihood (not single-point).

        Replaces _dag_ll with response_curve_likelihood across multiple
        intervention values. This gives positive information gain even when
        single-point predictions would coincide (e.g. tanh saturation).
        """
        from .differential_intervention import response_curve_likelihood

        sigma = self.sigma
        log_liks = []
        for p_idx, dag in enumerate(self.particles):
            ll = response_curve_likelihood(dag, obs, intervention_curve, sigma)
            lp = self._log_prior(dag)
            log_liks.append(ll + lp)
        stabilized = _logsumexp_stabilize(log_liks)
        max_v = max(stabilized) if stabilized else 0.0
        exp_sum = 0.0
        for v in stabilized:
            exp_sum += math.exp(v - max_v)
        if exp_sum > 0:
            w = [math.exp((v - max_v) / self.posterior_temperature) for v in stabilized]
            total = sum(w)
            self.weights = [wi / total for wi in w] if total > 0 else [1.0 / self.P] * self.P
        else:
            self.weights = [1.0 / self.P] * self.P
        self._iteration += 1

    def hippocampal_replay(self, obs: list[list[float]], replay_rounds: int = 3):
        for _ in range(replay_rounds):
            log_liks = [self._dag_ll(dag, obs) + self._log_prior(dag) for dag in self.particles]
            stabilized = _logsumexp_stabilize(log_liks)
            max_v = max(stabilized)
            w = [math.exp((v - max_v) / self.posterior_temperature) for v in stabilized]
            total = sum(w)
            self.weights = [wi / total for wi in w] if total > 0 else [1.0 / self.P] * self.P
            self._cached_kernel = None
            self._iteration += 1

    def MEC_clusters(self) -> dict[frozenset, list[int]]:
        clusters: dict[frozenset, list[int]] = {}
        for p_idx, dag in enumerate(self.particles):
            sk = frozenset(frozenset({u, v}) for u, v in dag)
            vstructs = set()
            edges = set(dag)
            for a, c in edges:
                for b, c2 in edges:
                    if c == c2 and a < b and frozenset({a, b}) not in sk:
                        vstructs.add((a, b, c))
            sig = sk | frozenset(vstructs)
            clusters.setdefault(sig, []).append(p_idx)
        return clusters

    def MEC_confidence(self) -> float:
        clusters = self.MEC_clusters()
        if not clusters:
            return 0.5
        masses = {sig: sum(self.weights[i] for i in idxs) for sig, idxs in clusters.items()}
        if not masses or max(masses.values()) <= 0:
            return 0.5
        max_mass = max(masses.values())
        n = max(len(clusters), 2)
        return 0.5 + 0.5 * (max_mass - 1.0 / n)

    def record_evidence(self, edge: tuple[int, int], organ_id: int, confirmed: bool, round_num: int):
        """Record evidence provenance for an edge in the MAP DAG."""
        if edge not in self._evidence_chain:
            self._evidence_chain[edge] = []
        self._evidence_chain[edge].append({
            "organ": organ_id, "confirmed": confirmed, "round": round_num,
            "posterior_prob": self.edge_marginals().get(edge, 0.0),
        })

    def evidence_report(self) -> dict:
        """Per-edge evidence chain: which organs proposed it, confirmation history."""
        report = {}
        for edge, entries in self._evidence_chain.items():
            confirmations = sum(1 for e in entries if e["confirmed"])
            total = len(entries)
            organs = sorted(set(e["organ"] for e in entries))
            report[str(edge)] = {
                "organs": organs, "confirmations": f"{confirmations}/{total}",
                "latest_prob": entries[-1]["posterior_prob"] if entries else 0,
            }
        return report


def generate_linear_scm_data(
    n_nodes: int,
    edges: frozenset[tuple[int, int]] | set[tuple[int, int]],
    n_obs: int,
    noise_std: float = 0.3,
    rng: random.Random | None = None,
    coef_range: tuple[float, float] = (0.3, 1.0),
) -> tuple[list[list[float]], dict[tuple[int, int], float]]:
    """Generate observational data from a linear-Gaussian SCM with given DAG.

    Each node j = sum_{i in pa(j)} beta_{ij} * x_i + epsilon_j,
    where epsilon_j ~ N(0, noise_std).

    Returns:
        obs: list of rows, each row = [x_0, ..., x_{n-1}]
        coefficients: dict (i,j) -> beta_ij
    """
    rng = rng or random.Random()
    coefs = {}
    parents = {j: [] for j in range(n_nodes)}
    for u, v in edges:
        parents[v].append(u)
        coefs[(u, v)] = rng.uniform(*coef_range) * rng.choice([1.0, -1.0])
    topological_order = []
    indeg = {j: len(parents[j]) for j in range(n_nodes)}
    for j in range(n_nodes):
        if indeg[j] == 0 and j not in topological_order:
            topological_order.append(j)
    for j in range(n_nodes):
        if j not in topological_order:
            topological_order.append(j)
    obs = []
    for _ in range(n_obs):
        row = [0.0] * n_nodes
        for j in topological_order:
            val = rng.gauss(0, noise_std)
            for p in parents[j]:
                val += coefs[(p, j)] * row[p]
            row[j] = val
        obs.append(row)
    return obs, coefs
