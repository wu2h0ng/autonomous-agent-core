# R-STATE-CREDIT-1 Runner/Prereg Build Packet

> Status: `BUILDER_PACKET / NOT_ARCHITECTURE_REVIEWED / NOT_FROZEN / NOT_RUN`
>
> Track: `Research Track` infrastructure; claim class `research-automation`
>
> Owner: Codex implementation writer
>
> Independent acceptance owner: a later reviewer and freeze lane

## Goal Card

**Objective.** Build the smallest provider-neutral Stage-A execution contract that
can be bound to the native preregistration freezer without making an experiment
runnable before its actor, corpus, scorer, C7 owner, and founder/CTO run authority
are real and exact.

**Compounding value.** Replace the current informal runner gap with typed,
fail-closed interfaces and one-shot execution semantics while preserving the
already-reviewed Batch-2B candidate bytes.

**Included scope.**

- an API-only `ActorClient` protocol and closed request/response contracts;
- exact actor, corpus, scorer, authority, and native freeze bindings;
- a raw, non-adjudicating r-final artifact contract;
- atomic start, interruption, C7 abort, write-once result, and no-rerun rules;
- a formal native-runner preregistration YAML and exact-content manifest;
- tests-only fakes and native workflow-runner compatibility verification.

**Excluded scope.**

- no provider implementation, credentials, network call, or CLI model transport;
- no real or calibration corpus generation, hidden-label materialization, scoring,
  adjudication, result-bearing execution, training, Stage B, product integration,
  push, merge, or release;
- no `prereg_review.json`, `architecture_theory_review.json`, RR-0031 reviewer
  record, freeze lock, or reviewer identity claim;
- no change to the Batch-2B candidate or any file hashed by its source manifest.

**Exit conditions.** The new contracts fail closed on every missing or drifting
binding; tests demonstrate RED then GREEN for execution boundaries; the formal
spec is parseable by the native freezer; its manifest covers every
`mechanism.files` byte; targeted and full Research gates, native compatibility,
Ruff, Pyright, and diff checks pass; an independent Kimi exact-diff review is
requested before any freeze lane acts.

## Architecture-Theory builder mapping

This section supplies review input. It is not the independent RR-0029 acceptance
record required by the native freezer.

1. **Claim and class.** `research-automation`: a typed experiment runner can make
   actor/corpus/scorer/authority drift and same-lock reruns mechanically visible.
   It is not a claim that A3 works or that any autonomy capability exists.
2. **Null and killer.** The route is killed if a missing binding can reach an actor,
   if a started or aborted lock can run again, if C7 cannot stop future calls, if a
   result can be overwritten, or if native review hashes different bytes.
3. **Channel map.** The runner writes only `X`-channel execution state and raw
   research rows. It does not write `B`, `K`, `R`, `T`, `S`, product policy,
   C7, audit authority, thresholds, baselines, or verdicts.
4. **Control path.** Exact spec and native lock -> complete typed bindings ->
   atomic start claim -> C7 check -> injected API-only actor -> injected bound
   scorer -> raw write-once artifact. Any exception leaves a terminal no-rerun
   record. Adjudication remains outside this path.
5. **Value source.** Loss weights, action grammar, held-out seeds, checkpoints,
   and stop rules come only from the reviewed Batch-2B candidate. The runner does
   not infer or edit them.
6. **Prior negatives.** G0-G13, C3, survival, risk, G12, and G13 remain unchanged.
   This build tests no new intelligence mechanism and cannot rescue a failed axis.
   Its only purpose is faithful execution infrastructure for the already-cast
   representation falsifier.
7. **Pressure and cheap baseline.** The pressure is long-horizon state drift under
   interruption. A0 exact full log remains the mandatory strong cheap baseline;
   tying or losing to A0 parks the typed-state route.
8. **Consumption proof.** Actor responses are closed actions for hermetic cases.
   The runner cannot alter arm representations, action options, scores, or C7.
   The scorer receives responses only after actor calls and has no actor control
   handle.
9. **Representation ownership.** A0-A3 own their frozen representations; the
   corpus owns observable events and hidden referee identities. The runner only
   transports typed values and verifies matched identifiers.
10. **C6/C7/SD4.** No SD4 or autonomy claim is admissible. C7 is injected by an
    externally owned abort interface, checked before start and around every actor
    call, and cannot be modified by the runner or actor.
11. **Legal interaction budget.** Only hermetic reversible temporary software
    repositories are in scope. External side effects are forbidden. API transport
    is a future bound dependency, not authorized by this build.
12. **Product/process boundary.** The code remains under `experiments/`; it does
    not enter Agent OS Product Track, product runtime, customer promises, or meta
    workflow runtime.
13. **Decision owner.** Founder/CTO supplies explicit run authority; an independent
    reviewer accepts exact content; an independent adjudicator owns the verdict.
    The writer, runner, actor, and scorer cannot self-approve.

## Strongest skeptical attack

A typed runner may create the appearance of readiness while the scientifically
decisive actor revision, held-out corpus, sealed referee, and scorer do not yet
exist. The design answers this by representing readiness as an all-or-nothing
closed object: unresolved values are absent, not fake; no production default is
provided; and execution cannot create its atomic start claim until native-lock and
binding integrity checks all pass. The formal prereg remains explicitly
`DRAFT_BINDINGS_REQUIRED` until a later lane supplies real bytes and triggers a
fresh exact-content review.

## Minimal implementation sequence

1. Add failing tests for closed binding and ActorClient contracts.
2. Implement only enough typed contracts to satisfy them.
3. Add failing tests for native lock drift and formal-spec compatibility.
4. Implement native-lock verification without importing the workflow repository.
5. Add failing tests for atomic start, interruption, C7 abort, raw result schema,
   and same-lock no-rerun behavior using tests-only fakes.
6. Implement the one-shot runner and keep verdict/adjudication absent.
7. Write the formal YAML and exact-content manifest after code bytes stabilize.
8. Run native workflow-runner subprocess compatibility checks without producing
   durable reviewer or freeze artifacts.
