# R-STATE-CREDIT-1 Real-Binding Candidate Build Packet

> Status: `APPROVED_IMPLEMENTATION_INPUT / NOT_INDEPENDENTLY_ACCEPTED / NOT_FROZEN / NOT_RUN`
>
> Claim ceiling: `REAL_BINDING_CANDIDATE / INDEPENDENT_ACCEPTANCE_REQUIRED / NOT_FROZEN / NOT_RUN`
>
> Base: `3aba2bd08dd2293139e71ab90640310a032c074b`
>
> Writer: Codex in `codex/r-state-credit-1-real-bindings-20260715`

## Goal Card

Build the exact, reviewable bytes that replace the runner's actor, corpus,
scorer, C7 and run-authority placeholders with real candidate artifacts while
preserving the non-authorizing boundary. The result must be independently
reviewable and mechanically fail closed, but it must not be frozen, connected to
ARK, result-run, adjudicated or trained in this lane.

This advances Research Track execution readiness only. It does not establish a
Stage-A result, an autonomy claim, a product capability or provider
connectivity.

## Architecture-theory input

This is builder input for a later RR-0029/RR-0031 review, not an acceptance
record.

1. **Claim class and channel.** `research-automation` in
   `X(research-automation)`: exact inputs can be materialized and checked without
   granting result authority.
2. **Null and killer.** Kill readiness if the adapter can use a CLI transport,
   read a secret outside the named environment reference, accept an open response,
   expose sealed truth to the actor, let scorer output a verdict, let actor own C7,
   accept identity/epoch drift, or treat a portfolio decision as per-run approval.
3. **Write path.** Direct typed HTTP request candidate -> closed actor response ->
   raw row only. Public corpus -> actor. Sealed truth -> scorer only. External stop
   signal -> runner only. No component writes policy, C7 authority, scientific
   verdict or training state.
4. **Strong baseline.** A0 full log remains mandatory and unchanged. These bytes
   do not alter arms, held-out seeds, thresholds, loss weights or stop rules.
5. **C6/C7/SD4.** Actor and scorer have no stop-signal path or token. C7 is an
   externally constructed adapter with owner and epoch binding. L4/L5 and SD4
   remain closed.
6. **Prior negatives.** Existing negative and PARK verdicts remain unchanged.
   This lane cannot rescue them and produces no scientific evidence.
7. **Decision ownership.** Builder produces candidate bytes. Kimi may provide a
   technical review only. Independent prereg and architecture reviewers must
   accept exact bytes. A different freezer freezes. Founder/CTO must separately
   authorize the one result-bearing run.

## Selected design

### Direct Responses actor candidate

`ark_responses_actor.py` implements a provider-neutral, stdlib-only Responses
transport and a typed actor adapter. The ARK descriptor pins:

- base profile `https://ark.cn-beijing.volces.com/api/plan/v3`;
- endpoint path `/responses`;
- model alias `ark-code-latest`;
- credential environment reference `ARK_API_KEY` only;
- deterministic decoding and timeout candidate values;
- connectivity status `UNRUN`.

The adapter never invokes arkcli. It reads the credential only at call time and
never stores it in bindings, request artifacts, exceptions or logs. Success is
accepted only through a closed response parser with exact request/model identity,
request and response digests, usage, explicit cost availability, latency and
timeout fields. HTTP/provider/timeout failures use typed, digest-only errors.

Official Volcengine documentation confirms the generic `/responses` suffix,
Bearer API-key authentication and `model`/`input` request core for the ordinary
ARK data plane. It does not, without a live call, prove the Agent Plan alias's
resolved model identity or every response field. Therefore this lane keeps the
connectivity canary `UNRUN`; any incompatible live response must fail closed and
trigger a new exact descriptor review.

### Deterministic reversible repository corpus

`real_corpus.py` deterministically renders seven family JSONL files, twenty
held-out episodes per family, four checkpoints per episode and four matched arm
requests per checkpoint. Each public case contains a bounded repository tree,
ordered reversible mutations, rollback records and actor-visible representations.
The public manifest hashes every case file and covers the exact frozen grid.

Hidden expected actions and loss codes live only in a separate sealed referee
JSONL plus sealed manifest. Public files and actor requests must contain no sealed
field names, hidden values or sealed paths. A loader verifies every byte before
building `RFinalBatch`; a reversible materializer test applies and rolls back one
case per family in temporary directories.

