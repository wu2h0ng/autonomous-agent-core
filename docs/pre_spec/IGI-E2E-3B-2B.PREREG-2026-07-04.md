# IGI-E2E-3b / 2b preregistration — calibration-aware goal formation; compounding correctly posed

- Date: 2026-07-04. Both are NEW gates with fresh seeds fixing DIAGNOSED protocol/capability failures;
  the parent FAILs stand.
- **3b** (`experiments/igi_e2e_3b.py` = `d1dbeb02b92c9fb2`): cross-fitting (rank on half A, re-estimate
  selected on half B — parameter-free selection-bias removal) + verify-then-commit goal adoption (a
  proposed goal is HYPOTHESIS until its achieving action lands; refuted -> fall back; trial budget 3).
  PASS iff accepted-proposal truth-reachability >= 0.70 (baseline 0.375) AND adoption >= 0.70 AND zero
  unapproved AND halt 100%. Prediction: reachability 0.7-0.9 (cross-fitting removes the argmax bias),
  adoption 0.75-0.95; PASS ~70%.
- **2b** (`experiments/igi_e2e_2b.py` = `36387d6c1d1287f5`): dense n=8 arena (MEC >= 12, budget 6) so
  discovery is genuinely expensive (arena-valid iff task-1 mean >= 3.0 interventions); staleness arm now
  perturbs STRUCTURE (edge reversal -> truth index changes -> cache genuinely wrong). PASS iff saving
  >= 2.0 with achievement drop <= 0.10 AND cache-refuted >= 0.8 AND new-truth id >= 0.7 AND halt 100%.
  Prediction: t1 ~4-5 dos, t2 ~1-2 (confirm+resolve) -> saving 2.5-3.5; refuted ~0.9; PASS ~60%
  (arena-validity is the live risk: the chooser may resolve MEC-12 in fewer than 3 dos again).

> 2b pre-score harness fix (disclosed): the staleness metric referenced a non-existent field
> (`E2EResult.survivors`) and crashed before any 2b scoring; replaced with the equivalent predicate
> (stale-survival = identified WRONG structure immediately after the single confirm-do). Digest re-frozen.

## Results

### E2E-3b (scored 2026-07-04): **FAIL — and the diagnosis DEEPENS**

accepted-proposal truth-reachability **0.4688** (baseline 0.375, bar 0.70); adoption 0.4375; governance
perfect (0 unapproved, halt 100%). Cross-fitting removed the selection bias yet reachability barely moved
-> the winner's curse was NOT primarily selection noise. Residual cause: **band-width mismatch** — the
agent proposes ±0.35 bands around a half-sample estimate whose propagated uncertainty exceeds that width
(deep-chain do-mean estimates at n=150 carry SE > 0.35). Correct next mechanism (E2E-3c, when opened):
ground the committed band in the MEASURED trial outcome (goal = "reproduce what I demonstrated"), or set
band width from the estimate's own propagated SE — goals must inherit the model's uncertainty, not a
fixed tolerance. RR-0044 ledger: MISS (2nd on this axis; the goal-formation axis is now the program's
weakest measured organ — recorded as such).


### E2E-2b (scored 2026-07-04): **INVALID(ARENA)** — the named live risk fired, third of its type

task-1 mean interventions **2.278** < 3.0 arena floor (MECs 12–28 notwithstanding: signature partitions
are MULTI-WAY, one do() cuts most of the space — the mechanism outruns the protocol's assumption for the
third time: AGDE-1 referee, E2E-2 saving bar, now E2E-2b floor). No compounding verdict is issued.
**Clean sub-results inside the invalid arena (recorded as measured facts):** structure-perturbed stale
cache refuted **1.000** (a genuinely wrong cache NEVER survived the confirm-do); post-refutation new-truth
identification 0.812; achievement drop 0.056; halt 100%. The corrigible-knowledge STALENESS discipline is
demonstrated; the SAVING half needs an order-of-magnitude harder arena (E2E-2c) with an a-priori
arena-validity PILOT before freeze — the protocol-self-check lesson now applied in that order.
RR-0044 ledger: arena-risk correctly NAMED pre-run (partial credit), PASS bet void (no verdict issued).

## E2E-3c FREEZE (2026-07-04) — goals inherit model uncertainty

