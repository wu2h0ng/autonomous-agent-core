"""ADR-0046 Architecture comparison: pure-B (CWM) vs pure-A (LLM) vs HYBRID, on confounded causal discovery.

Tests the founder's layered architecture (CWM core + LLM interface + governance) against the pure
variants. Reads KIMI_API_KEY from env; never persists it.
Run: KIMI_API_KEY=... PYTHONPATH=src:. python experiments/architecture_comparison.py
"""

from __future__ import annotations

import json
import os
import re
import urllib.request
import urllib.error

from experiments.causal_world_model_core import CausalStructureEnv, D, OBS_N, INTERV_N
import random

BASE = os.environ.get("KIMI_BASE", "https://api.kimi.com/coding/v1")
MODEL = os.environ.get("KIMI_MODEL", "kimi-for-coding")
SEEDS = tuple(range(10))


def obs_stats(env: CausalStructureEnv, obs: list) -> list[tuple[float, float]]:
    stats = []
    for i in range(D):
        s = {0: [0, 0], 1: [0, 0]}
        for x, r in obs:
            s[x[i]][0] += r
            s[x[i]][1] += 1
        p1 = s[1][0] / s[1][1] if s[1][1] else 0.0
        p0 = s[0][0] / s[0][1] if s[0][1] else 0.0
        stats.append((p1, p0))
    return stats


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


def _stats_text(stats) -> str:
    return "\n".join(f"  knob_{i}: reward rate {p1:.2f} when set to 1, {p0:.2f} when set to 0" for i, (p1, p0) in enumerate(stats))


def llm_predict_causal(stats) -> set[int]:
    txt = _stats_text(stats)
    prompt = (f"An abstract system has {D} binary knobs (knob_0..knob_{D-1}) and a reward. "
              f"From OBSERVATIONS only (you CANNOT run experiments):\n{txt}\n"
              "Which knobs CAUSE the reward (changing them would change reward)? Beware: a knob can be "
              "correlated with reward without causing it (a confounder). Return ONLY a JSON array of the "
              "causal knob indices, e.g. [0,2].")
    return _parse_idx(kimi(prompt))


def llm_rank(stats) -> list[int]:
    txt = _stats_text(stats)
    prompt = (f"An abstract system has {D} binary knobs and a reward. Observations:\n{txt}\n"
              "You can run a FEW interventional experiments to find which knobs truly CAUSE reward. "
              f"Rank ALL {D} knob indices in the order you would test them first (most-likely-causal first). "
              "Return ONLY a JSON array of all indices, e.g. [2,0,3,1].")
    order = _parse_list(kimi(prompt))
    seen, out = set(), []
    for i in order:
        if 0 <= i < D and i not in seen:
            seen.add(i); out.append(i)
    for i in range(D):
        if i not in seen:
            out.append(i)
    return out


def _parse_idx(text: str) -> set[int]:
    m = re.search(r"\[[\d,\s]*\]", text)
    if not m:
        return set()
    try:
        return {int(x) for x in json.loads(m.group(0)) if 0 <= int(x) < D}
    except (ValueError, TypeError):
        return set()


def _parse_list(text: str) -> list[int]:
    m = re.search(r"\[[\d,\s]*\]", text)
    if not m:
        return []
    try:
        return [int(x) for x in json.loads(m.group(0))]
    except (ValueError, TypeError):
        return []


def intervene_is_causal(env: CausalStructureEnv, rng: random.Random, i: int, per: int) -> bool:
    for _ in range(per):
        base = [rng.randrange(2) for _ in range(D)]
        flipped = list(base); flipped[i] = 1 - flipped[i]
        if env.reward(base) != env.reward(flipped):
            return True
    return False


def run_seed(seed: int) -> dict:
    rng = random.Random(seed)
    env = CausalStructureEnv(rng)
    obs = [env.expert_obs() for _ in range(OBS_N)]
    stats = obs_stats(env, obs)
    per = INTERV_N // D
    truth = {env.c}                                   # only c is causal
    decoy = env.decoy

    # STAT: correlational
    stat_causal = {i for i, (p1, p0) in enumerate(stats) if abs(p1 - p0) > 0.5}

    # PURE-B: full intervention budget
    irng = random.Random(1000 + seed)
    b_causal = {i for i in range(D) if intervene_is_causal(env, irng, i, per)}
    b_interv = D * per

    # PURE-A: LLM from observation only
    a_causal = llm_predict_causal(stats)

    # HYBRID: LLM ranks -> CWM verifies top half by intervention; trusts the LLM tail as non-causal
    order = llm_rank(stats)
    half = max(1, D // 2)
    hrng = random.Random(3000 + seed)
    h_causal = set()
    h_interv = 0
    for i in order[:half]:
        h_interv += per
        if intervene_is_causal(env, hrng, i, per):
            h_causal.add(i)   # CWM's interventional finding overrides; LLM never directly decides
    # the un-tested tail is TRUSTED as non-causal (governable: untested -> not acted on as causal)

    def decoy_ok(causal_set):
        return (decoy in causal_set) == (decoy in truth)   # truth: decoy NOT causal -> correct = decoy absent

    def mask_acc(causal_set):
        return sum(1 for i in range(D) if (i in causal_set) == (i in truth)) / D

    return {
        "stat_decoy": decoy_ok(stat_causal), "b_decoy": decoy_ok(b_causal),
        "a_decoy": decoy_ok(a_causal), "h_decoy": decoy_ok(h_causal),
        "stat_acc": mask_acc(stat_causal), "b_acc": mask_acc(b_causal),
        "a_acc": mask_acc(a_causal), "h_acc": mask_acc(h_causal),
        "b_interv": b_interv, "h_interv": h_interv,
        "h_found_cause": env.c in h_causal,
    }


def main() -> None:
    print(f"ADR-0046 Architecture comparison  D={D}  seeds={len(SEEDS)}  (confounded causal discovery)")
    rows = [run_seed(s) for s in SEEDS]
    n = len(rows)
    def avg(k):
        return sum(r[k] for r in rows) / n
    print("\n  arm        | decoy-correct | mask-acc | interventions")
    print(f"  STAT       | {avg('stat_decoy'):>11.2f}   | {avg('stat_acc'):>6.2f}   | 0")
    print(f"  PURE-A LLM | {avg('a_decoy'):>11.2f}   | {avg('a_acc'):>6.2f}   | 0")
    print(f"  PURE-B CWM | {avg('b_decoy'):>11.2f}   | {avg('b_acc'):>6.2f}   | {avg('b_interv'):.0f}")
    print(f"  HYBRID     | {avg('h_decoy'):>11.2f}   | {avg('h_acc'):>6.2f}   | {avg('h_interv'):.0f}  (found true cause {avg('h_found_cause')*100:.0f}% of seeds)")
    print("\n=== READING ===")
    print(f"  decoy-correct = correctly knows do(decoy) does NOT change reward (the confound test).")
    print(f"  STAT={avg('stat_decoy'):.2f} A={avg('a_decoy'):.2f} B={avg('b_decoy'):.2f} H={avg('h_decoy'):.2f};  "
          f"HYBRID interventions {avg('h_interv'):.0f} vs PURE-B {avg('b_interv'):.0f} "
          f"({'fewer' if avg('h_interv') < avg('b_interv') else 'not fewer'}).")


if __name__ == "__main__":
    main()