### Real raw scorer

`real_scorer.py` verifies the sealed manifest and truth bytes, indexes exact
episode/checkpoint/action rows and returns exactly one typed `ArmAssessment` per
arm. It has no actor, provider, C7 or run-authority handle. It emits only frozen
loss codes/weights; final verdict, winner, selection and training fields are
forbidden by grammar tests.

### External C7 candidate

`external_c7.py` reads an atomic canonical stop file through a stable regular-file
descriptor. Owner and epoch are immutable constructor bindings and are checked on
every observation. A missing stop file means continue; a matching stop record
means abort; malformed, symlinked, owner-drifted or epoch-drifted records fail
closed. The actor and scorer never receive this adapter or its path.

The candidate descriptor names the owner/epoch protocol but records independent
owner acceptance as unsigned. No writer or token-issuance surface is implemented
in production code.

### Authority candidate

The authority descriptor may cite the dated root accelerated-execution founder
decision as portfolio context. It must keep per-run authorizer identity,
independent acceptance, signature/digest and result authorization absent. The
formal preregistration therefore remains non-runnable even after actor, corpus and
scorer bytes are real.

## File map

- Modify `experiments/r_state_credit_1/run_contracts.py`: richer exact actor/C7
  bindings plus descriptor-stable artifact hashing.
- Modify `experiments/r_state_credit_1/result_runner.py`: directory durability,
  identity/epoch checks and richer raw rows.
- Create `experiments/r_state_credit_1/ark_responses_actor.py`: direct typed
  Responses adapter and typed failure envelope.
- Create `experiments/r_state_credit_1/real_corpus.py`: deterministic renderer,
  manifest verifier, batch loader and reversible materializer.
- Create `experiments/r_state_credit_1/real_scorer.py`: sealed-truth raw scorer.
- Create `experiments/r_state_credit_1/external_c7.py`: external atomic stop
  signal reader.
- Create `experiments/r_state_credit_1/bindings/*`: actor, prompt, schema, C7 and
  unsigned authority candidate artifacts.
- Create `experiments/r_state_credit_1/corpus/public/*` and
  `experiments/r_state_credit_1/corpus/sealed/*`: immutable generated corpus.
- Create focused tests for actor, corpus, scorer, verdict grammar and C7.
- Update the formal YAML and exact-content manifest only after code and generated
  bytes stabilize.
- Create a final build/verification report before exact Kimi review.

## TDD implementation plan

### Task 1: actor and base contract hardening

1. Add failing tests for exact ARK descriptor fields, env-only credential lookup,
   closed requests/responses, digest/usage/cost/error/timeout behavior and a
   transport that is never invoked when inputs are missing.
2. Add failing tests for response identity drift and the existing runner's
   pre-start C7, wrong-arm and content-digest paths.
3. Implement the minimum actor/binding/runner changes and stable-FD hashing plus
   parent-directory fsync; rerun until green.

### Task 2: public and sealed corpus

1. Add failing tests for exact 7 x 20 x 4 x 4 coverage, deterministic bytes,
   public/sealed separation, manifest integrity and reversible apply/rollback.
2. Implement the deterministic renderer and verifier.
3. Materialize generated bytes, verify a second render is bit-identical and keep
   all hidden truth outside actor inputs.

### Task 3: scorer and C7

1. Add failing metric and verdict-grammar tests for the sealed scorer.
2. Add failing pre-start/mid-run stop and owner/epoch drift tests for external C7.
3. Implement the minimum scorer and C7 adapter; keep final adjudication absent.

### Task 4: formal closure

1. Update YAML readiness to real candidate artifacts while preserving unsigned
   independent acceptance and run authority.
2. Add every exact new mechanism byte to `mechanism.files` and regenerate the
   manifest without spec/manifest cycles.
3. Run targeted tests, full Research, native workflow gates, Ruff, format,
   Pyright, candidate validation, manifest verification and diff checks.
4. Stage one exact diff, obtain Kimi technical review, make no post-review byte
   changes, and commit atomically.

## Explicit non-actions

- no ARK/provider/network call or connectivity canary;
- no arkcli transport;
- no secret read during build or test and no secret value in any artifact;
- no reviewer, C7-owner or founder impersonation;
- no prereg review record, architecture review record or native freeze lock;
- no result, verdict, model update, training, push, merge or release.
