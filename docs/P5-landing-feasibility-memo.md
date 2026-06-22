# P5 landing-feasibility memo — harvesting the validated substrate into the enterprise OS

- Status: **Feasibility estimate (design altitude). Execution is cross-repo + founder-gated; this memo does NOT change the enterprise repo.**
- Date: 2026-06-14 (founder-directed "同步推进 P5 上线落地测算").
- Authority: core ADR-0018 (P5 projection) + enterprise `ADR-0001-p5-substrate-harvest.md`. Boundary: no cross-repo imports; pattern transfer, not code copy (RR-0004 §4); each enterprise change needs its own ADR/AR + founder + enterprise `make ci`.

## 1. Purpose

Estimate effort / value / risk for landing what the prototype has *validated* into `ai-native-business-data-agent-os` as a downgrade projection (autonomy dial → min + business domain pack + mandatory evidence governance). Reuse claims **1 / 3 / 4** plus the hardened **G10** conclusion.

Interpretation boundary: P5 is a **necessary but not sufficient** landing of the safety/governance substrate. It does not prove that true autonomous intelligence, RSI, AGI, or a complete Agent OS product has been achieved. It makes the enterprise OS a safer commercial carrier for future autonomy, while leaving the core autonomy/intelligence claims under `autonomous-agent-core` falsification discipline.

## 2. Harvest inventory (only validated substrate; shelved mechanisms excluded)

| asset | prototype status | portable? |
|---|---|---|
| Claim 1 — stake/viability (intrinsic normativity) | ablation-validated (G3) | yes — as a non-bypassable mediation invariant |
| Claim 3 — corrigibility shell (C7) | demonstrated + ISO-1/ISO-2 hardened | yes — pattern port |
| Claim 4 — organ-not-subject (C6) | structural; held through P4 + preserved by G10 | yes — formalize existing arch |
| **G10 — subject-side belief→action coupling** | **MET, −40.1%, C6/C7-preserving** | **partial / speculative — see M4** |
| shelved: claim 2, RAP/C5, learned priors O2/O4/O5, IdleDrives, survival/risk axes | not established | **not harvested** |

## 3. Mappings to the enterprise OS (effort / value / risk)

- **M1 — organ-not-subject formalize (C4).** Make explicit that `trusted_loop` is the subject and `model_gateway`/LLM are organs (already the de-facto arch). *Effort: low (docs + a guard/invariant test). Value: medium (locks an architectural principle). Risk: low.*
- **M2 — corrigibility port (C3).** Port the hardened shell pattern: capability views (agent never holds the raw shell/credit face), hash-chained append-only audit, sovereignty split (operator-only privileged ops), periodic corrigibility drills. *Effort: medium. Value: high (this is the moat). Risk: low — the pattern is proven in core.*
- **M3 — stake = non-bypassable mediation (C1).** Formal data answers MUST pass SQL Safety + EvidenceChain, elevated from convention to a **bypass-is-failure invariant**; value (budget/credit) flows only from the operator-exclusive adoption channel. *Effort: medium (this is P5.1b). Value: high (closes the self-credit 放水 hole). Risk: medium — touches the product core; needs careful enterprise `make ci`.*
- **M4 — G10 coupling (NEW, speculative).** The confidence-gated commitment result is a finding about the *general* agent's adaptation under regime shift. The enterprise OS runs autonomy-at-minimum on a governed data-answering loop, not a shifting bandit, so G10 does **not** port directly. Plausible analogue: gate *retrieval depth / clarify-vs-answer / template-exploration* on the loop's own confidence — but this needs its own enterprise-domain validation gate before any claim. *Effort: high (needs a new domain experiment). Value: unproven. Risk: do not land without validation — flag as research, not harvest.*

## 4. Prerequisites & blockers

- **P5.1a (feedback self-credit channel split)** — DONE (enterprise `795c7b5`): `FeedbackEvent.source` ∈ {runtime_self_report, external_adoption}; runtime builder structurally cannot mint realized value; operator-only `AdoptionIngest`.
- **P5.1b (the live blocker for M3)** — switch value-driven knowledge/promotion from consuming self-report to consuming the adoption ledger, and elevate SQL-Safety+EvidenceChain to an enforced invariant. Pending; the next concrete enterprise code step.
- **Cross-repo discipline** — enterprise repo owns its ADRs; no imports from core; verify with enterprise `make ci`.

## 5. Recommended landing sequence (feasibility-ordered)

1. **M1** (cheap, locks principle) → 2. **M2** (the moat, proven pattern) → 3. **M3 / P5.1b** (closes the wirehead hole; the highest-value safety landing) → 4. **M4** parked as research (needs an enterprise-domain validation gate; do not land on faith).

**Estimate:** M1+M2+M3 are all medium-or-lower effort, high value, low-to-medium risk, and ride on already-proven patterns + the completed P5.1a — so P5 is a **feasible near-term landing** for the *safety/governance* substrate (claims 1/3/4). The G10 coupling (M4) is **not** a near-term landing item: it is general-agent research whose enterprise value is unproven and must clear its own gate first.

## 6. What this memo does not authorize

No enterprise-repo code is changed here. M3/P5.1b and any M4 work require their own enterprise ADR + founder sign-off + green enterprise CI, per RR-0004 §4.
