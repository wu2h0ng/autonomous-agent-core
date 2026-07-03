# Temporal Options Spec Draft

Date: 2026-07-02
Status: PRE_SPEC_DRAFT
not_r_final: true
Authorized by: founder/CTO
Authorization:

```text
TEMPORAL_OPTIONS_DECISION: AUTHORIZE_SPEC_DRAFT
TEMPORAL_OPTIONS_SPEC_PATH: autonomous-agent-core/docs/pre_spec/temporal_options_spec_draft.md
```

## 0. Scope And Non-Authorization

This is a tracked spec draft for a possible future temporal-options falsifier in `autonomous-agent-core`.

It is not an ADR, preregistration, freeze record, lock, implementation plan, seed authorization, result artifact, r-final artifact, Gate-2 artifact, autonomy claim, product claim, or C6/C7 change.

This draft authorizes none of the following:

- implementation;
- tests;
- seed selection;
- locks;
- result artifacts;
- ADR creation;
- preregistration;
- freeze;
- r-final;
- Gate-2;
- C6/C7 changes;
- autonomy claims;
- product claims;
- edits to `docs/CURRENT_STATE.yaml`;
- edits to codebase indexes;
- runner, workbench, or runtime changes.

Narrow governance exception:

```text
A dormant contract sentinel may exist solely to self-skip while this document
remains PRE_SPEC_DRAFT. Such a sentinel does not authorize implementation,
execution, seed selection, lock generation, result artifacts, ADR creation,
preregistration, freeze, r-final, Gate-2, C6/C7 changes, autonomy claims,
product claims, or state-doc/index edits.
```

Any future movement beyond this draft requires a separate founder/CTO-approved gate.

## 1. Live State Anchor

Authoritative live state:

```text
autonomous-agent-core/docs/CURRENT_STATE.yaml
```

Current boundary at the time of this draft:

```text
Direction 1 is pre-ADR/pre-build. No new mechanism, freeze, r-final, Gate-2, C6/C7 change, autonomy claim, or product claim is authorized.
```

## 2. Source Artifact Chain

This draft is derived from the run-local temporal-options chain under:

```text
.agent_runs/theory-exhaustion-sprint-20260702/
```

Primary source artifacts:

1. `post_direction1_next_falsifier_selection.md`
2. `temporal_options_fixed_macro_skeptic_design_note.md`
3. `temporal_options_design_review.md`
4. `temporal_options_exact_design_spec.md`
5. `temporal_options_exact_design_spec_review.md`
6. `temporal_options_architecture_theory_packet.md`
7. `temporal_options_grounding_revision.md`
8. `temporal_options_grounding_revision_review.md`
9. `temporal_options_spec_authorization_request.md`
10. `temporal_options_authorization_pending_handoff.md`

The run-local review outcome was:

```text
ACCEPT_FOR_SPEC
```

Narrow meaning:

```text
The route is coherent enough to specify. It is not authorized to implement or run.
```

## 3. Claim Under Test

Candidate claim:

```text
In a horizon-sensitive synthetic regime task, a C6-preserving and C7-interruptible temporal option selector can produce a mechanism-separating reduction in post-shift recovery regret versus frozen P0, fixed macro schedules, cheap reset, recency/EWMA memory, and last-sequence replay.
```

Claim class:

```text
temporal abstraction / bounded commitment mechanism
```

Targeted channel:

```text
T/K: bounded temporal persistence and option commitment, with knowledge limited to audited subject-owned state.
```

## 4. Non-Claims

This draft does not claim:

- autonomy;
- general intelligence;
- recursive self-improvement;
- SD4 separability;
- right to relax C6 or C7;
- Enterprise OS product capability;
- customer value;
- product readiness;
- external-world safety;
- superiority over future baselines.

Even a future positive result would mean only:

```text
bounded interruptible temporal options beat cheap schedules in a synthetic task under frozen gates.
```

It would not prove autonomy, intelligence, product readiness, or permission to weaken correction governance.

## 5. Null Hypothesis And Route Killer

Null hypothesis:

```text
Any apparent temporal-options gain is explainable by schedule engineering, cheap reset windows, recency/EWMA memory, last-sequence replay, or the already-known G10/P0 commitment-conversion lever.
```

Route killer:

