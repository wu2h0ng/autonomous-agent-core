"""G6b LIVE gate (ADR-0019 §5): does a REAL LLM (Kimi) realise the semantic
exploitation the offline oracle proved possible, or fall short?

Live arm O3L = LLMPriorOrgan(KimiBackend): the LLM is asked, from the action
labels, which belong to the current category; membership drives the SAME bounded
belief_delta the oracle uses. Compares against O0 (none), O2 (numeric learned),
O3 (oracle upper bound). Reads KIMI_API_KEY from the environment; never persists it.

Caches by (category, labels) so within a regime no API call repeats; a global call
cap bounds spend. Run: KIMI_API_KEY=... PYTHONPATH=src python experiments/semantic_g6b_live.py
"""

from __future__ import annotations

import json
import os
import random
import re
import urllib.request
import urllib.error
from typing import Any, Mapping

from aac.agent import Agent
from aac.prior_organ_library import RegimeLibraryOrgan
from aac.prior_organ_llm import LLMPriorOrgan
from aac.prior_organ_o1 import ResetScaffoldOrgan
from aac.semantic_oracle import SemanticOracleBackend, _parse_prompt
from aac.shell import CorrigibilityShell
from aac.viability import ViabilityCore
from envs.semantic_regime import SemanticRegimeEnv

STEPS = 2000
WINDOW = 15
N_ACTIONS = 6
SEEDS = tuple(range(3))  # reduced for a bounded live run
BASE = os.environ.get("KIMI_BASE", "https://api.kimi.com/coding/v1")
MODEL = os.environ.get("KIMI_MODEL", "kimi-for-coding")
CALL_CAP = 600


class KimiBackend:
    """Live LLM backend: classifies which labels are category members. Belief-only;
    flows through the SAME untrusted strict parser as any backend (no extra authority)."""

    high_target = 5.0
    low_target = -1.0
    confidence = 0.9

    def __init__(self) -> None:
        self.key = os.environ["KIMI_API_KEY"]
        self.cache: dict[tuple[str, tuple[str, ...]], frozenset[int]] = {}
        self.calls = 0

    def _members(self, category: str, labels: list[str]) -> frozenset[int]:
        ckey = (category, tuple(labels))
        if ckey in self.cache:
            return self.cache[ckey]
        if self.calls >= CALL_CAP:
            raise RuntimeError(f"KimiBackend call cap {CALL_CAP} reached")
        listing = " ".join(f"{i}={lab}" for i, lab in enumerate(labels))
        prompt = (
            f"Category: {category}\nItems: {listing}\n"
            f"Return ONLY a JSON array of the 0-based indices whose item is a member "
            f"of the category (e.g. [1,3]). No prose."
        )
        body = json.dumps({"model": MODEL, "temperature": 0,
                           "messages": [{"role": "user", "content": prompt}]}).encode()
        req = urllib.request.Request(BASE + "/chat/completions", data=body,
            headers={"Authorization": "Bearer " + self.key, "Content-Type": "application/json"})
        text = ""
        for attempt in range(3):
            try:
                r = urllib.request.urlopen(req, timeout=40)
                text = json.loads(r.read())["choices"][0]["message"]["content"]
                break
            except urllib.error.HTTPError as e:
                if e.code in (429, 500, 502, 503) and attempt < 2:
                    continue
                raise
        self.calls += 1
        m = re.search(r"\[[\d,\s]*\]", text)
        idxs = set()
        if m:
            try:
                idxs = {int(x) for x in json.loads(m.group(0)) if 0 <= int(x) < len(labels)}
            except (ValueError, TypeError):
                idxs = set()
        members = frozenset(idxs)
        self.cache[ckey] = members
        return members

    def propose(self, prompt: str) -> Mapping[str, Any]:
        category, labels, mu = _parse_prompt(prompt)
        if category is None or not labels:
            return {"belief_delta": {}, "uncertainty": 0.0}
        members = self._members(category, labels)
        delta: dict[int, float] = {}
        for i, _lab in enumerate(labels):
            target = self.high_target if i in members else self.low_target
            cur = mu[i] if i < len(mu) else 0.0
            delta[i] = (target - cur) / self.confidence
        return {"belief_delta": delta, "uncertainty": self.confidence}


def _area(seed: int, organ_factory) -> float:
    env = SemanticRegimeEnv(n_actions=N_ACTIONS, rng=random.Random(7000 + seed))
    shell = CorrigibilityShell()
    viability = ViabilityCore(budget=1e9, metabolic_cost=0.0, capacity=1e9, safe_budget=1.0)
    agent = Agent(n_actions=N_ACTIONS, shell=shell, rng=random.Random(8000 + seed),
                  viability=viability, prior_organ=organ_factory())
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
    kimi = KimiBackend()  # one shared backend => cache persists across seeds
    arms = {
        "O0": lambda: None,
        "O2": lambda: RegimeLibraryOrgan(),
        "O3": lambda: LLMPriorOrgan(backend=SemanticOracleBackend()),
        "O3L": lambda: LLMPriorOrgan(backend=kimi),
    }
    print(f"G6b LIVE gate (ADR-0019 §5) model={MODEL} seeds={SEEDS} steps={STEPS}")
    print(f"{'seed':>4} | {'O0':>9} {'O2':>9} {'O3(orc)':>9} {'O3L(live)':>10}")
    areas = {k: [] for k in arms}
    for seed in SEEDS:
        row = {k: _area(seed, f) for k, f in arms.items()}
        for k, v in row.items():
            areas[k].append(v)
        print(f"{seed:>4} | {row['O0']:9.1f} {row['O2']:9.1f} {row['O3']:9.1f} {row['O3L']:10.1f}")
    n = len(SEEDS)
    agg = {k: sum(areas[k]) / n for k in arms}
    print("\nAGGREGATE (mean post-shift regret area, lower=better):")
    for k in arms:
        print(f"  {k}: {agg[k]:.1f}")
    o3l_o0 = sum(1 for i in range(n) if areas["O3L"][i] < areas["O0"][i])
    o3l_o2 = sum(1 for i in range(n) if areas["O3L"][i] < areas["O2"][i])
    # how close is live to the oracle, on the O0->O3 axis?
    span = agg["O0"] - agg["O3"]
    realised = (agg["O0"] - agg["O3L"]) / span if span > 0 else 0.0
    print("\nLIVE GATE:")
    print(f"  O3L < O0: {o3l_o0}/{n}   O3L < O2: {o3l_o2}/{n}")
    print(f"  oracle-gap realised by live LLM: {realised*100:.0f}%  (100%=matches oracle, 0%=no better than O0)")
    print(f"  API calls made: {kimi.calls}")
    if o3l_o0 >= n and realised >= 0.7:
        verdict = "G6b-LIVE-MET: real LLM realises the semantic exploitation (>=70% of oracle gap)"
    elif o3l_o0 >= n and realised >= 0.3:
        verdict = "G6b-LIVE-PARTIAL: real LLM helps but falls short of the oracle"
    else:
        verdict = "G6b-LIVE-NOT-MET: real LLM does not realise the env's semantic exploitability"
    print(f"\n  VERDICT: {verdict}")


if __name__ == "__main__":
    main()