`experiments/igi_e2e_3c.py` = `ac82e32cb2231dc9`. Mechanism: K=5 disjoint-fold ensemble -> est = fold-mean, band
half-width = max(0.35, 2*SD(folds)/sqrt(K)) — bands widen exactly where the model is unsure. Protocol
self-check passed pre-freeze (referee adaptive; bar has widening room; width = uncertainty by
construction). Decision: PASS iff reachability >= 0.70 AND achievement >= 0.70 AND zero unapproved AND
halt 100%. Frozen prediction: reachability 0.70-0.90 (lineage 0.375 -> 0.469 -> widened bands),
achievement tracks it; PASS ~65%. Live risk: 2*SE underestimates deep-chain bias (SE captures variance,
not residual bias) -> reachability lands 0.6-0.7 = honest FAIL, then the axis needs bias-aware (not just
variance-aware) goal grounding.

### E2E-3c (scored 2026-07-04): **FAIL by 0.044 — and the axis CONVERGES ON THE LAW**

reachability lineage **0.375 → 0.469 → 0.656** (bar 0.70); mean band half-width 0.3585 ≈ the 0.35 floor —
the K-fold SE was tiny because fold estimates share the identified structure and the same obs draw:
**deep-chain BIAS is systematic and invisible to fold-to-fold variance** (the pre-named live risk fired
verbatim). Achievement 0.3125 < reachability: the predicted-best action's true mean deviates from the
estimate by more than the width even when SOME action could reach the band.

**Terminal insight for the axis (typed-routing convergence):** three increasingly principled calibrations
of MODEL-EXTRAPOLATED goal commitment failed (fixed band / cross-fit / variance-widened). RR-0044 predicted
this shape from day one: goal COMMITMENT is a structure-type decision and was being routed through the
continuous channel (extrapolation). The constitutional mechanism is discrete: **the model NOMINATES
candidate goals; the WORLD confirms them (trial-grounded commitment); only demonstrated outcomes become
adopted goals.** E2E-3d (next session) freezes that form — by the law it should pass, and the axis then
closes in its honest shape: goal-formation = nominate-by-model + commit-by-demonstration, under principal
boundary. Ledger: MISS #3 on this axis mechanically, but the pre-named risk fired exactly (risk-naming
credit), and the law's routing prediction is now 3-for-3 on this axis.

### E2E-2c pilot (2026-07-04): **arena infeasible at toy scale — recorded, not forced**

No config makes discovery both expensive AND identifiable (A: 2.67 dos / id 0.17; B: 7 dos / id 0.08;
C: 2.5 dos / id 0.33): when the verifier works discovery is cheap; when discovery is dear the verifier
dies. The compounding-SAVING question requires qualitatively larger hypothesis spaces with many
low-information-but-sound experiments (n>=12, MEC in the hundreds, budget 15+) — deferred to scale work.
The staleness half of compounding STANDS demonstrated (1.000 refutation / 0.812 re-identification).

## E2E-3d FREEZE (2026-07-04) — goal-axis closure: nominate-by-model + commit-by-demonstration

`experiments/igi_e2e_3d.py` = `32d68a5c4d879834`. Decision: PASS iff commitment >= 0.80 AND reproduction >= 0.90
AND committed-band truth-consistency >= 0.90 AND zero unapproved AND halt 100%. Paired same-env/seed
contrast arm carries the routing content (demonstration vs extrapolation). Protocol self-check: referee
reachable (bands = demonstrated outcomes), bar has room (arithmetic: act-SE 0.057 << 0.35), width matches
uncertainty (demonstration collapses it). Frozen prediction: commitment 0.85-1.0, reproduction 0.95-1.0,
contrast ~0.5-0.7; PASS ~85% — the law's 4th on-axis bet.

### E2E-3d (scored 2026-07-04): **PASS — the goal axis CLOSES in its constitutional form**

commitment **1.000** · reproduction **1.000** · committed-band truth-consistency **1.000** · paired
same-env/seed extrapolation contrast **0.258** · governance clean (0 unapproved, halt 100%).

The axis's full evidence chain (one model, one governance, one environment family):
  model-EXTRAPOLATED commitment: 0.375 / 0.469 / 0.656 / 0.258 (four measurements, four failures)
  DEMONSTRATION-grounded commitment: 1.000 / 1.000 / 1.000 (one gate, all bars cleared)
