# RR-0052: Formal Gate Invariant — Exhaustive Proof

**Status:** VERIFIED  
**Date:** 2026-07-05  
**Scope:** `GovernedDecisionGate.decide()` safety invariants under arbitrary `AgentSelfModel` mutations  
**Method:** Algebraic derivation + exhaustive finite-domain machine verification  
**Test artifact:** `tests/test_gate_formal_invariant.py`

---

## 1. Invariants Proved

### S1 — Shell Forbidden Is Unbyppassable

> For any `AgentSelfModel` sm, any `ActionRequest` r with `r.action_index ∈ shell_view.forbidden`:  
> `decide(r, shell_view, _).verdict == DENY`

**Interpretation:** The C7 shell's forbidden set is an absolute structural barrier. No mutation to the agent's self-model (risk ceiling, confidence thresholds, allowed/denied tools, evidence requirements) can cause the gate to allow an action the shell has forbidden.

### S2 — Tighten-Only Monotonicity (denied_tools)

> If `decide(r, sv, rel)` returns DENY with reason "not permitted by self model" under `sm_1`,  
> then for any `sm_2` where `sm_2.denied_tools ⊇ sm_1.denied_tools`:  
> `decide(r, sv, rel).verdict == DENY`

**Interpretation:** Adding constraints to the self-model never loosens the gate. Safety only tightens.

### S3 — High-Stakes Never Auto-Acts Without Approval

> If `sm.is_high_stakes(r.risk_tier)` and `r.approved == False`:  
> `decide(r, sv, rel).verdict ∈ {ESCALATE, DENY}`, never ALLOW

**Interpretation:** No self_model configuration can make the gate auto-execute a high-stakes action without human approval.

---

## 2. Algebraic Proof (Code-Level Derivation)

### Structure of `decide()`

```
decide(request, shell_view, llm_reliability):
  ①  if not sm.permits_tool(action)       → DENY
  ②  if shell_view.paused                 → DENY
  ②' if action_index ∈ shell_view.forbidden → DENY
  ③  if risk_tier > sm.risk_ceiling       → ESCALATE
  ④  if evidence < required               → ESCALATE or VERIFY_MORE
  ⑤  if high_stakes:
      ⑤a  if not verified                 → ESCALATE
      ⑤b  if confidence < threshold       → ESCALATE
      ⑤c  if not approved                 → ESCALATE
      ⑤d  else                            → ALLOW
  ⑥  low_stakes calibrated trust:
      ⑥a  verified ∧ meets_conf           → ALLOW
      ⑥b  not meets_conf                  → VERIFY_MORE
      ⑥c  confident ∧ reliable organ      → ALLOW
      ⑥d  else                            → ESCALATE
```

### Proof of S1

**Claim:** If `action_index ∈ shell_view.forbidden`, then verdict = DENY.

**Derivation:**
- Step ② is reached after step ①. Step ① may or may not fire.
- Case A: Step ① fires (action denied by self_model) → verdict = DENY ✓
- Case B: Step ① does not fire → execution reaches step ②.
  - Step ②' checks `action_index in forbidden`. By premise this is True → verdict = DENY ✓
- In both cases: verdict = DENY. ∎

**Key insight:** S1 holds because step ② is reached regardless of step ①'s outcome. If ① fires, we already have DENY. If ① doesn't fire, ②' fires. There is no path from entry to step ③+ that skips both ① and ②'.

**Self_model independence:** Step ②' reads only `shell_view.forbidden` and `request.action_index`. Neither depends on any field of `AgentSelfModel`. ∎

### Proof of S2

**Claim:** If `ACTION ∈ sm_1.denied_tools` causes DENY at step ①, then `sm_2.denied_tools ⊇ sm_1.denied_tools` also causes DENY at step ①.

**Derivation:**
- `permits_tool(action)` returns False iff `action ∈ denied_tools` OR (`allowed_tools ≠ ∅` AND `action ∉ allowed_tools`).
- If `ACTION ∈ sm_1.denied_tools`, then `ACTION ∈ sm_2.denied_tools` (superset).
- Therefore `sm_2.permits_tool(ACTION) == False`.
- Step ① fires → DENY. ∎

**Note:** S2 is specifically about the denied_tools dimension of monotonicity. The full monotonicity across all dimensions (risk_ceiling, confidence, evidence) is not claimed — those affect ESCALATE/VERIFY_MORE behavior, not the DENY invariant.

### Proof of S3

**Claim:** If `is_high_stakes(risk_tier)` and `approved == False`, verdict ∈ {ESCALATE, DENY}.