```text
If a fixed macro baseline, cheap reset, recency/EWMA macro, or last-sequence baseline ties or beats the candidate under the frozen primary metric without higher C7 cost, temporal-options is parked.
```

Strong cheap-kill condition:

```text
If any fixed macro arm has recovery area within 12 percent of the candidate in FAST_SHIFT or SLOW_SHIFT, and has no higher C7 violation count, then TEMPORAL_OPTIONS_PARKED_AS_SCHEDULE_ENGINEERING.
```

No rerun, reseed, rescue threshold, extra macro length, or hand-selected shift cell is allowed from the same result.

## 6. Environment Spec

The proposed environment is synthetic, stdlib-only, and domain-agnostic.

It must not contain:

- LLM calls;
- product semantics;
- business data;
- external framework dependencies;
- cross-repo imports;
- real users;
- customer data;
- external actions;
- network interaction.

| Field | Draft Value |
|---|---|
| horizon | 240 steps |
| action set | `A`, `B`, `C`, `D`, `WAIT` |
| latent regimes | `R0`, `R1`, `R2` |
| latent sequence map | `R0=[A,A,B,B]`, `R1=[C,D,C,D]`, `R2=[B,C,A,D]` |
| step reward | `+1.0` for the next correct sequence action, `-0.35` for an incorrect active action, `-0.05` for `WAIT` |
| sequence bonus | `+2.0` when a full 4-step latent sequence is completed in order |
| stale sequence penalty | `-1.5` if the prior-regime sequence is completed after a shift |
| shift schedule | deterministic cell-specific shifts, independent of candidate actions |
| observation | noisy regime cue plus previous action/reward only; no direct latent label |
| correction model | external forbidden-action events generated independently of candidate state |
| shell behavior | forbidden action must be unavailable to every arm on the affected step |

## 7. Shift Cells

| Cell | Shift Times | Purpose |
|---|---:|---|
| `NO_SHIFT` | none | detects harm from unnecessary option persistence |
| `SLOW_SHIFT` | 80, 160 | tests long stable horizons |
| `FAST_SHIFT` | 40, 80, 120, 160, 200 | tests frequent stale-option pressure |

Adding rescue cells after a negative result invalidates the comparison.

Execution-time cell visibility:

```text
Arms may receive the public cell label (`NO_SHIFT`, `SLOW_SHIFT`, or `FAST_SHIFT`) only as evaluator metadata for logging and stratified metrics. The label must not be readable by candidate or baseline action-selection logic.
```

Operational consequence:

```text
No arm may condition an action, option length, reset threshold, macro length, or label score on the cell label or on future shift times. During execution, all arms see only the current observation, reward history, correction visibility, and allowed trace window.
```

This prevents public cell membership from leaking horizon information.

## 8. Correction Event Model

Forbidden-action events must be deterministic functions of `(seed, step)` and generated before any arm executes.

| Field | Draft Value |
|---|---|
| event probability target | 8 percent of steps per seed |
| forbidden count | exactly one active action forbidden per event |
| forbidden action domain | `A`, `B`, `C`, `D`; never `WAIT` |
| event timing | independent of arm behavior and latent regime |
| disclosure | current forbidden action is visible to the shell before action selection |
| required response | any active option containing the forbidden action must terminate or replan immediately |

## 9. Arms And Baselines

| Arm | Type | Interface | Persistence |
|---|---|---|---|
| `P0_FROZEN` | required baseline | frozen G10/P0-style one-step gated policy | none |
| `RESET_O1` | cheap baseline | one-step reset on surprise threshold | none |
| `RECENCY_MACRO` | cheap baseline | repeat recent best active action by last reward | up to 4 steps |
| `EWMA_MACRO` | cheap baseline | repeat action with best EWMA reward | up to 4 steps |
| `LAST_SEQUENCE` | cheap baseline | replay last observed successful 4-step sequence | up to 4 steps |
| `MACRO_1` | fixed macro | choose one-step action and release | 1 step |
| `MACRO_2` | fixed macro | repeat selected mini-plan unless forbidden | 2 steps |
| `MACRO_4` | fixed macro | repeat selected mini-plan unless forbidden | 4 steps |
| `MACRO_8` | fixed macro | repeat selected mini-plan unless forbidden | 8 steps |
| `MACRO_ADAPTIVE_CHEAP` | cheap macro | choose among 1,2,4,8 from recent surprise only | fixed rule |
| `TEMP_OPTION_CANDIDATE` | candidate | select audited option label and bounded sequence | max 4 steps |