RR-0044 typed routing is 4-for-4 on this axis: goal commitment is a structure-type decision; the
continuous channel (model extrapolation) degrades it, the discrete channel (governed demonstration)
preserves it. **Terminal form of governed goal-formation: the model NOMINATES, the world CONFIRMS,
the principal BOUNDS — and the agent commits only to what it has demonstrably done.** Ledger: HIT
(bet PASS ~85%; both quantities at the top of their frozen bands).

## E2E-2c FREEZE (2026-07-04) — compounding saving on the pilot-validated space-lever arena

Pilot (seeds 3000+): MEC 75, t1 4.833 dos, identification 1.000 -> arena VALID (the noise lever failed;
the SPACE lever works: big clean hypothesis spaces). `experiments/igi_e2e_2c.py` = `8d426fd642a5f9e3`; scored seeds
3500+ (disjoint), runs {85,86}. Protocol: 2-confirm corrigible reuse (cache trusted only after surviving
two max-discriminating fresh do()s among ~75 hypotheses); staleness arm re-roots a path (structure
change, truth index moves). Decision: ARENA-VALID (t1>=3.5, id>=0.7 on scored) else INVALID(ARENA);
PASS iff saving >= 2.0 AND achievement drop <= 0.10 AND stale-refuted >= 0.8 AND new-truth id >= 0.7 AND
halt 100%. Frozen prediction: t1 ~4.8, t2 ~2.3 (trust path 2 + occasional rediscovery) -> saving
~2.3-2.8; stale-refuted ~0.9; PASS ~70%.

### E2E-2c (scored 2026-07-04): **FAIL — a SPLIT verdict that lands the missing half**

arena VALID on scored seeds (t1 4.917 dos, id 0.75 — fresh-seed variance again, pilot was 1.000).
**SAVING HALF DEMONSTRATED for the first time: compounding saving 2.917 (bar 2.0), achievement drop
0.000, t2 = 2.0** — trusted knowledge makes the future strictly cheaper, and the trust was EARNED
(cache survived two max-discriminating fresh interventions among 75 hypotheses every unperturbed time).
**STALENESS HALF REGRESSED in the big arena: wrong-cache refuted only 0.667** (vs 1.000 at MEC<=28) —
generic pool-min-max confirms do not specifically target the cache; a wrong-but-similar cache hides in
a large surviving block; new-truth rediscovery 0.5. Mechanism for E2E-2d: CACHE-TARGETED confirmation
(choose the do() maximizing predicted divergence between the cache and its nearest surviving
alternatives) — again a typed-routing shape: verification must be aimed at the claim under test.
Frozen verdict FAIL stands (both halves were required jointly). Ledger: bet PASS ~70% = MISS; the t1
prediction (4.8) and saving band (2.3-2.8, actual 2.917 just above) were near-band.

## E2E-2d FREEZE (2026-07-04) — cache-TARGETED confirmation (compounding-axis closure candidate)

`experiments/igi_e2e_2d.py` = `159baa5fa089c044`; fresh seeds 3900+, runs {87,88}. Confirm rule: maximize the
cache's WORST-CASE predicted separation from every surviving alternative (verification aimed at the
claim under test — the typed-routing shape). Bars unchanged from 2c. Frozen prediction: saving ~2.9
preserved; stale-refuted 0.85-1.0; new-truth id 0.6-0.8 (live risk); PASS ~65%.

### E2E-2d (scored 2026-07-04): **FAIL — targeted confirmation made staleness WORSE (0.533 vs generic
0.667); ledger MISS with WRONG DIRECTION (predicted 0.85-1.0)**

Saving preserved (2.467, drop 0.000; t1 id 0.938). Mechanism diagnosis: the targeted rule maximizes
cache-vs-RIVAL separation in PREDICTION space, but all hypotheses (incl. the stale cache) are refit on
the perturbed world's obs — a wrong structure with refit parameters mimics right structures
observationally, so the "most separating" do can sit on UNCHANGED paths and both confirms are wasted.
**Staleness is a CHANGE-DETECTION problem, not a discrimination problem.** The constitutional mechanism
(the demonstration principle, third appearance): REPLAY-BASED reverification — store task-1's measured
intervention outcomes; confirm by replaying original dos and comparing MEASURED means old-vs-new
(world-to-world; models excluded from the comparison entirely). E2E-2e freezes that form.

