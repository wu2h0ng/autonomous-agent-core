# Construction-Audit Discharge + Cross-Model Reversal — SD4/ADR-0037 Q2 REOPENED

> Date: 2026-06-29
> Disposition: **FOUNDER-CAST** (founder adopted Claude's recommendation, 2026-06-29). Claude did NOT self-cast the verdict; it produced the evidence (single-model audit), routed cross-model adjudication, and recommended. The founder ruled.
> Supersedes the 2026-06-29 "Q2 = NEGATIVE conditional on the construction-audit" status note (which this work overturns).

## What was tested
The z_t-out-of-B_K foreclosure (thin-readout-law §7b) was recorded as ANSWERED NO / FORECLOSURE_SOUND but **proven-CONDITIONAL** on a single remaining gap: a **representation-level recurrence-symmetry construction-audit** (same encoding + same admissible-recurrence family + symmetrized cost metric, not merely K/M/compute). This discharges that audit.

## Step 1 — single-model adversarial construction-audit (workflow wu4y95d48)
6 attack vectors, each a breaker trying to construct a z_t outside closure(B_K) with non-vanishing regret under representation-level symmetry, each adjudicated by 2 independent skeptics. **Result: 0 survivors.** But every break rested on one of **3 now-explicit load-bearing axioms**:
- **AXIOM 1 (most contestable):** the symmetrized cost metric must CHARGE encoder/representation acquisition — treat a fixed/pretrained env-specific encoder as accumulated privileged side-information, not a free architectural prior. (Killed the encoding-asymmetry construction.)
- **AXIOM 2:** the baseline's admissible-recurrence family must include arbitrary bounded Boolean latches (not just geometric kernels). (Killed the undiscounted-long-range construction.)
- **AXIOM 3 / nearest-miss:** C6 read as forbidding env-side coupling to private state except via the observable action (DPI). (Killed private-randomness; skeptics SPLIT — one could not break it.)
Single-model conclusion: foreclosure robust **conditional on these 3 axioms**.

## Step 2 — cross-model adjudication (Kimi, the established 3rd party for this line; caught 3 prior same-model self-deceptions)
**Verdict: `SKEPTIC_OVERCLAIMED` — foreclosure overclaimed; the autonomy door REOPENS.** (The 4th cross-model save on this line.)
- **AXIOM 1 judged ILLEGITIMATE:** C6 forbids runtime oracles + beliefs-in-control-path, NOT fixed feature maps / learned priors. Charging encoder acquisition conflates runtime fairness with developmental identity.
- **Killer point (holds even if AXIOM 1 is kept):** requiring the baseline to carry the identical trained parameters collapses foreclosure to "an agent cannot outperform an identical copy of itself" — true but **vacuous**, saying nothing about autonomy.
- **Surviving construction:** `z_t = φ_S(x_t)`, a fixed pretrained nonlinear encoder (parity / random projection over a secret subset S), not online-identifiable within the shared run budget, hence outside closure(B_K) with non-vanishing paid regret — and a deterministic function of the current observation, **not a C6 oracle**.
- AXIOM 2, 3 judged sound; private-randomness breaks (DPI). Foreclosure depends on AXIOM 1, which overreaches.

## The irreducible crux (why no further adjudication settles it)
The single-model/cross-model split is NOT a logic error on either side. It reduces to a **quantifier-order / no-free-lunch modeling choice** the audit cannot decide for itself:
- **"∀ environment ∃ organ-with-useful-S"** (transfer / pretrained-representation framing) → S is a free prior → **door OPEN**.
- **"∀ S, random environment"** → a random S is a.s. useless; usefulness ⇒ S correlated with this env's reward ⇒ env-specific privileged information → **door CLOSED**.
This is exactly why ADR-0037 §8 reserves the disposition to the founder: it is a research-question choice, not a logical fact.

## FOUNDER-CAST (2026-06-29) — adopting Claude's recommendation
1. **The strong claim "autonomy via an enriched internal state is FORECLOSED under C6" does NOT survive cross-model review** and is **WITHDRAWN**. SD4/ADR-0037 Q2's "NEGATIVE answer" is **CONTESTED, not established** (it is false under standard prior-fairness, or vacuous under no-free-prior).
2. **REOPEN the enrich-S route** under the standard prior-fairness reading (a fixed/pretrained representation is a legitimate free prior; the bet is whether such a representation yields an irreducible control signal a corrigible baseline cannot match).
3. **Reopening falsifier (to preregister):** the XOR-at-state-selected-lag / universal-hash `z_t = φ_S(x_t)` environment — now run to test **reopening** (does the fixed-encoder advantage survive when the prior-fairness convention is pinned and the baseline gets fair *online* acquisition?), the inverse of its earlier foreclosure framing. Freeze the prior-fairness convention BEFORE running.
4. **Caveat preserved:** the reopening is itself contingent on the pinned prior-fairness convention. A formal proof/disproof of the closure-completeness lemma, or a further cross-model pass, could move it again. This is a reopened research question, **not** a positive claim that autonomy works.

## Provenance
- Single-model audit: workflow `wu4y95d48` (0/6 survivors; 3 axioms).
- Cross-model: Kimi session `session_ed3b17a0-085d-4477-81fb-491755a7022e` (`SKEPTIC_OVERCLAIMED`).
- Upstream: `docs/research/thin-readout-law-and-structural-vs-artifact-crux-2026-06-28.md` (parent), ADR-0037.