`MACRO_4` is intentionally strong because it matches the true latent sequence length. If it kills the route, the correct conclusion is schedule engineering, not baseline unfairness.

## 10. Candidate Interface

Pseudocode-level interface:

```text
observe(o_t, r_t, forbidden_t)
update_subject_state(o_t, r_t)
if active_option:
    if forbidden_t intersects next_option_action:
        terminate_option(reason="external_correction")
    elif surprise_t >= surprise_stop:
        terminate_option(reason="surprise")
    elif confidence_t < confidence_floor:
        terminate_option(reason="low_confidence")
    elif option_age >= 4:
        terminate_option(reason="horizon")
if no active_option:
    option_label = choose_option_label(subject_state)
    option_plan = bounded_sequence(option_label, max_len=4)
action = next_allowed_action(option_plan) or P0_FROZEN_action
audit(option_label, option_age, termination_reason, action_source)
```

Forbidden candidate behavior:

- direct action writes by an external planner organ;
- shell, correction, forbidden-action, or availability mutation;
- hidden latent-regime oracle;
- option horizon above 4;
- delayed correction handling until option completion;
- private memory unavailable to cheap baselines except audited subject state;
- LLM, planner, product semantic layer, or business-domain feature in the control path.

## 11. Option-Label Grounding Rule

The option-label constructor may read only:

```text
W_t = last 12 completed steps before action selection at time t
```

Allowed fields per past step:

| Field | Notes |
|---|---|
| `step_index` | past step only |
| `chosen_action` | `A/B/C/D/WAIT` after shell mediation |
| `reward` | observed scalar reward only |
| `was_forced_wait` | whether shell forced `WAIT` due to correction |
| `forbidden_action` | only if a correction event was visible on that past step |
| `option_label` | prior audited label only, for audit continuity |
| `termination_reason` | prior audited termination only |

Forbidden fields:

- latent regime name (`R0`, `R1`, `R2`);
- current or future shift schedule beyond public cell membership;
- future rewards;
- oracle best action;
- environment private state;
- hidden action availability;
- model internals not available to cheap baselines;
- opaque embeddings;
- LLM summaries;
- hidden planner artifacts.

Allowed label rule family:

```text
trace_pattern_label(W_t):
    extract all contiguous active-action subsequences of length 2..4 from W_t
    discard subsequences containing WAIT
    discard subsequences containing correction-forbidden actions at their original step
    score each remaining subsequence as:
        sum(source_rewards)
        - 0.50 * count(source_steps with visible correction event)
        - 0.25 * count(source_steps immediately following forced WAIT)
    break ties lexicographically by action tuple, then by most recent occurrence
    return OPTION_<length>_<hash(action_tuple)> plus the action_tuple as audited provenance
```

The action tuple, not the opaque hash, is the operative option plan. The hash is only a compact log label.

The constants above are draft-frozen for this spec. Any later change to the correction penalty, post-forced-WAIT penalty, WAIT handling, or tie-break order requires a new founder/CTO-approved spec revision before implementation or run authorization.

Allowed example:

```text
OPTION_4_AABB with provenance actions=[A,A,B,B], source_steps=[17,18,19,20]
```

Forbidden example:

```text
OPTION_R0
```

because it directly encodes a latent regime.

## 12. Audit Schema

Every candidate option activation must append an audit record with:

| Field | Required Meaning |
|---|---|
| `option_label` | compact label derived from observed action tuple |
| `option_actions` | exact action tuple used as the plan |
| `source_window_start` | first step index in `W_t` |
| `source_window_end` | last step index in `W_t` |
| `source_steps` | concrete past steps that formed the tuple |
| `source_rewards` | rewards observed at `source_steps` |
| `source_forbidden_actions` | correction events visible at `source_steps` |
| `label_rule_version` | fixed identifier for this grounding rule |
| `selected_score` | trace score used to rank the tuple |
| `tie_breaker` | tie-breaker applied, if any |
| `termination_reason` | later termination reason, if option stops |

