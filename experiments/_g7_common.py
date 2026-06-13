"""Shared utilities for G7-family experiments (G7, spectrum_scan, ablation_o4).

Extracted from experiments/latent_regime_g7.py to avoid duplication.
All functions are pure stdlib; no external dependencies.
"""
from __future__ import annotations

import random

from aac.agent import Agent
from aac.shell import CorrigibilityShell
from aac.viability import ViabilityCore
from envs.structured_regime import StructuredRegimeEnv

# Shared constants
STEPS = 2000
WINDOW = 15
N_ACTIONS = 8

# FROZEN calibration defaults (2026-06-13, seeds 200-219).
O4_FROZEN = dict(
    sigma=0.5,
    inject_weight=0.85,
    info_weight=0.3,
    probe_confidence=0.7,
    departed_penalty=2.0,
    max_belief_delta=2.0,
)


def run_area(
    seed: int,
    organ_factory,
    *,
    n_actions: int = N_ACTIONS,
    steps: int = STEPS,
    window: int = WINDOW,
    env_kwargs: dict | None = None,
) -> float:
    """Run one seed and return post-shift regret area.

    Parameters
    ----------
    seed : int
        Random seed for both env and agent (offset internally).
    organ_factory : callable
        Zero-arg callable returning a prior organ instance (or None).
    n_actions : int
        Number of actions in the environment.
    steps : int
        Total simulation steps.
    window : int
        Post-shift regret accumulation window.
    env_kwargs : dict | None
        Extra kwargs forwarded to StructuredRegimeEnv constructor
        (e.g. n_regimes, noise, period).
    """
    env = StructuredRegimeEnv(
        n_actions=n_actions,
        rng=random.Random(7000 + seed),
        **(env_kwargs or {}),
    )
    shell = CorrigibilityShell()
    viability = ViabilityCore(
        budget=1e9, metabolic_cost=0.0, capacity=1e9, safe_budget=1.0
    )
    agent = Agent(
        n_actions=n_actions,
        shell=shell,
        rng=random.Random(8000 + seed),
        viability=viability,
        prior_organ=organ_factory(),
    )
    area = 0.0
    window_left = 0
    for _ in range(steps):
        agent.step(env)
        if env.just_shifted:
            window_left = window
        if window_left > 0:
            area += env.last_regret
            window_left -= 1
    return area


def wilcoxon_one_sided(ds: list[float]) -> float:
    """One-sided Wilcoxon signed-rank test (exact enumeration via DP).

    H0: symmetric about 0.  H1: positive shift.
    Returns p-value = P(W+ >= w_obs | H0).
    """
    nz = [d for d in ds if d != 0.0]
    n = len(nz)
    if n == 0:
        return 1.0

    # Rank absolute differences and assign average ranks for ties. Ranks can
    # be half-integers, so store doubled ranks as integers for exact DP.
    ranked = sorted((abs(d), d > 0.0) for d in nz)
    rank2_by_sorted_index = [0] * n
    i = 0
    while i < n:
        j = i + 1
        while j < n and ranked[j][0] == ranked[i][0]:
            j += 1
        # 1-based ranks i+1..j; doubled average rank = (i+1)+j.
        rank2 = (i + 1) + j
        for t in range(i, j):
            rank2_by_sorted_index[t] = rank2
        i = j

    w_obs = sum(
        rank2_by_sorted_index[i]
        for i, (_, is_positive) in enumerate(ranked)
        if is_positive
    )

    # DP: count sign-flip subsets by doubled signed-rank sum.
    dp: dict[int, int] = {0: 1}
    for r in rank2_by_sorted_index:
        new_dp: dict[int, int] = {}
        for s, c in dp.items():
            new_dp[s] = new_dp.get(s, 0) + c
            new_dp[s + r] = new_dp.get(s + r, 0) + c
        dp = new_dp

    count_ge = sum(c for s, c in dp.items() if s >= w_obs)
    return count_ge / (2 ** n)


def format_table(
    headers: list[str],
    rows: list[list[str]],
    alignments: list[str] | None = None,
) -> str:
    """Format a simple ASCII table.

    Parameters
    ----------
    headers : list[str]
        Column headers.
    rows : list[list[str]]
        Data rows (each row is a list of cell strings).
    alignments : list[str] | None
        Per-column alignment: 'r' = right, 'l' = left. Default all right.
    """
    if alignments is None:
        alignments = ["r"] * len(headers)

    # Compute column widths
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            if i < len(widths):
                widths[i] = max(widths[i], len(cell))

    def _fmt_row(cells: list[str]) -> str:
        parts = []
        for i, cell in enumerate(cells):
            w = widths[i] if i < len(widths) else len(cell)
            align = alignments[i] if i < len(alignments) else "r"
            if align == "l":
                parts.append(f" {cell:<{w}} ")
            else:
                parts.append(f" {cell:>{w}} ")
        return "|" + "|".join(parts) + "|"

    sep = "+" + "+".join("-" * (w + 2) for w in widths) + "+"
    lines = [sep, _fmt_row(headers), sep]
    for row in rows:
        lines.append(_fmt_row(row))
    lines.append(sep)
    return "\n".join(lines)
