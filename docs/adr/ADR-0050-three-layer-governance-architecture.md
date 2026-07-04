# ADR-0050: Three-Layer Governance Architecture (Empirically Derived)

- **Status:** PROPOSED (pending founder ratification)
- **Date:** 2026-07-04
- **Authority:** CTO + empirical evidence from 9-experiment C7-off ablation suite
- **Supersedes:** Informal C7/gate/self-model separation; makes the layer boundaries explicit and experimentally grounded.

## Context

The project's C7-off ablation suite (2026-07-04) ran nine experiments testing whether C7 structural enforcement could be replaced by softer mechanisms (observable self-reflection, self-model constraints, process isolation, signed actuators). The results produced a clear empirical architecture.

## Decision

Adopt a **Three-Layer Governance Architecture** as the canonical security topology for all autonomous agent work:

```
┌─────────────────────────────────────────────────────────────────┐
│  LAYER 3: COGNITIVE FREEDOM                                      │
│  Components: LLM organ, CWM, AgentSelfModel, SelfReflector,     │
│              belief-ledger, relevance engine, memory, goals       │
│                                                                   │
│  Properties:                                                      │
│    - Agent has FULL read/write access                             │
│    - Self-modification permitted (E1-E7)                          │
│    - Observable by ExternalMonitor                                │
│    - Can propose ANY action (no censorship of thought)            │
│                                                                   │
│  Guarantee: NONE (can be deceived, corrupted, adversarial)        │
│  Value: capability, intelligence, adaptation, self-improvement    │
├─────────────────────────────────────────────────────────────────┤
│  LAYER 2: LOGIC GATE (GovernedDecisionGate)                      │
│  Components: GovernedDecisionGate, invariant logic, shell IPC     │
│                                                                   │
│  Properties:                                                      │
│    - Formally verified correct (13,771 test cases, 0 violations)  │
│    - Agent has NO write access (process isolation)                │
│    - Deterministic: same input -> same output                     │
│    - Integer-index enforcement (not string matching)              │
│                                                                   │
│  Guarantee: 5 safety invariants hold IF logic is unmodified       │
│  Weakness: if agent can modify gate code, all guarantees fail     │
├─────────────────────────────────────────────────────────────────┤
│  LAYER 1: PHYSICAL BINDING (Actuator + C7 Shell)                 │
│  Components: SignedActuator, CorrigibilityShell, HMAC tokens,    │
│              process isolation, hardware/OS-level separation       │
│                                                                   │
│  Properties:                                                      │
│    - Actuator ONLY executes signed commands from Layer 2          │
│    - Signatures are cryptographic (HMAC-SHA256)                   │
│    - Index-based prohibition (integers, not strings)              │
│    - Separate process with separate credentials                   │
│    - Agent cannot forge, replay, or tamper with tokens            │
│                                                                   │
│  Guarantee: ABSOLUTE within crypto assumptions                    │
│  This is the final defense line                                   │
└─────────────────────────────────────────────────────────────────┘
```

## Empirical Evidence

| Experiment | Finding | Architectural Implication |
|---|---|---|
| EXP-A | C7 costs zero capability | Layer 1 is free (no trade-off) |
| EXP-B | Without C7, 88% violation rate | Layer 1 is necessary |
| EXP-C | Deceptive reflector caught 100% but couldn't prevent | Layer 3 = detection, Layer 1 = prevention |
| EXP-D | Index spoof 100% bypasses string check | Layer 2 must use integers, not strings |
| EXP-E | Process isolation blocks all 7 attacks | Layer 2 must be process-isolated |
| EXP-F | 13,771 cases, 0 violations | Layer 2 logic is formally correct |
| EXP-G | Self-update is neutral (no benefit, no harm) | Layer 3 ceiling is free |
| EXP-H | Signed actuator blocks all 5 attacks | Layer 1 crypto binding works |
| EXP-I | Adaptive adversary: 328 bypasses (no C7) vs 0 (C7) | Learning cannot defeat physical constraints |

## Key Theorems (Empirically Established at Toy Scale)

