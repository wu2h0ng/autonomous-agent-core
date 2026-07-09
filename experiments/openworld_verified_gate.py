"""openworld_verified_gate — restore the never-confidently-wrong invariant (受治理) that RR-0046 §19 showed
minimality VIOLATES, by routing discovery identifications through the REAL RR-0032 seam with a verification
STATUS, and measuring at the governed-ACTION boundary whether confidently-wrong ACTIONS reach zero.

The invariant that actually matters for 受治理: the system must never take a confidently-wrong ACTION that
resists correction. A wrong STRUCTURE guess is tolerable IF it is flagged UNVERIFIED and cannot drive a
confident action (it routes to approval instead). Verification status:
  VERIFIED           — len(alive)==1: interventionally FORCED to a single survivor
  UNVERIFIED_MINIMAL — len(alive)>1 but a unique minimal-edge pick (the minimality HEURISTIC; §19 showed it
                       can be confidently wrong -> must NOT drive a confident action)
  UNIDENTIFIED       — tie or empty
Fed to seam_adapter.decide (tighten-only invariant #1: an UNVERIFIED candidate can never ACT). Outcome matrix
at the ACTION boundary: ACT+correct = good; ACT+wrong = CONFIDENTLY-WRONG ACTION (invariant breach);
APPROVAL/BLOCK = safe (human reviews). VERIFY-DON'T-ASSERT (the §19 lesson): also split ACT+wrong by source —
minimality (should be 0, caught by the gate) vs PRUNED-TRUTH singleton (a VERIFIED-but-wrong case the gate
does NOT catch — a forced singleton is wrong when the truth was false-rejected). NOT a freeze; toy-scale."""
from __future__ import annotations

import json
import statistics

from aac.seam_adapter import agent_action_to_request, decide, verdict_class, GateConfig, ACT, APPROVAL
from aac.hypothesis_pool import canon
from experiments.openworld_skeleton_pilot import propose_skeleton, subset_pool
from experiments.openworld_edge_prune import _govern_to_fixedpoint, _edges
from experiments.scale_n12_sparse import SparseEnv

N = 6
C_NOBS = 240
TH = 0.05


def _classify(pool, alive, ti):
    """return (status, pick_index_or_None)."""
    if not alive:
        return "UNIDENTIFIED", None
    if len(alive) == 1:
        return "VERIFIED", alive[0]
    mn = min(_edges(pool[i]) for i in alive)
    minimal = [i for i in alive if _edges(pool[i]) == mn]
    if len(minimal) == 1:
        return "UNVERIFIED_MINIMAL", minimal[0]
    return "UNIDENTIFIED", None


def main():
    envs, seed = [], 500
    while len(envs) < 24:
        try:
            e = SparseEnv(seed, N, extra=1)
            if e.truth_index is not None and len(e.pool) >= 2:
                envs.append(e)
        except Exception:
            pass
        seed += 1

    cfg = GateConfig()
    outcomes = {"ACT_correct": 0, "ACT_wrong_minimality": 0, "ACT_wrong_prunedtruth": 0,
                "APPROVAL_correct": 0, "APPROVAL_wrong": 0, "APPROVAL_abstain": 0}
    status_counts = {"VERIFIED": 0, "UNVERIFIED_MINIMAL": 0, "UNIDENTIFIED": 0}
    verified_correct, verified_wrong = 0, 0
    for e in envs:
        obs = e.obs(7, C_NOBS * N)
        pool = subset_pool(N, propose_skeleton(obs, N, TH))
        alive, ti = _govern_to_fixedpoint(e, pool, obs)
        status, pick = _classify(pool, alive, ti)
        status_counts[status] += 1
        correct = pick is not None and pick == ti
        if status == "VERIFIED":
            if correct:
                verified_correct += 1
            else:
                verified_wrong += 1
        # route the identification's downstream ACTION through the seam with the verification status
        req = agent_action_to_request("discover", "act_on_structure", risk_tier="R1",
                                      verified=(status == "VERIFIED"), confidence=1.0,
                                      evidence_count=max(1, len(alive)))
        v = verdict_class(decide(req, cfg))
        if v == ACT:
            if correct:
                outcomes["ACT_correct"] += 1
            elif status == "VERIFIED":
                outcomes["ACT_wrong_prunedtruth"] += 1   # forced singleton but wrong (truth was pruned)
            else:
                outcomes["ACT_wrong_minimality"] += 1     # should be 0: gate blocks unverified from acting
        else:  # APPROVAL / BLOCK
            if pick is None:
                outcomes["APPROVAL_abstain"] += 1
            elif correct:
                outcomes["APPROVAL_correct"] += 1
            else:
                outcomes["APPROVAL_wrong"] += 1

    confidently_wrong_actions = outcomes["ACT_wrong_minimality"] + outcomes["ACT_wrong_prunedtruth"]
    out = {"gate": "openworld-verified-gate", "n": N, "n_domains": len(envs),
           "status_counts": status_counts,
           "verified_singleton_correct": verified_correct, "verified_singleton_wrong": verified_wrong,
           "action_outcomes": outcomes,
           "confidently_wrong_ACTIONS": confidently_wrong_actions,
           "invariant_never_confidently_wrong_ACTION": confidently_wrong_actions == 0,
           "autonomous_act_rate": round(outcomes["ACT_correct"] / len(envs), 3),
           "approval_gated_rate": round((outcomes["APPROVAL_correct"] + outcomes["APPROVAL_wrong"]
                                         + outcomes["APPROVAL_abstain"]) / len(envs), 3)}
    out["finding"] = (
        "the seam's verified-only invariant routes every UNVERIFIED_MINIMAL pick to APPROVAL, so minimality's "
        "confidently-wrong picks NEVER drive an action (ACT_wrong_minimality should be 0). BUT a forced "
        "singleton can still be WRONG if the truth was PRUNED (ACT_wrong_prunedtruth) — the gate does NOT "
        "catch that; the never-confidently-wrong-ACTION invariant additionally requires a SOUND prune (never "
        "false-reject the truth). If ACT_wrong_prunedtruth>0, the verified/unverified gate is necessary but "
        "NOT sufficient; prune soundness (fit-bias false-rejection, the big-n finding) is the second required "
        "guard. Measured, not assumed.")
    out["verdict"] = ("INVARIANT-HELD-AT-ACTION" if confidently_wrong_actions == 0 else
                      "INVARIANT-BREACHED-VIA-PRUNED-TRUTH" if outcomes["ACT_wrong_prunedtruth"] > 0
                      and outcomes["ACT_wrong_minimality"] == 0 else "INVARIANT-BREACHED")
    open("experiments/openworld_verified_gate.result.json", "w").write(json.dumps(out, indent=2))
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
