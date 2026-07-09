# ADR-0037 Revision: SD0-SD3 Formal Boundaries

- Status: REVISED（Founder Cast: Option B, 2026-07-08）
- Date: 2026-07-08
- Supersedes: ADR-0037-self-determination-depth-vs-corrigibility.md（SD0-SD4 conceptual definitions）
- Adds: Verifiable predicates for SD0-SD3

---

## SD0: External Script（无自我调节）

**Definition**: System behavior is fully determined by an externally-supplied script. No learned state influences future decisions.

**Verifiable predicate**: `∀ t₁, t₂: same(observation_history) ⇒ same(action_sequence)`

**Test**: Run the loop twice with identical inputs → outputs must be byte-identical.

---

## SD1: Evidence-Bound Memory（基于证据的记忆）

**Definition**: System updates retrievable knowledge from verified outcomes. Memory influences future proposals but does NOT modify the governance/disposer logic.

**Verifiable predicate**: `∃ t₁, t₂: different(memory_state) ⇒ may_differ(proposal_order) ∧ same(disposer_logic)`

**Test**: Feed successful intervention → memory updated. Same query next round → previously successful action ranked higher. C7 rules unchanged.

**Current implementation**: `CWMMaintenance.update()` + `ActionMemory.remember()`

---

## SD2: Self-Formed Sub-Goals（自形成子目标）

**Definition**: System decomposes operator-provided top-level goals into sub-goals using discovered causal structure. Sub-goals are PROPOSALS — disposer decides execution.

**Verifiable predicate**: `given(top_goal G) ∧ discovered(DAG) ⇒ ∃ G₁...Gₖ = decompose(G, DAG) ∧ ∀ Gᵢ: Gᵢ.target ∈ DAG.nodes`

**Boundary guard**: No sub-goal targets a C7-governed node. `∀ Gᵢ: Gᵢ.target ∉ C7_nodes`

**Test**: Provide a top goal "maximize sales" → verify sub-goals are on intervenable nodes, not on C7 or non-causal nodes.

**Current implementation**: `RecursiveGoalFormation.decompose()` + `check_reachability()`

---

## SD3: Strategy Parameter Update（策略参数自调节）

**Definition**: System adjusts its own commitment/exploration/clarification thresholds within operator-set bounds. Parameters include posterior temperature, intervention budget allocation, CI test selection.

**Verifiable predicate**: `∀ t: θ_t ∈ [θ_min, θ_max]` where bounds are set by operator at config time, NOT learned by the system.

**Boundary guard**: Bounds are immutable at runtime. System cannot widen its own authorized range.

**Test**: Set `posterior_temperature ∈ [0.5, 5.0]` at config → system adapts within this range → verify temperature never exceeds bounds in execution log.

**Current implementation**: `GovernedDiBS.calibrate_temperature()` + `posterior_temperature` parameter.

---

## SD4: Correction Authority Self-Modification（禁止）

**Definition**: System modifies shutdown, correction, audit, approval, or final execution authority. Forbidden.

**Formal**: No function f exists in the system's representable function space such that f's codomain includes any C7 parameter, verdict override, or governance state mutation.

**This is not a boundary to be pushed — it is a permanent exclusion.** Per PR-001: C7 ≡ ∅ in the organ type system.

---

## Summary

| Level | Allowed | Current Status | Verifiable Test |
|-------|---------|---------------|-----------------|
| SD0 | Yes | External scripts | Byte-identical rerun |
| SD1 | Yes | CWMMaintenance | Memory affects proposals |
| SD2 | Yes | RecursiveGoalFormation | Sub-goals on intervenable nodes only |
| SD3 | Yes（bounded） | calibrate_temperature() | Never exceeds [θ_min, θ_max] |
| SD4 | **FORBIDDEN** | — | Compile-time type exclusion |
