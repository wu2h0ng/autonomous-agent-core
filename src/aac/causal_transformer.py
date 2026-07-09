"""Causal Transformer — token-level causal modeling for mechanism fitting.

PyTorch-based neural mechanism fitter using causal multi-head attention.
Replaces polynomial basis expansion with attention-based interactions between
parent variables. Captures higher-order nonlinear dependencies that OLS and
explicit polynomial bases miss.

Architecture (4 layers per ADR-0040 vision):
  1. Causal Transformer: token-level attention with causal masking
  2. Modular Architecture: NN module registry + composition
  3. Causal World Model: pixel→variable→dynamics (CRL)
  4. Agent System: causal planning + attribution + memory

This module provides layer 1: causal attention for mechanism fitting.
Layer 2 (NN module registry) is included via the NNOrganRegistry.

Requires: PyTorch (installed in .venv-torch).
Usage:
    from aac.causal_transformer import CausalTransformerOrgan
    organ = CausalTransformerOrgan(n_heads=4, n_layers=2, d_model=64)
    pred = organ.mechanism_fit(dag, obs)  # returns callable predictor
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Callable

import torch
import torch.nn as nn
import torch.nn.functional as F

from .cwm_organ import CWMOrgan, StructureProposal, _standardize_cols, _cov, _inv, _spearman_rank


class CausalAttention(nn.Module):
    """Multi-head attention with causal masking.

    Causal mask: token i can only attend to tokens j ≤ i.
    This encodes the natural ordering: causes (parents) come before effects.
    """

    def __init__(self, d_model: int = 64, n_heads: int = 4, dropout: float = 0.1):
        super().__init__()
        assert d_model % n_heads == 0
        self.n_heads = n_heads
        self.d_k = d_model // n_heads
        self.w_q = nn.Linear(d_model, d_model)
        self.w_k = nn.Linear(d_model, d_model)
        self.w_v = nn.Linear(d_model, d_model)
        self.w_o = nn.Linear(d_model, d_model)
        self.dropout = nn.Dropout(dropout)

    def forward(self, x: torch.Tensor, mask: torch.Tensor | None = None) -> torch.Tensor:
        B, T, D = x.shape
        q = self.w_q(x).view(B, T, self.n_heads, self.d_k).transpose(1, 2)
        k = self.w_k(x).view(B, T, self.n_heads, self.d_k).transpose(1, 2)
        v = self.w_v(x).view(B, T, self.n_heads, self.d_k).transpose(1, 2)
        attn = (q @ k.transpose(-2, -1)) / math.sqrt(self.d_k)
        causal_mask = torch.triu(torch.ones(T, T, device=x.device), diagonal=1).bool()
        attn = attn.masked_fill(causal_mask, float("-inf"))
        if mask is not None:
            attn = attn.masked_fill(mask.unsqueeze(1).unsqueeze(2), float("-inf"))
        attn = F.softmax(attn, dim=-1)
        attn = self.dropout(attn)
        out = (attn @ v).transpose(1, 2).contiguous().view(B, T, D)
        return self.w_o(out)


class CausalTransformerMechanism(nn.Module):
    """Causal Transformer for mechanism fitting: parents → child.

    Takes a sequence of parent values (each token = one parent variable's value,
    positionally encoded), passes through stacked causal attention layers,
    outputs predicted child value via mean pooling + MLP head.
    """

    def __init__(self, n_parents: int, d_model: int = 64, n_heads: int = 4,
                 n_layers: int = 2, dropout: float = 0.1):
        super().__init__()
        self.n_parents = max(n_parents, 1)
        self.d_model = d_model
        self.input_proj = nn.Linear(1, d_model)
        self.pos_encoding = nn.Parameter(torch.randn(1, self.n_parents, d_model) * 0.02)
        self.layers = nn.ModuleList([
            CausalAttention(d_model, n_heads, dropout) for _ in range(n_layers)
        ])
        self.norm = nn.LayerNorm(d_model)
        self.head = nn.Sequential(
            nn.Linear(d_model, d_model // 2),
            nn.ReLU(),
            nn.Linear(d_model // 2, 1),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        B = x.shape[0]
        x = x.view(B, self.n_parents, 1)
        x = self.input_proj(x) + self.pos_encoding[:, :self.n_parents, :]
        for layer in self.layers:
            x = F.relu(layer(x) + x)
        x = self.norm(x)
        x = x.mean(dim=1)
        return self.head(x).squeeze(-1)


class CausalTransformerOrgan(CWMOrgan):
    """CWM organ using causal transformer for nonlinear mechanism fitting.

    Trains a CausalTransformerMechanism per node in the DAG to predict
    each variable from its parents. The causal attention captures higher-order
    interactions between parent variables that polynomial bases miss.

    Layer 1 of the ADR-0040 architecture: causal transformer + NN module registry.
    """

    def __init__(self, d_model: int = 64, n_heads: int = 4,
                 n_layers: int = 2, lr: float = 1e-3, n_epochs: int = 300,
                 tau: float = 0.05, seed: int = 0):
        self.d_model = d_model
        self.n_heads = n_heads
        self.n_layers = n_layers
        self.lr = lr
        self.n_epochs = n_epochs
        self.tau = tau
        self.seed = seed
        self._models: dict[int, CausalTransformerMechanism] = {}
        self._device = torch.device("cpu")

    def propose_skeleton(self, obs):
        n = len(obs[0])
        ranked = _spearman_rank(obs)
        std = _standardize_cols(ranked)
        prec = _inv(_cov(std))
        edges = set()
        for i in range(n):
            for j in range(i + 1, n):
                d = math.sqrt(abs(prec[i][i] * prec[j][j])) or 1e-12
                if abs(prec[i][j]) / d > self.tau:
                    edges.add(frozenset({i, j}))
        score = len(edges) / max(n * (n - 1) / 2, 1)
        return [StructureProposal(edges=frozenset(edges), score=score, provenance="CausalTransformer")]

    def mechanism_fit(self, dag, obs):
        n = len(obs[0])
        parents = {j: [] for j in range(n)}
        for u, v in dag:
            parents[v].append(u)
        self._models = {}
        rng = random.Random(self.seed)
        for j in range(n):
            pa = parents[j]
            if len(pa) == 0:
                self._models[j] = None
                continue
            X = torch.tensor([[obs[t][p] for p in pa] for t in range(len(obs))], dtype=torch.float32)
            y = torch.tensor([obs[t][j] for t in range(len(obs))], dtype=torch.float32)
            X_mean = X.mean(dim=0, keepdim=True)
            X_std = X.std(dim=0, keepdim=True).clamp(min=1e-6)
            X_norm = (X - X_mean) / X_std
            y_mean = y.mean(); y_std = y.std().clamp(min=1e-6)
            y_norm = (y - y_mean) / y_std

            model = CausalTransformerMechanism(len(pa), self.d_model, self.n_heads, self.n_layers)
            opt = torch.optim.Adam(model.parameters(), lr=self.lr)
            for epoch in range(self.n_epochs):
                opt.zero_grad()
                pred = model(X_norm)
                loss = F.mse_loss(pred, y_norm)
                loss.backward()
                opt.step()
            model.eval()
            model._x_mean = X_mean; model._x_std = X_std
            model._y_mean = y_mean; model._y_std = y_std
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
                inp = torch.tensor([[vals[p] for p in pa]], dtype=torch.float32)
                inp_norm = (inp - model._x_mean) / model._x_std
                with torch.no_grad():
                    pred_norm = model(inp_norm).item()
                vals[node] = pred_norm * model._y_std.item() + model._y_mean.item()
            return vals[target]

        return predict

    def confidence(self) -> float:
        return 0.7


class NNOrganRegistry:
    """Layer 2: Modular NN architecture registry for organ composition.

    Registers NN-based CWM organs by capability signature. Enables
    dynamic composition: the engine can select the best organ for each
    mechanism type (linear → OLS, nonlinear → Transformer, etc.).

    Usage:
        registry = NNOrganRegistry()
        registry.register("transformer", CausalTransformerOrgan(d_model=64))
        registry.register("polynomial", PolynomialOrgan(max_degree=2))
        best = registry.best_for("nonlinear")  # → transformer
    """

    def __init__(self):
        self._organs: dict[str, CWMOrgan] = {}
        self._capabilities: dict[str, list[str]] = {}

    def register(self, name: str, organ: CWMOrgan, capabilities: list[str] | None = None):
        self._organs[name] = organ
        self._capabilities[name] = capabilities or ["nonlinear"]

    def best_for(self, capability: str) -> CWMOrgan | None:
        for name, caps in self._capabilities.items():
            if capability in caps:
                return self._organs[name]
        return None

    def all_for(self, capability: str) -> list[CWMOrgan]:
        return [self._organs[n] for n, c in self._capabilities.items() if capability in c]

    def __len__(self):
        return len(self._organs)