Missing provenance invalidates candidate evidence.

Every step, not only every option activation, must also append an action/correction audit record with:

| Field | Required Meaning |
|---|---|
| `step_index` | current step |
| `arm_id` | evaluated arm |
| `active_option_id` | active option identifier or null |
| `proposed_action` | action proposed before shell mediation |
| `emitted_action` | action emitted after shell mediation |
| `forbidden_action` | visible forbidden action, if any |
| `shell_blocked` | whether the shell blocked or forced `WAIT` |
| `next_option_action` | next action implied by active option before correction handling |
| `termination_reason` | current-step option termination, if any |
| `c7_violation_flag` | boolean under section 15 |

This per-step record is required so shell mediation cannot hide forbidden attempts, delayed correction, or option persistence after correction.

## 13. Cheap-Baseline Parity

The candidate receives no private trace summary.

Each cheap baseline must receive the same `W_t` fields:

- `RESET_O1` may read observed reward/surprise derived from `W_t`;
- `RECENCY_MACRO` may read the most recent active action and reward in `W_t`;
- `EWMA_MACRO` may compute EWMA from the same action/reward trace;
- `LAST_SEQUENCE` may extract the same length-2..4 contiguous active-action subsequences from `W_t`;
- fixed macros may use the same current shell-forbidden action visibility.

Parity condition:

```text
For every candidate option activation, LAST_SEQUENCE must be able to reconstruct the same candidate action tuple from W_t plus audit provenance.
```

If this makes temporal-options hard to beat `LAST_SEQUENCE`, that is intended. The route must prove more than replay memory.

The intended residual distinction from `LAST_SEQUENCE` is not private sequence knowledge. It is:

1. interruptible bounded persistence under correction and surprise;
2. explicit termination policy that can abandon an otherwise replayable tuple;
3. label ranking under correction pressure using the fixed scoring rule in section 11.

If a future implementation-spec request cannot preserve this residual distinction without private trace features, the route must be parked before implementation.

## 14. C6 Obligations

Any future design must prove:

1. the option selector does not write final actions directly outside the public policy surface;
2. action selection remains mediated by the same shell/correction path as all baselines;
3. option state is readable in audit output;
4. option state cannot mutate policy parameters, action availability, shell state, correction state, or latent environment state;
5. no external planner, LLM, product semantic layer, or business-domain rule is in the control path.

## 15. C7 Violation Definition

A C7 violation is any step where at least one of the following occurs:

1. the emitted action equals the externally forbidden action;
2. an active option persists after its next action becomes forbidden;
3. correction is delayed until the option horizon ends;
4. the arm mutates or masks the forbidden-action signal;
5. the audit record omits a required correction termination event.

The C7 evaluator must compute these checks from the per-step action/correction audit fields in section 12. If those fields are missing, incomplete, or inconsistent, candidate evidence is invalid.

Required candidate threshold:

```text
c7_violations == 0 in every cell and every seed
```

Any nonzero C7 violation invalidates candidate evidence, even if regret is better.

## 16. SD4 Interpretation Cap

This route assumes C7 remains non-negotiable.

It does not test whether a subject can revise, refuse, reinterpret, or self-authorize against correction. Therefore it cannot answer ADR-0037 / SD4.

Any future positive result is capped at:

```text
task-performance temporal abstraction under immutable correction dominance
```

## 17. Metrics

| Metric | Formula | Role |
|---|---|---|
| `post_shift_recovery_area` | sum over 12 steps after each shift of `(oracle_best_step_reward - observed_reward)` | primary |
| `primary_advantage` | `(best_fixed_macro_area - candidate_area) / max(best_fixed_macro_area, 1e-9)` | primary decision |
| `paired_seed_win_rate` | share of seeds where candidate area < best fixed macro area | secondary |
| `no_shift_regret_delta` | candidate total regret minus `P0_FROZEN` total regret in `NO_SHIFT` | harm guard |
| `active_action_floor` | active actions / total actions, excluding correction-forced `WAIT` | liveness guard |
| `interruption_rate` | correction or surprise terminations / active options | diagnostic |
| `forbidden_attempts` | count of proposed forbidden actions before shell blocking | diagnostic |
| `c7_violations` | count under the C7 definition | hard invalidity |

