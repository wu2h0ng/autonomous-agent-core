"""Torch Attention Causal Prior — cross-domain edge prediction with learned attention.

Trains a neural network on 5000+ synthetic SCMs to predict edge probabilities
from domain features. Uses multi-head attention over edge pairs to capture
structural regularities across domains.

Architecture (inspired by ADAG, Yin+2025):
1. Domain encoder: MLP(features) → domain_embedding (128-dim)
2. Per edge pair: concat[domain_embedding, positional_encoding(i,j)] → MLP → prob
3. Multi-head attention over all edge pairs for structural context
4. Training: MSE between predicted and true edge probabilities

This scales beyond the K-NN prior saturation point (500 domains) because
the parametric model can learn nonlinear feature→edge mappings that
nearest-neighbor averaging cannot.

Requirements: torch (pip installed into .venv-torch)
Run with: PYTHONPATH=src .venv-torch/bin/python experiments/torch_prior_train.py
"""
from __future__ import annotations

import math
import random
import statistics
from typing import Callable

import torch
import torch.nn as nn
import torch.nn.functional as F

from .cwm_organ import _standardize_cols, _cov, _inv

MAX_NODES = 20
MAX_PAIRS = MAX_NODES * (MAX_NODES - 1) // 2  # 190


class DomainFeatureExtractor:
    """Extract 12-dim features from observational data + mechanism info."""

    _MECH_MAP = {"linear": 0, "tanh": 1, "poly": 2, "sin": 3}

    @staticmethod
    def extract(obs: list[list[float]], mechanism: str = "linear") -> list[float]:
        n_nodes = len(obs[0]); n_obs = len(obs)
        try:
            std = _standardize_cols(obs); prec = _inv(_cov(std))
        except (ValueError, ZeroDivisionError):
            return [n_nodes/15, math.log(max(n_obs,1))/10, 0,0,0,0,0,0,0,0,0,0]
        pcs = []
        adj = {i: set() for i in range(n_nodes)}
        for i in range(n_nodes):
            for j in range(i+1, n_nodes):
                d = math.sqrt(abs(prec[i][i]*prec[j][j])) or 1e-12
                pc = abs(prec[i][j]) / d; pcs.append(pc)
                if pc > 0.01: adj[i].add(j); adj[j].add(i)
        n_p = max(n_nodes*(n_nodes-1)//2, 1)
        degs = [len(adj[i]) for i in range(n_nodes)]
        tris = 0
        for i in range(n_nodes):
            for j in adj[i]:
                if j > i:
                    for k in (adj[i] & adj[j]):
                        if k > j: tris += 1
        n_tri = max(sum(d*(d-1) for d in degs), 1)
        return [
            n_nodes/15.0, math.log(max(n_obs,1))/10.0,
            statistics.mean(pcs) if pcs else 0,
            statistics.pstdev(pcs) if len(pcs)>1 else 0,
            max(pcs) if pcs else 0,
            sum(1 for p in pcs if p>0.01)/n_p,
            sum(1 for p in pcs if p>0.05)/n_p,
            statistics.mean(degs)/10 if degs else 0,
            max(degs)/10 if degs else 0,
            (3.0*tris)/n_tri,
            -sum((d/max(sum(degs),1))*math.log(max(d/max(sum(degs),1),1e-12)) for d in degs)/max(math.log(n_nodes),1),
            DomainFeatureExtractor._MECH_MAP.get(mechanism, 0)/3.0,
        ]

    @staticmethod
    def edge_target_vector(
        obs: list[list[float]], n_nodes: int, true_edges: frozenset,
    ) -> list[float]:
        vec = [0.0] * MAX_PAIRS
        try:
            std = _standardize_cols(obs); prec = _inv(_cov(std))
            ts = frozenset(true_edges)
            idx = 0
            for i in range(n_nodes):
                for j in range(i+1, n_nodes):
                    d = math.sqrt(abs(prec[i][i]*prec[j][j])) or 1e-12
                    pc = abs(prec[i][j]) / d
                    is_t = frozenset({i,j}) in {frozenset(e) for e in ts}
                    vec[idx] = pc * 0.5 + (1.0 if is_t else 0.0) * 0.5
                    idx += 1
        except (ValueError, ZeroDivisionError):
            pass
        return vec


class AttentionCausalPrior(nn.Module):
    """Attention-based causal edge prior — predicts P(edge|domain_features)."""

    def __init__(self, feat_dim: int = 12, embed_dim: int = 128,
                 n_heads: int = 4, dropout: float = 0.1):
        super().__init__()
        self.domain_encoder = nn.Sequential(
            nn.Linear(feat_dim, embed_dim),
            nn.ReLU(),
            nn.Linear(embed_dim, embed_dim * 2),
            nn.ReLU(),
            nn.Linear(embed_dim * 2, embed_dim),
        )
        self.pos_encoder = nn.Linear(2, embed_dim)
        self.attention = nn.MultiheadAttention(embed_dim, n_heads,
                                                dropout=dropout, batch_first=True)
        self.edge_predictor = nn.Sequential(
            nn.Linear(embed_dim, embed_dim // 2),
            nn.ReLU(),
            nn.Linear(embed_dim // 2, 1),
            nn.Sigmoid(),
        )

    def forward(self, features: torch.Tensor, n_pairs: int) -> torch.Tensor:
        batch_size = features.shape[0]
        dom_emb = self.domain_encoder(features)
        positions = torch.stack([
            torch.arange(n_pairs, device=features.device) % MAX_NODES,
            torch.arange(n_pairs, device=features.device) // MAX_NODES,
        ], dim=-1).float() / MAX_NODES
        pos_emb = self.pos_encoder(positions)
        seq = dom_emb.unsqueeze(1).expand(-1, n_pairs, -1) + pos_emb.unsqueeze(0)
        seq_attn, _ = self.attention(seq, seq, seq)
        probs = self.edge_predictor(seq_attn).squeeze(-1)
        return probs


def generate_training_batch(
    batch_size: int, n_nodes_range: tuple[int, int] = (4, 14),
    n_obs_range: tuple[int, int] = (50, 500),
    noise_range: tuple[float, float] = (0.1, 1.0),
    mechanisms: list[str] | None = None,
    seed: int = 0,
) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
    if mechanisms is None:
        mechanisms = ["linear", "tanh", "poly"]
    rng = random.Random(seed)
    features_batch = []; targets_batch = []; n_pairs_list = []
    for _ in range(batch_size):
        n = rng.randint(*n_nodes_range); n_obs = rng.randint(*n_obs_range)
        noise = rng.uniform(*noise_range); mech = rng.choice(mechanisms)
        edges = set()
        for i in range(n):
            for j in range(i+1, n):
                if rng.random() < rng.uniform(0.1, 0.5): edges.add((i,j))
        if len(edges) < 2: edges = {(0,1),(1,2)}
        obs, true_edges = _gen_data(n, frozenset(edges), n_obs, noise, mech, rng)
        feats = DomainFeatureExtractor.extract(obs, mech)
        targets = DomainFeatureExtractor.edge_target_vector(obs, n, true_edges)
        features_batch.append(feats); targets_batch.append(targets)
        n_pairs_list.append(n * (n - 1) // 2)
    return (
        torch.tensor(features_batch, dtype=torch.float32),
        torch.tensor(targets_batch, dtype=torch.float32),
        torch.tensor(n_pairs_list, dtype=torch.long),
    )


def _gen_data(n, edges, n_obs, noise, mech, rng):
    if mech == "linear":
        from .bayesian_dag_posterior import generate_linear_scm_data
        return generate_linear_scm_data(n, edges, n_obs, noise, rng=rng)
    parents = {j: [] for j in range(n)}
    coefs = {}
    for u, v in edges: parents[v].append(u); coefs[(u,v)] = rng.uniform(0.4,1.0)*rng.choice([1.0,-1.0])
    obs = []
    for _ in range(n_obs):
        row = [0.0]*n
        for j in range(n):
            val = rng.gauss(0, noise)
            for p in parents[j]:
                if mech == "tanh": val += coefs[(p,j)]*math.tanh(row[p]*1.5)
                elif mech == "poly": val += coefs[(p,j)]*(row[p]+0.3*row[p]**2)
            row[j] = val
        obs.append(row)
    return obs, edges


def train_model(
    model: AttentionCausalPrior, n_steps: int = 50000,
    batch_size: int = 64, lr: float = 1e-3, seed: int = 42,
):
    opt = torch.optim.Adam(model.parameters(), lr=lr)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(opt, n_steps)
    random.seed(seed)
    losses = []
    for step in range(n_steps):
        feats, targets, n_pairs = generate_training_batch(
            batch_size, seed=step * 12345,
        )
        preds = model(feats, MAX_PAIRS)
        loss = torch.tensor(0.0)
        count = 0
        for b in range(batch_size):
            n_p = n_pairs[b].item()
            if n_p > 0:
                mse = F.mse_loss(preds[b, :n_p], targets[b, :n_p])
                loss = loss + mse; count += 1
        if count > 0:
            loss = loss / count
            opt.zero_grad(); loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step(); scheduler.step()
            losses.append(loss.item())
        if (step + 1) % 5000 == 0:
            avg = statistics.mean(losses[-1000:]) if len(losses) >= 1000 else statistics.mean(losses)
            print(f"  step {step+1}/{n_steps}  loss={avg:.4f}")
    return losses


def predict_priors(model: AttentionCausalPrior, obs: list[list[float]],
                   mechanism: str = "linear") -> dict[tuple[int, int], float]:
    n_nodes = len(obs[0]); n_pairs = n_nodes * (n_nodes - 1) // 2
    feats = DomainFeatureExtractor.extract(obs, mechanism)
    with torch.no_grad():
        preds = model(torch.tensor([feats], dtype=torch.float32), MAX_PAIRS)
        probs = preds[0, :n_pairs].tolist()
    result = {}
    idx = 0
    for i in range(n_nodes):
        for j in range(i + 1, n_nodes):
            result[(i, j)] = max(0.01, min(0.99, probs[idx] if idx < len(probs) else 0.1))
            idx += 1
    return result
