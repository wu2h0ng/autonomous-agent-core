"""InterventionChooser — AGDE-1's ~60 lines of NEW mechanism: the deterministic, contentless,
stateless min-max-split rule (packet §3; RR-0044 derivation: min-max split = maximise worst-case
bits per intervention).

Given the surviving hypothesis set and their FITTED mechanisms, each candidate node k induces a
partition of survivors by their QUANTISED predicted-shift signature under do(k=c) (hypotheses in the
same block are indistinguishable by that intervention at tolerance resolution). Choose the k whose
worst-case block is smallest; tie-break lowest node index. The rule reads ONLY partition structure —
no node semantics, no learned state, no memory across calls (contentless + stateless, disposer-
compatible; propose-only: the gate decides whether the do() executes)."""
from __future__ import annotations

from aac.structure_consistency import predict_do_means


def signature(n: int, pa: dict[int, frozenset[int]], mech: dict[int, tuple],
              k: int, c: float, baseline: list[float], tol: float) -> tuple[int, ...]:
    """Quantised predicted-shift signature of hypothesis (pa, mech) under do(k=c): buckets of width
    2*tol around the hypothesis's own baseline prediction — hypotheses within tolerance share buckets."""
    pred = predict_do_means(n, pa, mech, k, c)
    return tuple(round((pred[j] - baseline[j]) / (2.0 * tol)) for j in range(n))


def partition_blocks(n: int, survivors: list, mechs: list, k: int, c: float,
                     baselines: list[list[float]], tol: float) -> dict[tuple, list[int]]:
    blocks: dict[tuple, list[int]] = {}
    for i, (pa, mech) in enumerate(zip(survivors, mechs)):
        blocks.setdefault(signature(n, pa, mech, k, c, baselines[i], tol), []).append(i)
    return blocks


def choose(n: int, survivors: list, mechs: list, admissible: list[int], c: float,
           baselines: list[list[float]], tol: float) -> int:
    """The min-max rule. Deterministic: same inputs -> same choice, byte-stable; tie-break lowest index."""
    best_k, best_worst = None, None
    for k in sorted(admissible):
        worst = max(len(b) for b in partition_blocks(n, survivors, mechs, k, c, baselines, tol).values())
        if best_worst is None or worst < best_worst:
            best_k, best_worst = k, worst
    return best_k
