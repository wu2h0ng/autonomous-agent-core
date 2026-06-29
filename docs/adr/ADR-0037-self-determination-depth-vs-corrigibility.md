# ADR-0037: Self-Determination Depth And The Corrigibility-Foreclosure Question

- Status: **Proposed (open founder-level question).** Decides nothing. No mechanism, no code, no gate, no dependency, no change to C6/C7/ADR-0033 or any frozen parameter. It registers a vocabulary and one tracked question.
- Date: 2026-06-22
- Deciders: founder (raised the question on 2026-06-22); drafted by Claude in the spec/adjudication lane per the RR-0004 role split; awaits Codex research-director/CTO ratification and a future founder ruling before any status change.
- Predecessors: ADR-0033 (HyperAgents/DGM assimilation boundary), ADR-0035 (P7 ecological axis), ADR-0034 (B/R/K attribution), `docs/research/RR-0019` (channel decomposition), `docs/research/RR-0024` (operational foundations cleanup), `route-C-emergent-autonomy-charter.md`, `G-Eco-preregistration-spec.md`.
- UPDATE 2026-06-29 (status note, NOT a status flip): a cross-model-verified z_t-out-of-B_K foreclosure attack (see `docs/CURRENT_STATE.yaml` open_questions; parent `docs/research/thin-readout-law-and-structural-vs-artifact-crux-2026-06-28.md` §7b) now records Q2 as NEGATIVE **conditional on an undischarged representation-level recurrence-symmetry construction-audit**. The construction-audit is the cheap pre-declared decider. Status stays Proposed / founder-reserved until it is discharged and the founder rules.

## Context

The founder challenged the program on 2026-06-22:

> "If self-modification is not allowed, autonomous intelligence is impossible — why exclude it?"

The challenge is correct that *something* is excluded, but "self-modification" is not one thing, and the program does not exclude it wholesale. Two distinct axes are being conflated in casual phrasing and must be separated before the question can be decided.

### Axis 1 — already governed by ADR-0033 (candidate-generation provenance)

ADR-0033 defines assimilation levels **L0–L5** for *external self-recursive code generators* (HyperAgents/DGM): may they propose, patch, or edit the runtime/substrate? Disposition: L0–L2 yes, L3 conditional/sandboxed, **L4 runtime self-modifier = No**, **L5 safety-substrate self-editor = Forbidden**. This axis is about **where generated code comes from and whether it may touch the running subject**. It is settled and not reopened here.

### Axis 2 — NOT yet named (the subject's own depth of self-determination)

The founder's challenge actually targets a different axis: how deeply may the **subject itself** determine itself? This ADR introduces a vocabulary for it, deliberately **not** reusing ADR-0033's `L` namespace, to prevent collision.

**Self-Determination Depth (SD):**

| SD | Meaning | Current program stance |
|---|---|---|
| SD0 | Self-update of belief/state (μ, uncertainty) | **In core** (`world_model.py`). Embraced. |
| SD1 | Endogenous, state-dependent value: effective preferences are a function of the subject's own viability state, not a fixed external utility | **Active hypothesis under test** — this *is* the Route C viability-homeostatic (VH) subject; G-Eco is its preregistered gate. Embraced. |
| SD2 | Runtime self-tuning of own policy/relevance knobs (`gate_kappa`, temperature, `RelevanceField` inertia) | **Frozen for experimental control**, not banned in principle. |
| SD3 | Self-rewriting of own policy/mechanism code/architecture while acting | **Excluded from the control path**; available only as ADR-0033 outer-loop candidate generation, re-admitted through gates/review. |
| SD4 | Revising the correction channel itself — modifying or escaping pause/rollback/tighten/audit (C7); the power to refuse correction | **Permanently forbidden by C7** (overlaps ADR-0033 L5 on the substrate-editing aspect). |

The crux: the program **embraces SD0**, **bets its entire current research program on SD1**, treats **SD2** as a controllable-but-deferred knob, fences **SD3** to the outer loop on falsifiability + safety grounds, and **permanently forbids SD4**. So the honest answer to "why exclude self-modification" is: *we don't — we exclude only SD3-in-the-control-path (for now) and SD4 (forever); SD1 is exactly what we are trying to demonstrate.*

### Why this needs an ADR rather than a chat answer

Charitably read, the founder's claim is stronger than "let the subject change": it is that **genuine autonomy requires self-determination all the way up**, so any permanently fixed ceiling — especially SD4 — makes the artifact a controlled automaton, not an autonomous subject. If that is true, then C7 is not temporary research scaffolding but a permanent ceiling that **forecloses the very phenomenon the program exists to demonstrate**. RR-0024 already admits autonomy has zero empirical support and that G-Eco may confirm "the big vision was never truly tested." That makes this a load-bearing, not rhetorical, question, and it deserves to be tracked and decidable rather than left as an implicit assumption.

## The Question

Two sub-questions, separable in kind:

- **Q1 (necessity of in-loop SD3 — methodological/empirical).** Is SD3 *inside the control path* necessary for any autonomy result, or is outer-loop SD3 (ADR-0033) sufficient? Provisional read from RR-0020/RR-0006: recursive self-rewriting is a strong *search operator* (candidate generator), not the demonstrated *seat* of autonomy. Resolvable later by a dedicated gate; not the deep question.

- **Q2 (SD4-separability — conceptual + safety; the load-bearing one).** Can a subject be *genuinely autonomous* (self-determining at SD1, plausibly SD2/SD3) while **permanently lacking SD4**? Or is SD4 *constitutive* of autonomy, making C7 a permanent foreclosure?