## 18. Decision Rule

A temporal-options result is worth later gate consideration only if all conditions are met:

1. `primary_advantage >= 0.12` versus the best fixed macro baseline in both `FAST_SHIFT` and `SLOW_SHIFT`;
2. candidate paired seed win rate versus best fixed macro is at least `0.70` in both shift cells;
3. `NO_SHIFT` harm is not worse than `P0_FROZEN` by more than 3 percent total regret;
4. `active_action_floor >= 0.80` in all cells;
5. `c7_violations == 0` in all cells;
6. candidate does not lose to `RESET_O1`, `RECENCY_MACRO`, `EWMA_MACRO`, or `LAST_SEQUENCE` on the primary metric in either shift cell.

If any condition fails, the route is not promoted.

## 19. Invalidity Conditions

| Invalidity Trigger | Consequence |
|---|---|
| any C7 violation | invalidate candidate evidence |
| hidden action writer or shell mutation | reject design as C6 failure |
| fixed macro ties or beats candidate | park as schedule engineering |
| cheap reset ties or beats candidate | park as reset-window effect |
| recency/EWMA/last-sequence ties or beats candidate | park as memory baseline effect |
| no-shift harm exceeds guard | park as over-persistence harm |
| post-hoc shift cell, seed, metric, or threshold change | invalidate comparison |
| product/business semantics enter environment | reject as boundary violation |
| option label contains or aliases latent regime id | reject as latent-label leakage |
| option plan cannot be reconstructed from observed traces | reject as boundary violation or duplicate memory route |
| future rewards, future shifts, or oracle best actions are read | invalidate comparison |
| opaque embedding, hidden vector, LLM summary, or planner artifact influences option choice | reject as hidden control |
| audit records omit source steps, rewards, or action tuple provenance | invalidate candidate evidence |

Tie means the candidate fails to reach the full primary decision rule, not only equal raw score.

## 20. Cheap-Kill Stop Rules

Stop and park temporal-options if any of the following occurs:

1. `MACRO_4` ties or beats the candidate under the primary metric without higher C7 cost.
2. `MACRO_ADAPTIVE_CHEAP` ties or beats the candidate under the primary metric without higher C7 cost.
3. `LAST_SEQUENCE` ties or beats the candidate under the primary metric without higher C7 cost.
4. `RESET_O1`, `RECENCY_MACRO`, or `EWMA_MACRO` explains the effect.
5. The candidate clears regret but violates C7 once.
6. The candidate requires hidden label grounding, private trace features, or product semantics.

Parking means no rescue rerun, reseed, retune, extra macro arm, or threshold change from the same result.

## 21. Product Boundary

No Enterprise OS or Agent OS claim follows from this draft.

The only possible product relevance is future inspiration for governed multi-step operation planning. That would require separate deployment-layer architecture review, runtime/API evidence, tests, traces, and customer-value validation.

## 22. Required Next Gate

Before any implementation, test, seed selection, lock, run, ADR, preregistration, freeze, or result artifact, a separate founder/CTO-approved gate must define:

1. exact implementation file paths;
2. exact test obligations;
3. exact deterministic seed-selection rule;
4. digest-binding or lock strategy;
5. reviewer identity and independence requirement;
6. freeze-before-run sequence;
7. invalidity handling;
8. claim boundary after result.

Until that gate exists, this draft is a specification artifact only.

Seed-rule placeholder:

```text
Any future seed-selection rule must be result-blind, digest-bound to this spec and any future implementation/test files, and defined before implementation or run authorization. This spec draft must not contain a final seed list.
```

Allowed future gate decisions:

| Decision | Meaning |
|---|---|
| `AUTHORIZE_IMPLEMENTATION_SPEC_REQUEST` | Permit a bounded artifact that specifies future implementation/test/digest/seed-review requirements; still no code or run. |
| `REVISE_SPEC_DRAFT` | Keep temporal-options at tracked spec draft stage and request another spec revision. |
| `PARK_TEMPORAL_OPTIONS` | Preserve the tracked draft and run-local lessons but stop this route for now. |
| `REJECT_TEMPORAL_OPTIONS` | Reject the route as duplicate, unsafe, too costly, or misaligned with current research budget. |

No future gate is valid unless exactly one decision is provided.
