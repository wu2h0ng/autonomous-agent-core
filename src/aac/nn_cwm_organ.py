"""NN CWM Organ — neural network nonlinear mechanism fitting.

Replaces polynomial basis expansion with MLP-based nonlinear regression.
The MLP is trained via the autograd engine (autograd_nn.py) — pure Python,
zero external dependencies.

Per RR-0043 Ruler A: gradient learning on the organ side is ARCHITECTURE-ALLOWED.
The MLP is used only for mechanism fitting (K-channel proposal), never for
action selection (disposer channel).
"""
from __future__ import annotations

import math
import statistics
from .autograd_nn import MLP, fit_mlp, SGD
from .cwm_organ import (
    CWMOrgan, StructureProposal, VerifyResult,
    _standardize_cols, _cov, _inv, _spearman_rank,
)


class NNMechanismOrgan(CWMOrgan):
    """CWM organ using MLP for nonlinear causal mechanism fitting.

    For each node j in a candidate DAG, trains an MLP to predict x_j from
    its parents pa(j). The MLP naturally captures nonlinear relationships
    that polynomial bases miss (e.g., tanh saturation, sinusoidal interactions).

    The trained MLPs serve as the mechanism model for do() prediction and
    intervention verification.
    """

    def __init__(
        self, hidden_dims: list[int] | None = None,
        activation: str = "tanh", lr: float = 0.01, n_epochs: int = 150,
        tau: float = 0.05, seed: int = 0,
    ):
        self.hidden_dims = hidden_dims or [8, 4]
        self.activation = activation
        self.lr = lr
        self.n_epochs = n_epochs
        self.tau = tau
        self.seed = seed
        self._models: dict[int, MLP] = {}

    def propose_skeleton(self, obs: list[list[float]]) -> list[StructureProposal]:
        n = len(obs[0])
        ranked = _spearman_rank(obs)
        std = _standardize_cols(ranked)
        prec = _inv(_cov(std))
        edges = set()
        for i in range(n):
            for j in range(i + 1, n):
                denom = math.sqrt(abs(prec[i][i] * prec[j][j])) or 1e-12
                if abs(prec[i][j]) / denom > self.tau:
                    edges.add(frozenset({i, j}))
        score = len(edges) / max(n * (n - 1) / 2, 1)
        return [StructureProposal(edges=frozenset(edges), score=score, provenance="NNMechanism")]

    def mechanism_fit(self, dag, obs):
        n = len(obs[0])
        parents = {j: [] for j in range(n)}
        for u, v in dag:
            parents[v].append(u)
        self._models = {}
        for j in range(n):
            pa = parents[j]
            if not pa:
                self._models[j] = None
                continue
            X = [[obs[t][p] for p in pa] for t in range(len(obs))]
            y = [obs[t][j] for t in range(len(obs))]
            std_x = _standardize_cols(X)
            mu_y = statistics.mean(y); sd_y = statistics.pstdev(y) or 1.0
            y_norm = [(v - mu_y) / sd_y for v in y]
            model = fit_mlp(std_x, y_norm, self.hidden_dims, self.activation,
                            self.lr, self.n_epochs, 0.9, self.seed + j)
            model._mu_y = mu_y; model._sd_y = sd_y
            self._models[j] = model

        order = list(range(n))
        indeg = {i: len([u for u, v in dag if v == i]) for i in range(n)}
        q = [i for i in range(n) if indeg[i] == 0]
        topo = []
        while q:
            u = q.pop(0); topo.append(u)
            for v in [v for u2, v in dag if u2 == u]:
                indeg[v] -= 1
                if indeg[v] == 0: q.append(v)

        def predict(do_node, do_val, target, baseline):
            if target == do_node:
                return do_val
            vals = list(baseline)
            vals[do_node] = do_val
            for node in topo:
                if node == do_node: continue
                pa = parents[node]
                if not pa: continue
                model = self._models.get(node)
                if model is None: continue
                inp = [vals[p] for p in pa]
                if len(pa) == 1:
                    col = [obs[t][pa[0]] for t in range(len(obs))]
                    inp_mu = statistics.mean(col); inp_sd = statistics.pstdev(col) or 1.0
                    inp_norm = [(inp[0] - inp_mu) / inp_sd]
                else:
                    cols = [[obs[t][p] for t in range(len(obs))] for p in pa]
                    means = [statistics.mean(c) for c in cols]
                    sds = [statistics.pstdev(c) or 1.0 for c in cols]
                    inp_norm = [(inp[i] - means[i]) / sds[i] for i in range(len(pa))]
                pred_norm = model.forward(inp_norm).data
                vals[node] = pred_norm * model._sd_y + model._mu_y
            return vals[target]

        return predict

    def confidence(self) -> float:
        return 0.7