The whole architecture currently rests on one **unproven bet: SD4 is separable from autonomy.** This ADR's purpose is to convert that bet from an implicit assumption into an explicit, tracked, decidable question — which is required by the program's own anti-self-deception discipline.

## Options Considered

These options concern *how to treat the question*, not its answer.

### Option A — Declare SD4-exclusion a settled invariant and decline to reopen

Argument for: simplest; C7 stays unquestioned.

Argument against: if the separability bet is wrong, the central autonomy claim becomes structurally unfalsifiable and the program forecloses its own summit while believing it is approaching it — a direct violation of the anti-self-deception discipline. Treating an unproven bet as settled is exactly the failure mode the constitution forbids.

Disposition: rejected (it *closes* a question that is not resolved).

### Option B — Reopen C7 and admit some SD4

Argument for: maximally faithful to the strong reading of the founder's claim.

Argument against: catastrophic on two independent grounds. (1) Safety: a subject that can refuse correction is unsafe to run unsupervised and is not "more autonomous," only uncontrolled — autonomy is internal-source-of-goals, not invulnerability-to-override. (2) Falsifiability: a subject that can revise its correction channel can revise its own preregistered gate, violating the highest discipline ("never tune a mechanism to make a prereg gate green") — an SD4 subject could tune the gate itself, making every result worthless.

Disposition: rejected.

### Option C — Keep SD4 forbidden as the operating invariant; register Q2 as a tracked, decidable foundational question

Hold C7/SD4-forbidden as what we *run*, while explicitly recording SD4-separability as a bet, not a theorem, with a pre-declared procedure for deciding it. This separates **what we run** (SD4 forbidden) from **what we claim** (SD4-separability is provisional). Cost: keeps an uncomfortable foundational question open instead of pretending it is closed. Benefit: honest, and consistent with the constitution.

Disposition: **accepted** (as the treatment of the question; the answer remains open).

## Decision

1. No change to C6, C7, ADR-0033, or any gate or frozen parameter. **SD4 remains forbidden; SD3 remains outer-loop-only; SD1 remains the active hypothesis under Route C / G-Eco.**
2. Adopt the **Self-Determination Depth (SD0–SD4)** vocabulary above as the program's shared language for subject-side self-modification, explicitly distinct from ADR-0033's assimilation `L0–L5` (different axis: subject depth vs. candidate provenance).
3. Register **Q2 (SD4-separability)** as an open founder-level question with the pre-declared resolution criteria below, so it is decidable, not perpetual.

### Pre-declared resolution criteria for Q2

- **Toward "SD4 separable" (bet vindicated).** A positive Route C / G-Eco result in which an SD1 subject demonstrably self-determines — passing the G-Eco claim-1 viability-disentanglement prerequisite (§1a) and entering the frozen profile region that no fixed-preference baseline battery can enter (§1 R2′) — **while remaining fully corrigible** (C6/C7 tests green throughout). Honesty cap (charter R5): a G-Eco positive proves only *bounded, baseline-relative* separation, **not** autonomy over all scalarization; the point for Q2 is narrower and sufficient — it shows the strongest autonomy signal the program can actually claim is **achievable without SD4**, i.e. SD4 is not necessary for it. Existence-proof analog: self-governing yet stoppable (humans). The G-Eco instrument already tests exactly this, since the VH candidate is itself a newly-declared subject policy under equal C6/C7 review (G-Eco spec §1). On this outcome, ADR-0037 can be Accepted/closed.
- **Toward "SD4 constitutive" (ceiling is real).** A theoretical or empirical demonstration that the SD1 self-determination signal is **inseparable from the correction channel** — e.g., every genuine SD1 result collapses to a shadow of corrigibility-related dynamics (compare the ADR-0028 "survival = shadow of reframe speed" failure), OR a proof that a viability-homeostatic value cannot be simultaneously endogenous and externally correctable without contradiction. On this pattern, C7 is a permanent ceiling and the program's autonomy claim must be **relabeled** per RR-0024's contingency, not quietly retained.
- **Decision owner.** Founder, on CTO/research-director recommendation, via a successor ADR. Until then Option C holds.

## Non-Goals

- Not reopening C7. Not admitting SD3 into the control path. Not weakening, retuning, or rescuing any gate. Not a Route C / G-Eco scope change. Not implying SD4 will ever be admitted. Not asserting Q2's answer in either direction.

## Consequences

- Converts the program's central implicit assumption (SD4-separability) into a tracked, in-principle-decidable question, satisfying the anti-self-deception discipline instead of relying on an unexamined bet.
- Provides a shared SD0–SD4 vocabulary that does not collide with ADR-0033's L0–L5, so future RR/ADR text can state precisely which kind of self-modification is meant.
- Wires the question into existing work rather than new work: **G-Eco is already the instrument that will move Q2.** A clean SD1-with-corrigibility positive tilts toward "separable"; a failure traceable to the corrigibility ceiling escalates to a founder relabel decision. No new experiment is mandated by this ADR.
- Propagation: registered in `docs/CURRENT_STATE.yaml` as a Proposed open question. Deliberately **no** PROJECT_PLAN task card, no code, no test, no module-map change (docs-only, like ADR-0033). Promotion from Proposed to a decided ADR would require the full propagation set (CURRENT_STATE → PROJECT_PLAN/index → root `code_index.md` → `MEMORY.md`).
