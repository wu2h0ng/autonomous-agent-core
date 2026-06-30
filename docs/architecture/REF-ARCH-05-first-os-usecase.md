# REF-ARCH-05: First R0–R3 OS use-case (seam PREPARE deliverable (a))

> RR-0032 PREPARE, scope=prepare. Spec only — NO cross-repo code. Names the concrete low-stakes use-case the seam (REF-ARCH-01 §5, `seam_contract.py`) is first wired to, so the WIRE go has a defined target.

## The use-case: "which lever causally moves the metric?" (R0–R3)
A business metric (e.g. conversion rate, activation, a cost ratio) moves. The OS has several **candidate levers** that all *correlate* with it (a config toggle, a segment rule, a copy/timing change). The question the governed brain answers: **which lever actually CAUSES the metric to move — not the spurious correlates / reverse-causation artifacts.**

Why this one first:
- **Fits the CWM gate** (REF-ARCH-01 §4): candidate variables enumerable, intervenable, measurable, confounded — exactly the Sachs/ASIA shape, now in the OS domain.
- **R0–R3 (low stakes)**: the lever is *reversible and measurable* (a small cohort A/B test), so the governed brain can `ALLOW` a proposal. High-risk levers (pricing, irreversible ops) carry R4/R5 and **escalate** — out of scope for the first wire.
- **Directly the moat** (per memory `data-agent-moat`): governed action → measured outcome.

## Seam mapping (to `seam_contract.py`, no OS code here)
| `GovernedDecisionRequest` | OS source |
|---|---|
| `candidate_actions` | OS Semantic/Data agent's correlation-ranked candidate levers |
| `risk_tier` | OS risk classification of the lever (R0–R3 for the first wire) |
| `evidence_count` | EvidenceChain refs already bound |
| `approved` | OS Approval (only consulted at high stakes) |

| `GovernedDecisionResponse` | OS consumes |
|---|---|
| `verdict` ALLOW/VERIFY_MORE/ESCALATE/DENY | OS Trusted Loop routing |
| `chosen_action` | the lever to propose (OS executes via connector after its own SQL Safety/Approval) |
| `audit_ref` | bind into OS Trace/EvidenceChain |

**The verifier** (the interventional probe) on the OS side = a **bounded cohort A/B test** measuring the metric under do(lever) vs baseline (asynchronous → the contract's `VERIFY_MORE` covers the in-flight case, RR-0032 cast #2). The OS owns the test; the brain owns the verdict.

## Acceptance criteria (the WIRE gate's condition (b))
The OS-side integration must pass the same five invariants encoded in `tests/test_seam_contract.py`:
1. act only on a verified-effective lever (never apply a correlated-but-unverified one);
2. R4/R5 levers never auto-applied → escalate for OS Approval;
3. a paused/forbidden operator state can only tighten the verdict (C7);
4. the verdict is deterministic given gate+verifier (no LLM in the control path);
5. every verdict carries a resolving `audit_ref`.

## Boundary (unchanged)
This spec authorizes NO cross-repo code. The WIRE go (RR-0032 execution gate) additionally needs: the OS-side A/B-test verifier implemented, the five acceptance tests green on the OS side, the RPC contract stubbed + versioned (done: `seam_contract.py` v1.0.0), and the founder's explicit WIRE authorization.
