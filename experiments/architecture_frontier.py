"""ADR-0047 Architecture frontier: where does HYBRID's half-budget LLM-trust break?

Sweeps D (knobs) with 2 causes + 2 confounds; finds where HYBRID starts missing a true cause
because the LLM ranked it into the un-tested tail. Reads KIMI_API_KEY from env; never persists it.
Run: KIMI_API_KEY=... PYTHONPATH=src:. python experiments/architecture_frontier.py
"""

from __future__ import annotations

import json
import os
import re
import random
import urllib.request
import urllib.error

BASE = os.environ.get("KIMI_BASE", "https://api.kimi.com/coding/v1")
MODEL = os.environ.get("KIMI_MODEL", "kimi-for-coding")
D_VALUES = (6, 12, 20)
K_CAUSES = 2
K_DECOYS = 2
OBS_N = 300
PER = 6
SEEDS = tuple(range(8))


class FrontierCausalEnv:
    def __init__(self, D: int, rng: random.Random) -> None:
        self.D = D
        self.r = rng
        idx = list(range(D)); rng.shuffle(idx)
        self.causes = idx[:K_CAUSES]
        self.decoys = idx[K_CAUSES:K_CAUSES + K_DECOYS]
        self.targets = {c: rng.randrange(2) for c in self.causes}
        self.decoy_val = {d: rng.randrange(2) for d in self.decoys}

    def reward(self, x: list[int]) -> int:
        return sum(1 for c in self.causes if x[c] == self.targets[c])

    def expert_obs(self) -> tuple[list[int], int]:
        x = [self.r.randrange(2) for _ in range(self.D)]
        for c in self.causes:
            x[c] = self.targets[c]
        for d in self.decoys:
            x[d] = self.decoy_val[d]
        return x, self.reward(x)


def kimi(prompt: str) -> str:
    key = os.environ["KIMI_API_KEY"]
    body = json.dumps({"model": MODEL, "temperature": 0,
                       "messages": [{"role": "user", "content": prompt}]}).encode()
    for attempt in range(4):
        try:
            req = urllib.request.Request(BASE + "/chat/completions", data=body,
                headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
            r = urllib.request.urlopen(req, timeout=120)
            return json.loads(r.read())["choices"][0]["message"]["content"]
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, ConnectionError):
            if attempt < 3:
                continue
            return ""
    return ""


def stats_text(env, obs) -> str:
    out = []
    for i in range(env.D):
        s = {0: [0, 0], 1: [0, 0]}
        for x, r in obs:
            s[x[i]][0] += r; s[x[i]][1] += 1
        p1 = s[1][0] / s[1][1] if s[1][1] else 0.0
        p0 = s[0][0] / s[0][1] if s[0][1] else 0.0
        out.append(f"  knob_{i}: mean reward {p1:.2f} when 1, {p0:.2f} when 0")
    return "\n".join(out)


def parse_list(text: str, D: int) -> list[int]:
    m = re.search(r"\[[\d,\s]*\]", text)
    if not m:
        return []
    try:
        return [int(x) for x in json.loads(m.group(0)) if 0 <= int(x) < D]
    except (ValueError, TypeError):
        return []


def intervene_causal(env, rng, i: int, per: int) -> bool:
    for _ in range(per):
        base = [rng.randrange(2) for _ in range(env.D)]
        flipped = list(base); flipped[i] = 1 - flipped[i]
        if env.reward(base) != env.reward(flipped):
            return True
    return False


def run_seed(D: int, seed: int) -> dict:
    rng = random.Random(seed * 97 + D)
    env = FrontierCausalEnv(D, rng)
    obs = [env.expert_obs() for _ in range(OBS_N)]
    txt = stats_text(env, obs)
    causes, decoys = set(env.causes), set(env.decoys)

    # PURE-B: full budget
    irng = random.Random(1000 + seed * 13 + D)
    b_causal = {i for i in range(D) if intervene_causal(env, irng, i, PER)}

    # PURE-A LLM
    a_text = kimi(f"A system has {D} binary knobs (knob_0..knob_{D-1}) and a reward. From OBSERVATIONS "
                  f"only (no experiments):\n{txt}\nWhich knobs CAUSE the reward? Beware confounders "
                  f"(correlated but not causal). Return ONLY a JSON array of causal knob indices.")
    a_causal = set(parse_list(a_text, D))

    # HYBRID: LLM ranks all; CWM verifies top half; trusts tail
    rank_text = kimi(f"A system has {D} binary knobs and a reward. Observations:\n{txt}\n"
                     f"You can run a few interventional experiments. Rank ALL {D} knob indices by which "
                     f"to test first (most-likely-causal first). Return ONLY a JSON array of all {D} indices.")
    order = parse_list(rank_text, D)
    seen = set(); order = [i for i in order if not (i in seen or seen.add(i))]
    for i in range(D):
        if i not in seen:
            order.append(i)
    half = max(K_CAUSES, D // 2)
    hrng = random.Random(3000 + seed * 7 + D)
    tested = order[:half]
    h_causal = {i for i in tested if intervene_causal(env, hrng, i, PER)}
    h_interv = len(tested) * PER

    # worst-cause rank: deepest position of a true cause in the LLM ranking
    worst_rank = max((order.index(c) for c in env.causes), default=D - 1)

    def cf(s):  # causes found
        return len(causes & s)
    def dc(s):  # decoys correctly non-causal
        return len(decoys - s)

    return {
        "stat_cf": cf({i for i in range(D)  # STAT flags high-corr
                       if abs(sum(r for x, r in obs if x[i] == 1) / max(1, sum(1 for x, _ in obs if x[i] == 1))
                              - sum(r for x, r in obs if x[i] == 0) / max(1, sum(1 for x, _ in obs if x[i] == 0))) > 0.3}),
        "b_cf": cf(b_causal), "a_cf": cf(a_causal), "h_cf": cf(h_causal),
        "b_dc": dc(b_causal), "a_dc": dc(a_causal), "h_dc": dc(h_causal),
        "b_interv": D * PER, "h_interv": h_interv,
        "worst_cause_rank": worst_rank, "half": half,
        "h_missed_cause": cf(h_causal) < K_CAUSES,
    }


def main() -> None:
    print(f"ADR-0047 Architecture frontier  D={D_VALUES} causes={K_CAUSES} decoys={K_DECOYS} seeds={len(SEEDS)}")
    for D in D_VALUES:
        rows = [run_seed(D, s) for s in SEEDS]
        n = len(rows)
        def a(k):
            return sum(r[k] for r in rows) / n
        print(f"\n=== D={D} (half-budget tests top {rows[0]['half']} of {D}) ===")
        print(f"  arm    | causes-found/2 | decoys-ok/2 | interventions")
        print(f"  PURE-A | {a('a_cf'):>12.2f}   | {a('a_dc'):>9.2f}   | 0")
        print(f"  PURE-B | {a('b_cf'):>12.2f}   | {a('b_dc'):>9.2f}   | {a('b_interv'):.0f}")
        print(f"  HYBRID | {a('h_cf'):>12.2f}   | {a('h_dc'):>9.2f}   | {a('h_interv'):.0f}")
        print(f"  -> HYBRID missed >=1 true cause in {a('h_missed_cause')*100:.0f}% of seeds; "
              f"avg worst-cause rank in LLM order = {a('worst_cause_rank'):.1f} (need to test this deep to catch all causes)")


if __name__ == "__main__":
    main()