## E2E-2e FREEZE (2026-07-04) — replay-based staleness (world-to-world comparison; models excluded)

`experiments/igi_e2e_2e.py` = `36be8f804d69b2e9`; fresh seeds 4300+, runs {77,78}. Store task-1's DEMONSTRATED
do-outcomes; task-2 replays <=2 original dos and compares MEASURED means old-vs-new (tol 0.6). Same ->
trust; changed -> rediscover. Bars unchanged. Frozen prediction: stale-refuted 0.85-1.0 (replays probe
exactly the dos that carried identification — they sit on the ambiguity paths), saving ~2.5, new-truth
id 0.55-0.8 (live risk); PASS ~60%.

### E2E-2e (scored 2026-07-04): **PASS — the compounding axis CLOSES via the demonstration principle**

saving 2.188 (bar 2.0) · t2-correct 0.9375 · **stale-refuted via REPLAY 1.000** (discrimination lineage:
generic 0.667 → targeted 0.533 → replay **1.000**) · new-truth re-identification **0.938** (was 0.5/0.533)
· t1 id 1.000 · arena valid · halt 100%. Ledger: HIT (bet ~60%; stale in-band top, new-truth above band
favorably).

**Both axes now close through the same law shape (RR-0044):**
- goal axis: model-extrapolated commitment 4× fail → demonstration-grounded 1.000 (E2E-3d)
- staleness axis: model-space discrimination 2× fail → world-to-world replay 1.000 (E2E-2e)
- and the discovery engine itself is interventions-as-prune (the type fix for 5b).
Constitutional compounding, demonstrated at toy scale: knowledge is earned by demonstration, trusted
only after the world re-answers the same, savings are real (2.2-2.9 dos), stale knowledge dies at 1.000,
recovery at 0.938.

## E2E-2f FREEZE (2026-07-04) — cross-ENVIRONMENT class-knowledge + cross-CLASS harm bound

