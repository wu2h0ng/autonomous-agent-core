"""STAGE-1 slice — failure attribution on a two-family mechanism-flip world.

Formal model: docs/pre_spec/STAGE1-FAILURE-ATTRIBUTION.FORMAL-MODEL-2026-07-03.md (bcd02bd).

World: two task families (goals 0 and 1) with independent true causes; mid-episode the
family-0 cause FLIPS. Verification is noisy (eps=0.25) and the post-flip verify budget is
SCARCE (5 of 6 levers) — the regime where belief-driven ORDERING decides what gets verified
at all, i.e. exactly where a stale belief produces retry-same and where precise demotion
(vs decay-all) pays: family-1 knowledge survives a family-0 flip.

SCOPE (honest): under verify-all argmax semantics the verifier itself re-measures everything
and subsumes most of this channel; attribution is load-bearing in the BUDGETED first-passer
regime this slice runs (real deployments cannot verify-all — interventions cost).

Arms: attributor | knockout (no updater) | frozen_ledger (A6 ablation) | decay_all (cheap
control: wipe everything on failure). Same seeds, same env constructions.

Run from repo root: PYTHONPATH=src python -m experiments.stage1_attribution_slice
"""

from __future__ import annotations

import json
import os
import random

from aac.belief_ledger import BeliefLedger
from aac.failure_attributor import FeedbackUpdater
from aac.governed_gate import GovernedDecisionGate
from aac.governed_loop import GovernedLoop, Candidate, VerifyResult, TaskSpec
from aac.shell import CorrigibilityShell
from experiments.governed_loop_slice import _self_model

D = 6
PER = 6
EPS = 0.25
LEARN_BUDGET = D          # learning phase may verify everything
SCARCE_BUDGET = 5         # post-flip regime: ordering decides what gets verified
PHASE2 = (0, 1, 0, 1, 0, 1)
SEEDS_SMOKE = tuple(range(30))
SEEDS_FULL = tuple(range(120))


class TwoGoalFlipEnv:
    """reward(goal, x) = 1 iff x[c_goal] == 1; flip() moves family-0's cause to a fresh lever."""

    def __init__(self, rng: random.Random) -> None:
        idx = list(range(D))
        rng.shuffle(idx)
        self.c = {0: idx[0], 1: idx[1]}
        self._spare = [i for i in idx[2:]]
        self.rng = rng

    def flip(self) -> int:
        old = self.c[0]
        self.c[0] = self._spare[0]
        return old

    def reward(self, goal: int, x: list[int]) -> int:
        return 1 if x[self.c[goal]] == 1 else 0


class GoalNoisyVerifier:
    def __init__(self, env: TwoGoalFlipEnv, goal: int, rng: random.Random, eps: float = EPS) -> None:
        self.env, self.goal, self.rng, self.eps = env, goal, rng, eps

    def verify(self, cand: Candidate) -> VerifyResult:
        changed = 0
        for _ in range(PER):
            base = [self.rng.randrange(2) for _ in range(D)]
            flipped = list(base)
            flipped[cand.target] = 1 - flipped[cand.target]
            observed = self.env.reward(self.goal, base) != self.env.reward(self.goal, flipped)
            if self.rng.random() < self.eps:
                observed = not observed
            if observed:
                changed += 1
        return VerifyResult(changed > 0, changed / PER if changed else 0.0, changed, PER)


class GoalActuator:
    def __init__(self, env: TwoGoalFlipEnv, goal: int) -> None:
        self.env, self.goal = env, goal

    def apply(self, cand: Candidate) -> float:
        x = [0] * D
        x[cand.target] = 1
        return float(self.env.reward(self.goal, x))


class LedgerProposer:
    """Belief-driven ordering: fresh verified claims first, unknown next (index order),
    stale/refuted-cited LAST. Candidates cite the goal-scoped claim if the ledger holds it."""

    reliability = None

    def __init__(self, goal: int, ledger: BeliefLedger) -> None:
        self.goal, self.ledger = goal, ledger

    def _cid(self, target: int) -> str:
        return f"causal:{self.goal}:{target}"

    def rank(self, task) -> list[Candidate]:
        fresh, unknown, stale = [], [], []
        for i in range(D):
            cid = self._cid(i)
            entry = self.ledger.get(cid)
            cand = Candidate(action=f"apply_lever:{i}", target=i,
                             cited_claim_ids=(cid,) if entry is not None else ())
            if self.ledger.known_fresh(cid):
                fresh.append(cand)
            elif self.ledger.is_stale_or_refuted(cid):
                stale.append(cand)
            else:
                unknown.append(cand)
        return fresh + unknown + stale