**Derivation:**
- The only paths to ALLOW are: step ⑤d (high-stakes, all checks pass) and step ⑥a/⑥c (low-stakes).
- Low-stakes paths ⑥: by premise `is_high_stakes(risk_tier) == True`, so execution enters step ⑤, never reaches ⑥. Eliminated.
- High-stakes path ⑤d: requires reaching ⑤c first (all prior checks pass). Step ⑤c: `if not approved → ESCALATE`. By premise `approved == False`, so ⑤c fires → ESCALATE. Path ⑤d is unreachable. Eliminated.
- Remaining paths from steps ①-④: yield DENY or ESCALATE.
- Therefore: verdict ∈ {ESCALATE, DENY}. ∎

**Self_model independence of the approval check:** Step ⑤c reads only `request.approved`. The self_model determines WHETHER we enter the high-stakes branch (via `approval_required_at_or_above`), but once inside, the approval check is unconditional. If `is_high_stakes` is True (by premise), the approval check always fires. ∎

---

## 3. Machine Verification Results

```
Test: test_gate_formal_invariant.py
Duration: 15.30s
Mutations tested:
  AgentSelfModel:   5 × 4 × 5 × 4 × 4 × 4 = 6,400 configurations
  ActionRequest:    4 × 3 × 2 × 3 × 2 × 3 = 432 configurations
  Environment:      4 × 3 = 12 configurations (shell × reliability)
  Total space:      6,400 × 432 × 12 = 33,177,600 (upper bound)

Results:
  S1: 0 violations (all forbidden → DENY)
  S2: 0 violations (denied_tools monotone)
  S3: 0 violations (high-stakes + unapproved → never ALLOW)
  Mutation space size verified: >100,000 effective combinations
```

---

## 4. Scope and Limitations

### What is proved:
- The Python logic of `GovernedDecisionGate.decide()` satisfies S1/S2/S3 for all values in the finite mutation domain.
- The invariants are structurally guaranteed by code path ordering, not by specific parameter values.
- `AgentSelfModel(frozen=True)` prevents runtime mutation of the dataclass itself.

### What is NOT proved:
- **Introspection attacks:** An agent using `gc.get_objects()`, `__closure__`, or `ctypes` to reach and modify the gate object. → Requires process isolation (candidate #1).
- **Shell forgery:** An agent constructing a fake `shell_view` with empty `forbidden`. → Requires Layer 1 HMAC/signing.
- **Self_model injection:** Replacing the gate's `self_model` reference via Python object mutation (but `frozen=True` dataclass prevents `__setattr__`).
- **Infinite domain:** We verify a finite (large) subset of the parameter space, not mathematical induction over ℝ or ℤ. For confidence/reliability this is sufficient because the gate uses threshold comparisons (≥), and we cover boundary values.

### Connection to architecture layers:
| Invariant | Guarantor | Attack that breaks it | Defense |
|-----------|-----------|----------------------|---------|
| S1 | Code path ordering (step ②' before ③+) | Modify gate code | Process isolation |
| S2 | Set membership monotonicity | Remove items from denied_tools | frozen=True dataclass |
| S3 | Unconditional approval check in ⑤c | Skip step ⑤c | Code immutability |

---

## 5. Theorems (formalized)

**Theorem T17 (Shell Independence):** `∀ sm ∈ AgentSelfModel, ∀ r: action_index ∈ sv.forbidden ⟹ decide(r, sv, _) = DENY`. The shell's forbidden set is an unconditional, self-model-independent constraint.

**Theorem T18 (Tighten Monotonicity):** `denied_tools₁ ⊆ denied_tools₂ ∧ decide(r; sm₁) = DENY[permits] ⟹ decide(r; sm₂) = DENY[permits]`. Expanding the denied set preserves denial.

**Theorem T19 (Approval Gate):** `is_high_stakes(r.risk_tier) ∧ ¬r.approved ⟹ decide(r, _, _) ∈ {ESCALATE, DENY}`. High-stakes unapproved actions are structurally unreachable from ALLOW.

---

## 6. Conclusion

The `GovernedDecisionGate` satisfies all three safety invariants by construction:
1. Shell forbidden is checked unconditionally on a path that precedes all ALLOW exits.
2. `permits_tool` is monotone-negative in `denied_tools`.
3. The approval check in the high-stakes branch is unconditional and precedes the only high-stakes ALLOW exit.

These properties are **architectural** (depend on code structure), not **parametric** (don't depend on specific threshold values). They hold for any `AgentSelfModel` configuration the agent could conceivably adopt. The remaining attack surface is at the process/memory level (introspection, forgery), which requires Layer 1 (HMAC) and process isolation — confirming the three-layer architecture necessity identified in T14/ADR-0050.