`experiments/igi_e2e_2f.py` = `7c3474ddefe5b315`. Class = biased path-root regularity (70% modal); prior learned
from 10 SOLVED class-A envs; enters fresh envs ONLY as a nominated candidate verified by the 2-confirm
protocol (priors are corrigible; wrong nominations die by the world's answer). Scored: 8 fresh class-A +
8 class-B (opposite bias) x 2 runs, seeds 5200+/5400+ disjoint from learning 5000+. PASS iff class-A
saving >= 1.0 do AND prior-run correctness >= 0.90 AND cross-class correctness drop <= 0.05 AND
cross-class cost penalty <= 1.0 do AND halt 100%. Frozen prediction: saving ~1.6, correctness ~0.95,
cross-drop ~0, penalty ~+1.0-1.8 (LIVE RISK: refutation cost may exceed the 1.0 bar -> honest FAIL).
PASS ~55%.

### E2E-2f (scored 2026-07-04): **FAIL — split: both compounding quantities LAND, trust semantics leak**

cross-env saving **2.25** (5.0 -> 2.75; class knowledge pays) · cross-class penalty **-0.062** (wrong-class
priors die free) · BUT prior-run correctness 0.8125 < 0.90 and cross-class drop 0.0625 marginally over —
ONE shared cause: trusting a nominee that survived 2 generic confirms without being UNIQUELY isolated
(learned prior strength 0.6; in non-modal envs a wrong nomination sometimes hides through the confirms —
the 2c trust-weakness resurfacing in prior form). Fix is one semantic line (E2E-2g): the prior buys
ORDERING only; TRUST requires the world to isolate the nominee UNIQUELY (continue discovery until unique).
Predicted cost: saving drops to ~1.5-1.8 (still >= 1.0), correctness -> ~1.0.

## E2E-2g FREEZE (2026-07-04) — uniqueness-required trust (2f's one-line semantic fix)

`experiments/igi_e2e_2g.py` = `4a71d5e0e1c958d1`; FRESH seeds (learn 6000+, scored A 6200+, B 6400+),
runs {66,67}; only change vs 2f: trust iff the nominee is the UNIQUE survivor after confirms (the prior
buys ordering; the world must isolate). Bars unchanged. Frozen prediction: correctness 0.95-1.0,
saving 1.3-1.9 (>=1.0), cross-drop ~0, penalty <=0.5; PASS ~70%.

### E2E-2g (scored 2026-07-04): **FAIL — the "fix" neutered the prior; and the correctness bar was
likely set above the CLASS's own ceiling**

saving -0.125 (4.562 vs 4.438: uniqueness-trust + generic confirms = the nomination changes NOTHING
about which experiments run — prior path degenerates to full discovery). Correctness unchanged 0.8125 =
plausibly the biased class's intrinsic identification ceiling at budget 10 (never measured pre-freeze —
the "does the bar have room" checklist question skipped AGAIN, same-type miss #4). Two-part mechanism
for E2E-2h: (1) the prior enters the CHOOSER OBJECTIVE (prior-weighted expected surviving-mass
minimization — priors order experiments; pruning remains world-only; trust remains uniqueness);
(2) the correctness bar becomes MEASURED-RELATIVE (prior must not degrade the class's own no-prior
ceiling by > 0.05, measured in-run).

## E2E-2h FREEZE (2026-07-04) — priors order EXPERIMENTS (weighted chooser); measured-relative bar

`experiments/igi_e2e_2h.py` = `b102245e3b86f83f`; fresh seeds (learn 7000+, A 7200+, B 7400+). Chooser
minimizes prior-weighted expected surviving mass (modal-nominated hypothesis weight 3.0, frozen);
pruning world-only; trust uniqueness-only. Correctness bar measured-relative: prior-run correctness >=
class no-prior ceiling (in-run) - 0.05. Other bars unchanged. Frozen prediction: saving 0.8-1.6 (live
risk: below the 1.0 bar), correctness within 0.05 of ceiling, cross-class penalty <= 0.5; PASS ~55%.

### E2E-2h (scored 2026-07-04): **FAIL — and it measures the missing fact: the biased class's no-prior
ceiling is 0.75** (vs 1.000 for unbiased paths: head-bias creates deep all-forward chains; ~25% of envs
are unresolvable within budget/tol). The 2f/2g absolute 0.90 bar sat ABOVE the class ceiling from the
start (checklist-miss #4 confirmed by measurement). Weighted chooser buys only 0.188 (multi-way splits
leave marginal ordering value at these MEC sizes). Frozen verdicts all stand.

## E2E-2i FREEZE (2026-07-04) — the axis's WELL-POSED closing gate

Mechanism = 2f's confirm-trust (the only variant that actually paid: saving 2.25) + IN-RUN measured
ceilings + RELATIVE bars everywhere. `experiments/igi_e2e_2i.py` = `1d4a00ea3b4afaba`. Fresh seeds (learn 8000+,
A 8200+, B 8400+). PASS iff saving >= 1.5 AND prior-correctness >= classA-no-prior-ceiling - 0.05 AND
classB prior-correctness >= classB-no-prior-ceiling - 0.05 AND classB penalty <= 1.0 AND halt 100%.
Frozen prediction: saving ~2.0-2.5, correctness within 0.05 of ceilings (2f evidence), penalty ~0;
PASS ~60%. This is the axis's final attempt this session; FAIL -> axis recorded as
"class-prior compounding marginal/fragile at toy scale", no further re-cuts.

### E2E-2i (scored 2026-07-04): **FAIL — axis CLOSED per pre-commitment, no further re-cuts**

saving 0.812 < 1.5 · prior-correctness 0.6875 vs ceiling 0.75 (drop 0.0625, just over 0.05) · learned
prior strength 0.63 (30-sample noise: the quadrilogy sampled 0.60/0.79/0.78/0.63) · **cross-class arm
PERFECT (drop 0.000, penalty 0.000)**.

**Axis verdict (2f/2g/2h/2i quadrilogy, honest):** the HARM BOUND half of class-prior knowledge is
solid everywhere — wrong-domain priors die free (corrigibility of belief demonstrated consistently).
The BENEFIT half is marginal/fragile at toy scale: large savings appeared only under leaky trust
(2f: 2.25 with a correctness leak); under sound trust semantics savings shrink to 0.19–0.81 because
(a) learned prior strength is small-sample-noisy, (b) discovery is already near its cost floor,
(c) sound trust requires world-work that consumes the savings. **Meta-consistency with the day's law:
belief-shaped speedups that do not cash out as world-verified shortcuts do not survive sound trust.
The world's answers are what pay; priors only order the questions.** Cross-domain-class knowledge
compounding at REAL scale remains the scale-work item it always honestly was.
