# CWM-LEARN-5e preregistration — data-blind LLM knowledge pruning + CWM invariance verification

- **Date:** 2026-07-04 · **Design:** `CWM-LEARN-5E.DESIGN-2026-07-04.md` · **Program:** RR-0041/RR-0042
  (founder tier-1 bullseye). **Author/builder:** Claude; **Adjudicator:** founder.
- **Pilot (pre-freeze, seeds 100–102 disjoint):** degradation regime CONFIRMED at n_raw=60 — exhaustive
  cross2 (1,830 coords) median normalized score **0.564** (seed 100 `found=False`; kept ≤2 coords elsewhere)
  vs oracle 0.90–0.95 → freeze at 60 (`cwm_learn_5e_pilot.result.json`).

## Frozen artifacts (rechecked at run; drift ⇒ INVALID)

| artifact | sha256[:16] |
|---|---|
| `experiments/synthetic_scm_highdim.py` (with cond-B override) | `405224156d1caa98` |
| `experiments/cwm_learn_5e.py` | `4b02e5a9fe6c2d41` |
| `experiments/hd5e_schema.json` (names + cond-A/B maps) | `49e296bf68036569` |
| `experiments/hd5e_prompt.txt` (data-blind proposer prompt) | `2994dea595c1a50a` |
| `experiments/hd5e_proposals.json` (5 proposals VERBATIM) | `b0b106c04c0419dd` (file bytes) |

> Hash-record correction (disclosed): the original freeze recorded the CANONICAL-JSON hash (`87ced634…`,
> sort_keys serialization) instead of the file-bytes hash; the run-time drift guard checks file bytes and
> correctly halted the scored run. Content verified UNCHANGED (canonical hash still `87ced6345e2932d8`);
> only the recorded digest form is corrected. Guard behavior = working as designed.

## Leakage + integrity disclosures (frozen)

- Prompt = pure function of the schema (names alphabetical — no position leak); proposers saw NO data, no
  env structure, no seeds, no true pairs, not this session. m=5 independent calls, **0 re-rolls**, all taken
  verbatim. **Proposer model = Claude subagents — same family as the builder, disclosed**; the knowledge-vs-
  luck question is carried by the condition-B control and the random-k arm, not by proposer identity.
- Condition-B true structure (arbitrary distractor pairs `[[20,47],[26,53],[32,58],[38,51]]`) was frozen in
  the schema BEFORE any proposal call.
- Observed post-freeze (recorded, no design change): all 4 cond-A true pairs appear in **5/5** proposals;
  union cap 30 by frequency ranking.

## Arms + decision rule (frozen; author recommends, founder casts)

Identical verifier everywhere (`InvariantStructureFilter`): a=LLM-union(≤30 pairs) / b=exhaustive cross2 /
c=random-k (20 draws/seed, median) / d=oracle / e=screening top-k by min-env |corr(x_i·x_j, y)|. Seeds 0–9
(disjoint from pilot). Normalized s=(AUC−0.5)/(oracle−0.5), `found=False`→0.
**MET** iff median s_a ≥ 0.8 AND a>b ≥9/10 AND a>random-median ≥9/10 AND **condition-B collapse** (median
s_a_B within 0.10 of s_rand_B). Tiers: **MET-strong** a>e ≥8/10; **MET-weak** |s_a−s_e| ≤ 0.05 (data-free
knowledge matches data-using screening — reported as such, never conflated). **NULL** if enumeration
suffices / prior=luck / screening dominates (park knowledge route). **INVALID** on condition-B anomaly
(a wins where names carry no information) or hash/digest drift.

## Frozen honest prediction

**MET likely (~60–70%)** — union contains all 4 true pairs at top frequency, and the verifier at p≈90 is in
its validated regime while exhaustive is confirmed degraded. **Most likely tier: MET-weak** — the screening
baseline probably also finds the true pairs (their products carry strong invariant correlation), in which
case the honest headline is "data-free knowledge ≈ cheap data-screening at this scale", NOT "LLM beats data".
NULL path: verifier fails to keep the true pairs even from the pruned set on some seeds. Condition-B collapse
expected (proposals contain none of the arbitrary pairs). I will not tune caps/thresholds/params post-run.

## Honest scope

MET proves: on knowledge-congruent semi-synthetic structure, a data-blind knowledge proposer + our validated
verifier recovers causal structure where enumeration degrades. It does NOT prove real-world validity, general
LLM causal discovery, or superiority over data-using screening unless MET-strong. Proposer stays strictly
outside the control path. Condition-B measures how the prior misleads on incongruent domains (deliverable).

## Result

_(appended by the scored run)_

## Result (scored 2026-07-04, digests no-drift): **MET-weak — as frozen-predicted tier**

median s: **llm 1.000** / screening 1.000 / exhaustive 0.446 / random 0.319. LLM > exhaustive 10/10,
> random 10/10, > screening 2/10 → |s_a−s_e| = 0 ≤ 0.05 ⇒ **MET-weak**. Condition-B collapse clean
(s_llm_B median 0.000 = random level) — the knowledge claim is knowledge, not leakage/luck.

Honest reading: the proposer/verifier pipeline REACHES THE ORACLE CEILING where enumeration degrades
(the p≫n value window is real and fully captured), but the cheapest data-using screener reaches it too —
at this scale, data-free knowledge ≈ cheap screening. The knowledge channel's UNIQUE region (zero-shot
pre-data pruning; non-enumerable functional forms) is where 5e-2 must be set, per RR-0044 §4.4.
RR-0044 ledger: this bet HIT (predicted ~85% MET, s_llm≥0.8, s_exh≤0.65).