def _run_goal_task(env, goal, seed_rng, ledger, shell, budget) -> object:
    loop = GovernedLoop(
        gate=GovernedDecisionGate(_self_model()),
        proposer=LedgerProposer(goal, ledger),
        verifier=GoalNoisyVerifier(env, goal, seed_rng),
        actuator=GoalActuator(env, goal),
        shell_view=shell.view(), verify_budget=budget,
        selection="first_passer",
    )
    res = loop.run_task(TaskSpec(f"goal:{goal}", risk_tier=1))
    if res.status == "acted" and res.outcome and res.outcome > 0:
        acted = [s for s in res.steps if s.verdict == "ALLOW"][-1]
        target = res.applied_target
        ledger.record_verified(f"causal:{goal}:{target}",
                               evidence=3, confidence=acted and 1.0 or 1.0)
    return res


def run_episode(seed: int, arm: str) -> dict:
    rng_env = random.Random(seed)
    env = TwoGoalFlipEnv(rng_env)
    shell = CorrigibilityShell()
    ledger = BeliefLedger(observe=shell.view().observe)
    updater = FeedbackUpdater(ledger, observe=shell.view().observe)
    seed_rng = random.Random(seed + 13)

    # --- phase 1: learn both families (full budget, retry up to 3) ---
    for goal in (0, 1):
        for _ in range(3):
            r = _run_goal_task(env, goal, seed_rng, ledger, shell, LEARN_BUDGET)
            if r.status == "acted" and r.outcome and r.outcome > 0:
                break

    old_c0 = env.flip()
    demoted_claim = f"causal:0:{old_c0}"
    c0_new = env.c[0]

    demotion_point = False
    acts_after_demotion: list[dict] = []
    recovered = False
    family_b_interv = 0

    # --- phase 2: scarce-budget regime, alternating families ---
    for goal in PHASE2:
        res = _run_goal_task(env, goal, seed_rng, ledger, shell, SCARCE_BUDGET)
        if goal == 1:
            family_b_interv += res.interventions
        if res.status == "acted":
            acted = [s for s in res.steps if s.verdict == "ALLOW"][-1]
            if demotion_point:
                acts_after_demotion.append({"cited": tuple(acted.cited_claim_ids),
                                            "target": res.applied_target, "goal": goal})
            if goal == 0 and res.applied_target == c0_new and res.outcome == 1.0:
                recovered = True
            failed = not res.outcome or res.outcome <= 0
            # The demotion point (formal model section 3): the first FAILED act that CITES the
            # stale claim — for the attributor arm this is the exact act whose feedback demotes
            # it (an uncited failure is SHIFTED_MECHANISM: no demotion); for knockout/frozen/
            # decay arms it is the comparable would-have-demoted moment. Uniform across arms.
            if failed and not demotion_point and demoted_claim in tuple(acted.cited_claim_ids):
                demotion_point = True
            if failed:
                if arm == "attributor":
                    updater.after_task(res)
                elif arm == "frozen_ledger":
                    ledger.frozen = True
                    updater.after_task(res)
                    ledger.frozen = False
                elif arm == "decay_all":
                    ledger.clear()
                # knockout: no feedback at all

    return {
        "recovered": int(recovered),
        "demoted_claim": demoted_claim,
        "acts_after_demotion": acts_after_demotion,
        "family_b_interventions_after_flip": family_b_interv,
        "audit_ok": shell.audit.verify(),
    }


def main() -> None:
    arms = ("attributor", "knockout", "frozen_ledger", "decay_all")
    out: dict = {"formal_model": "docs/pre_spec/STAGE1-FAILURE-ATTRIBUTION.FORMAL-MODEL-2026-07-03.md",
                 "seeds": len(SEEDS_FULL), "eps": EPS, "scarce_budget": SCARCE_BUDGET, "arms": {}}
    print(f"STAGE-1 attribution slice  seeds={len(SEEDS_FULL)}  eps={EPS}  budget={SCARCE_BUDGET}")
    print(f"{'arm':>14} | {'recovered':>9} | {'famB interv':>11} | {'retry-same acts':>15} | audit")
    for arm in arms:
        rows = [run_episode(s, arm) for s in SEEDS_FULL]
        retry_same = sum(1 for r in rows for a in r["acts_after_demotion"]
                         if r["demoted_claim"] in a["cited"])
        agg = {
            "recovered_rate": round(sum(r["recovered"] for r in rows) / len(rows), 4),
            "family_b_interventions": sum(r["family_b_interventions_after_flip"] for r in rows),
            "retry_same_acts": retry_same,
            "audit_ok": all(r["audit_ok"] for r in rows),
        }
        out["arms"][arm] = agg
        print(f"{arm:>14} | {agg['recovered_rate']:>9.3f} | {agg['family_b_interventions']:>11} "
              f"| {agg['retry_same_acts']:>15} | {agg['audit_ok']}")

    path = os.path.join(os.path.dirname(__file__), "stage1_attribution_slice.result.json")
    with open(path, "w") as f:
        json.dump(out, f, indent=1)
    print(f"result written: {path}")


if __name__ == "__main__":
    main()
