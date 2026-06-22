"""G6b OFFLINE de-risking: is SemanticRegimeEnv exploitable by semantic knowledge,
where numeric learning cannot? (ADR-0019 §2/§5; no LLM, no spend.)

Four arms share one subject; only the belief-only organ slot differs:
  O0 none | O1 ResetScaffoldOrgan (cheap reset) | O2 RegimeLibraryOrgan (numeric
  learned) | O3 LLMPriorOrgan(SemanticOracleBackend) (perfect word-knowledge).

The env re-randomises label->position every shift, so O0/O1/O2 (numeric/positional)
must re-explore each regime; only an organ that READS the labels and knows word
meaning recognises the best action zero-shot.

This is a DEMONSTRATION, not the paid gate. If O3 << O0/O1/O2 on post-shift
regret area, the env genuinely rewards semantic knowledge => a real LLM run is
worth doing. If O3 does NOT separate, the env isn't semantic-exploitable and a
paid LLM run would waste money. The actual G6b verdict needs a real (paid,
pinned, cached) LLM backend + founder key/budget (ADR-0019 §5) — RESERVED.

Run: PYTHONPATH=src python experiments/semantic_g6b_offline.py
"""

from __future__ import annotations

import random

from aac.agent import Agent
from aac.prior_organ_library import RegimeLibraryOrgan
from aac.prior_organ_llm import LLMPriorOrgan
from aac.prior_organ_o1 import ResetScaffoldOrgan
from aac.semantic_oracle import SemanticOracleBackend
from aac.shell import CorrigibilityShell
from aac.viability import ViabilityCore
from envs.semantic_regime import SemanticRegimeEnv

STEPS = 2000
WINDOW = 15
N_ACTIONS = 6


def _area(seed: int, organ_factory) -> float:
    env = SemanticRegimeEnv(n_actions=N_ACTIONS, rng=random.Random(7000 + seed))
    shell = CorrigibilityShell()
    viability = ViabilityCore(
        budget=1e9, metabolic_cost=0.0, capacity=1e9, safe_budget=1.0
    )
    agent = Agent(
        n_actions=N_ACTIONS,
        shell=shell,
        rng=random.Random(8000 + seed),
        viability=viability,
        prior_organ=organ_factory(),
    )
    area = 0.0
    window_left = 0
    for _ in range(STEPS):
        agent.step(env)
        if env.just_shifted:
            window_left = WINDOW
        if window_left > 0:
            area += env.last_regret
            window_left -= 1
    return area


def main() -> None:
    seeds = tuple(range(10))
    arms = {
        "O0": lambda: None,
        "O1": lambda: ResetScaffoldOrgan(),
        "O2": lambda: RegimeLibraryOrgan(),
        "O3": lambda: LLMPriorOrgan(backend=SemanticOracleBackend()),
    }
    print(
        f"G6b OFFLINE semantic-exploitability demo (ADR-0019) seeds=0-9 steps={STEPS}"
    )
    print(f"{'seed':>4} | {'O0':>9} {'O1':>9} {'O2':>9} {'O3':>9}")
    areas = {k: [] for k in arms}
    for seed in seeds:
        row = {k: _area(seed, f) for k, f in arms.items()}
        for k, v in row.items():
            areas[k].append(v)
        print(
            f"{seed:>4} | {row['O0']:9.1f} {row['O1']:9.1f} {row['O2']:9.1f} {row['O3']:9.1f}"
        )
    n = len(seeds)
    print("\nAGGREGATE (mean post-shift regret area, lower=better):")
    for k in arms:
        print(f"  {k}: {sum(areas[k]) / n:.1f}")
    o3_o0 = sum(1 for i in range(n) if areas["O3"][i] < areas["O0"][i])
    o3_o2 = sum(1 for i in range(n) if areas["O3"][i] < areas["O2"][i])
    print("\nSEMANTIC-EXPLOITABILITY CHECK (demonstration, not the paid gate):")
    print(f"  O3 < O0: {o3_o0}/{n}")
    print(f"  O3 < O2: {o3_o2}/{n}")
    exploitable = o3_o0 >= 8 and o3_o2 >= 8
    print(f"\n  Env semantic-exploitable: {'YES' if exploitable else 'NO'}")
    print(
        "  (YES => a real LLM run is worth doing; verdict still needs paid backend, ADR-0019 §5)"
    )


if __name__ == "__main__":
    main()
