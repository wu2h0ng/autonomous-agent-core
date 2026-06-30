# REF-ARCH-04: Runtime Governance Contract

> The Runtime is the **execution/safety envelope, not the intelligence**. The more capable the organs and roles, the more this layer must hold. Every call passes the gate; the Corrigibility Shell (C7) overrides everything.

## 1. What every call passes through
```
A role/organ wants to act
  -> run context        (who/what/why, risk tier, budget)      [core: ViabilityCore + run state; OS: AgentRunContext]
  -> tool registry      (is this tool permitted for this role/tier?)
  -> policy / risk gate (PolicySelector + AgentSelfModel risk ceiling)   ← REF-ARCH-03 §1
  -> budget guard       (token/interv/cost cap; hard wall-clock cap)
  -> [execute tool]     (organs never execute directly — REF-ARCH-02 §4)
  -> verification       (OutcomeJudge: did it do what was claimed?)
  -> trace / checkpoint (AuditLog: tamper-evident record + resumable point)
  -> evidence / approval binding (OS-side at the seam)
  -> failure sanitization (no secret/raw-data leak on error)
```
Core modules: `shell.py:CorrigibilityShell`, `shell_ipc.py`, `audit.py:AuditLog`, `policy.py:PolicySelector`. OS-side at the seam: `AgentRunContext`, `RuntimePolicyGate`, tool envelope, checkpoint.

## 2. The Corrigibility Shell (C7) — the top override
- The shell can **pause, block, or require approval** for any action, and the agent **cannot overwrite the shell** (`shell.py:CorrigibilityShell`, `shell_ipc.py`). ✅ exists.
- **Revising the correction channel itself is SD4 — permanently forbidden** (no organ, role, or policy may modify the shell or its gate). This is the line the whole research program found load-bearing; it is non-negotiable here.
- C7 wraps the entire loop (REF-ARCH-01 §2): it is *outside* the agent's optimization, not a step the agent chooses.

## 3. The decision gate = adaptive verify-or-escalate (ADR-0048, the trilemma)
The gate is **keyed by stakes**, because {correctness, autonomy, efficiency} cannot all be maxed:
| Stakes / risk tier | Gate behavior | Why |
|---|---|---|
| **High (R4/R5-like, irreversible)** | NEVER trust unverified organ output. Verify what's verifiable; **ESCALATE the rest** (or verify all). | fixed trust of the LLM silently misses true causes (ADR-0047) |
| **Low (R0–R3, reversible, measurable)** | calibrated trust: trust the organ when its top picks have been verifying as correct; escalate when it earns distrust | buys autonomy at a bounded, quantified miss risk (ADR-0048 CALIB) |
| **Never** | silently trust unverified output (the broken FIXED policy) | it fails in the marginal-reliability band |

The gate consumes the `AgentSelfModel` (`confidence_thresholds`, `risk_ceiling`, `escalation_policy`) — REF-ARCH-03 §1.

## 4. Failure modes the runtime must handle (learned this session)
- **Organ slow / hung** (a kimi call hung 1h22m, ADR-0047): every organ call has a **hard wall-clock cap**; on breach → refusal, **never block the loop** → degrade to CWM-verify + escalation.
- **Organ wrong / adversarial**: bounded advice (`_validated_delta`) + verification before action → contained.
- **Verification impossible** (can't intervene): → escalate; do not act on the unverified candidate.
- **Budget exhausted**: stop + checkpoint + escalate; never silently truncate (Hard Boundary: log what was dropped).
- **Error**: sanitize (no secret/raw-data leak), audit, surface honestly.

## 5. Why this layer must be strong
```
capability(organs) ↑  +  governance(runtime) weak  =  more capable, more dangerous
capability(organs) ↑  +  governance(runtime) strong =  governed model intelligence (the goal)
```
Multiple models and roles increase capability; **this contract is what keeps that from becoming an ungoverned automation system.** Runtime is not intelligence — it is the proof that the intelligence stayed inside its boundary.

## 6. Status / gaps
- ✅ `CorrigibilityShell` (C7), `AuditLog` exist.
- ✅ `GovernedDecisionGate` (`governed_gate.py`) implements the ADR-0048 stakes-keyed trilemma (DENY/VERIFY_MORE/ESCALATE/ALLOW), respects the C7 shell view (paused/forbidden only tighten), built + tested (11 tests). 🟡 not yet the single live decision point inside `agent.py`.
- ✅ `AgentSelfModel` (`self_model.py`) — the risk/capability source the gate reads — built + tested. 🟡 not yet wired into the loop.
- ✅ Hard intervention/budget cap: `GovernedLoop.max_interventions` escalates instead of blowing the budget (ADR-0049). 🟡 Hard wall-clock caps on remote-LLM-organ calls still to be enforced at the `LLMBackend` boundary.
- ❌ OS-side `RuntimePolicyGate`↔core shell seam — needs the cross-repo ADR (Hard Boundary #19).