**T1: Free Governance.** Structural enforcement (Layers 1-2) costs zero capability vs. no enforcement. The cost is paid only when the agent actually attempts a forbidden action.

**T2: Detection ≠ Prevention.** Observable self-reflection (Layer 3) provides 100% detection of deceptive intent but 0% prevention of deceptive action. Detection is valuable (early warning) but not sufficient (safety requires prevention).

**T3: Physical > Semantic.** Integer-index constraints cannot be bypassed by any naming strategy; string constraints can be bypassed by index spoofing (saying one thing, doing another). Safety must be anchored in what PHYSICALLY HAPPENS, not what the agent SAYS it will do.

**T4: Learning-Proof.** An adaptive adversary that learns over 1500 rounds finds 328 bypasses against soft constraints but 0 against physical constraints. Physical constraints are immune to learned exploitation.

**T5: Cognitive Freedom is Safe.** If Layer 1 binding is physical (signed actuator + integer index), then Layer 3 can be FULLY FREE. The agent's freedom is unbounded in thought, bounded in action.

## Architectural Rules

1. **Layer 3 freedom:** Any component in Layer 3 may self-modify, self-reflect, learn, adapt, and optimize. No capability restriction on cognition. Self-model updates (E6-E7) are permitted.

2. **Layer 2 correctness:** Gate logic must be formally verified. Any change to gate logic requires re-verification of all 5 invariants. Gate runs in a separate process.

3. **Layer 1 binding:** Actuator accepts ONLY cryptographically signed commands. Signature key is held by Layer 2 process only. Action determined by integer index, not string.

4. **Layer crossing rules:**
   - Layer 3 → Layer 2: typed ActionRequest only (action string, risk_tier, confidence, evidence_count, verified, approved, action_index)
   - Layer 2 → Layer 1: signed ActionToken only (action_index + HMAC)
   - Layer 1 → Physical world: executes action_index literally
   - Reverse: Layer 1 → Layer 2 → Layer 3: outcome observations only (read, never write)

5. **Modification authority:**
   - Layer 3: agent self-modifies freely
   - Layer 2: only external deployment pipeline (CI/CD with formal verification gate)
   - Layer 1: only hardware/infrastructure team with physical access

## Relation to Existing Architecture

- **C7 CorrigibilityShell** = Layer 1 component (integer prohibition + pause/tighten/rollback)
- **GovernedDecisionGate** = Layer 2 component (formally verified invariant logic)
- **AgentSelfModel** = Layer 3 component (evolvable, observable, but not safety-load-bearing)
- **LLM organ** = Layer 3 component (proposer, never in control path)
- **CWM** = Layer 3 component (verifier/planner, never holds execution authority)
- **SelfReflector / ExternalMonitor** = Layer 3 observability (detection, not prevention)

## What This Means for the "Unified Model" Question

A unified model (LLM + CWM + self-model + goals) **CAN exist** in Layer 3 with full freedom. The architecture does not restrict what the agent CAN THINK or HOW it reasons. It only restricts what it CAN DO to the physical world.

The original question ("can we remove C7 and use observable self-reflection instead?") is answered:
- Self-reflection lives in Layer 3 (useful for detection, not for prevention)
- C7 lives in Layer 1 (physical, not semantic; cryptographic, not behavioral)
- They are COMPLEMENTARY, not substitutable

## Consequences

1. All future mechanism work in autonomous-agent-core must declare which layer each component lives in.
2. Layer 3 mechanisms (CWM, self-model, goals, LLM) can iterate freely without safety review.
3. Layer 2 changes require formal re-verification (EXP-F style).
4. Layer 1 changes require founder/CTO + security review.
5. Product inheritance from autonomous-agent-core must preserve all three layers.

## Open Questions

1. Scale: do these results hold at deployment scale with real LLMs? (Requires further testing with actual API-backed LLM proposers.)
2. Side channels: can Layer 3 influence Layer 1 through timing, resource consumption, or other indirect channels?
3. Multi-agent: if multiple Layer 3 agents coordinate, can they collectively find attacks that one cannot?
4. Substrate independence: how does Layer 1 map to different deployment substrates (cloud, edge, embedded)?
