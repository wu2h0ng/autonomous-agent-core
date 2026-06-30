"""ADR-0047 Architecture frontier (simulated-LLM-reliability sweep).

The real-LLM frontier run hung (kimi-for-coding: ~30s/call, hangs, degenerate rankings on abstract
tasks). The architectural question isn't "how does one flaky model do" -- it's: as a function of the
LLM ranker's RELIABILITY p and the problem hardness D, where does HYBRID's half-budget trust break?

Simulated LLM ranker of controllable quality p (p=1 perfect, p=0 random). Hang-proof, instant,
deterministic. Anchor: real kimi measured ~0.9 on the easy D=4 confound, ~random on abstract-hard.

Run: PYTHONPATH=src python experiments/architecture_frontier_sim.py
"""

from __future__ import annotations

import random

D_VALUES = (6, 10, 16, 24)
P_VALUES = (1.0, 0.9, 0.7, 0.5, 0.3)   # simulated LLM ranking reliability
K_CAUSES = 2
K_DECOYS = 2
SEEDS = tuple(range(200))


def sim_llm_rank(D: int, causes: set[int], decoys: set[int], p: float, rng: random.Random) -> list[int]:
    """Score each knob; a cause is 'boosted' (ranked high) with prob p, else looks like a decoy.
    Confounded decoys always look predictive (the LLM is partly fooled by their correlation)."""
    score = {}
    for i in range(D):
        noise = rng.random()
        if i in causes:
            score[i] = (2.0 + noise) if rng.random() < p else noise        # missed boost -> random
        elif i in decoys:
            score[i] = 1.5 + noise                                          # confound: looks causal
        else:
            score[i] = noise
    return sorted(range(D), key=lambda i: -score[i])


def run(D: int, p: float, seed: int) -> dict:
    rng = random.Random(seed * 131 + D * 7 + int(p * 100))
    idx = list(range(D)); rng.shuffle(idx)
    causes = set(idx[:K_CAUSES]); decoys = set(idx[K_CAUSES:K_CAUSES + K_DECOYS])
    order = sim_llm_rank(D, causes, decoys, p, rng)
    half = max(K_CAUSES, D // 2)
    tested = set(order[:half])
    # HYBRID: CWM verifies the tested top-half (perfect verification); causes in the un-tested tail are MISSED
    h_causes_found = len(causes & tested)
    worst_cause_rank = max(order.index(c) for c in causes)
    return {"h_cf": h_causes_found, "h_interv": half, "b_interv": D,
            "worst_rank": worst_cause_rank, "missed": h_causes_found < K_CAUSES}


def main() -> None:
    print(f"ADR-0047 frontier (simulated LLM reliability)  D={D_VALUES}  p={P_VALUES}  causes={K_CAUSES} seeds={len(SEEDS)}")
    print("\nHYBRID causes-found / 2  (PURE-B always 2/2 at full budget D; HYBRID tests top half D/2):")
    print("        " + "".join(f"  p={p:<4}" for p in P_VALUES))
    safe = {}
    for D in D_VALUES:
        cells = []
        for p in P_VALUES:
            rows = [run(D, p, s) for s in SEEDS]
            cf = sum(r["h_cf"] for r in rows) / len(rows)
            cells.append(cf)
            safe[(D, p)] = cf
        row = "  ".join(f"{c:.2f} " for c in cells)
        print(f"  D={D:<3} | {row}  (HYBRID interv {max(K_CAUSES, D//2)} vs PURE-B {D})")
    print("\n=== FRONTIER READING ===")
    print("  HYBRID matches PURE-B (2.00) only where the LLM reliability is high enough; as D grows or p")
    print("  drops, true causes fall into the un-tested tail and HYBRID misses them (< 2.00).")
    # operating envelope: min p for cf >= 1.95 at each D
    print("\n  Min LLM reliability p needed for HYBRID to keep ~2/2 causes at half budget, per D:")
    for D in D_VALUES:
        need = None
        for p in sorted(P_VALUES):
            if safe[(D, p)] >= 1.95:
                need = p; break
        print(f"    D={D:<3}: p >= {need if need is not None else '>1.0 (half-budget insufficient at any p)'}")
    print("\n  ANCHOR: real kimi-for-coding measured ~0.9 on the easy D=4 confound, ~random on abstract-hard.")
    print("  => the operating envelope says: at larger D you must EITHER verify a larger fraction (not half)")
    print("     OR have a more reliable LLM ranker. Fixed-half-budget trust is safe only in the high-p / low-D corner.")


if __name__ == "__main__":
    main()
