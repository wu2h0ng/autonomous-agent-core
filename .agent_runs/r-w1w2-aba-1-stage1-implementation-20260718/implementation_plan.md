# R-W1W2-ABA-1 Stage 1 Admission and Implementation Cast Plan

> **For agentic workers:** REQUIRED SUB-SKILL after admission only: use `superpowers:test-driven-development`. No public scaffold code may be written until Task 1 returns `QUALIFICATION_SCAFFOLD_CAST_APPROVED`; experiment code remains prohibited while the separate state is `EXPERIMENT_IMPLEMENTATION_DENIED`.

**Goal:** Convert the approved ABA design into a qualification-only public scaffold cast or an early PARK without building a real arm executor, scorer or ungrounded harness.

**Architecture:** The package separates public admission evidence from private custody. Public artifacts bind the two-stage claim ceiling, five bundle manifests and closed failure states. Private units, expected outcomes and mechanical paths never enter this repository, an LLM transcript or ordinary CI; only future public commitments and post-global-seal closed receipts may cross the boundary.

**Tech Stack after admission:** Python stdlib-only research module, immutable dataclasses/enums, canonical JSON + SHA-256, pytest/Ruff/Pyright. No Agent framework and no Product Runtime dependency.

## Global Constraints

- Stage 1 is exactly three prospective independent family blocks × five arms = 15 executions.
- Stage 1 can only return `PARK_STAGE1_NONDOMINANCE`, another prefrozen `PARK`, `INVALID`, `KILL_CURRENT_IMPLEMENTATION`, or `ADVANCE_TO_STAGE2_DESIGN / NO_MET`.
- Stage 1 cannot emit `MET`, `NARROW_MET`, `REDUCES_TO_*`, Product evidence, value evidence or autonomy evidence.
- Missing or unaccepted B1-B5 denies experiment implementation/freeze/run; a green qualification test cannot mint authority.
- Hidden identities, mappings, tests, expected outcomes, mechanical paths, keys, pre-seal arm labels and scorer internals never enter LLM/reviewer/tool/ordinary-CI transcripts.
- Legacy heads `8c090f1` and `a4afe14` are `CHARACTERIZATION_ONLY` until exact compatibility is independently accepted.
- No release is authorized.

---

### Task 1: Exact admission packet and preregistration candidate

**Files:**
- Modify: `.agent_runs/r-w1w2-aba-1-stage1-implementation-20260718/context_pack.json`
- Create: `.agent_runs/r-w1w2-aba-1-stage1-implementation-20260718/preregistration_candidate.md`
- Create: `.agent_runs/r-w1w2-aba-1-stage1-implementation-20260718/verification_report.md`
- Create: `.agent_runs/r-w1w2-aba-1-stage1-implementation-20260718/advisory_cast_review.md`
- Create: `.agent_runs/r-w1w2-aba-1-stage1-implementation-20260718/qualification_cast_review.md`

**Produces:** An exact design binding, five-bundle admission matrix, frozen public decision grammar and a binary `QUALIFICATION_SCAFFOLD_CAST_APPROVED` or `QUALIFICATION_SCAFFOLD_CAST_REVISE` disposition. The separate experiment state remains `EXPERIMENT_IMPLEMENTATION_DENIED` in both cases.

- [x] Bind canonical base, design source commit and exact design SHA-256.
- [x] Preserve the harsh Stage 1 route-kill comparison and claim ceiling.
- [x] Mark every absent external commitment as `UNBOUND`, not as a fillable default.
- [x] Incorporate independent design-auditor and legacy-code-characterizer findings.
- [x] Run exact-byte, forbidden-claim and JSON validity checks.
- [x] Commit only after `qualification_cast_review.md` reports no unresolved P0/P1.

**Admission result:** Until exact cast review passes, the scaffold is write-closed. Even after scaffold approval, B1-B5 absence keeps the experiment at `EXPERIMENT_IMPLEMENTATION_DENIED / PREREG_REVISE / NOT_IMPLEMENTATION_READY / NOT_FROZEN / NOT_RUN`.

### Task 2: External evidence closure; no candidate code

**Owners:** independent non-LLM curator/freezer/scorer plus founder/CTO. The candidate builder and any LLM may inspect only public commitments.

**Required evidence:**

1. Candidate-blind sampling frame commitment with at least three eligible independent public software families.
2. Independent semantic novelty/difficulty protocol acceptance.
3. Observable-information, release, reread, build-corpus and resource-rights commitment.
4. External non-LLM freezer/scorer identity and service digest plus fail-closed egress proof.
5. Public canonical test vectors that contain no hidden source or outcome material.

**Stop conditions:** Any hidden material enters a transcript; fewer than three families are groundable; representation cannot be isolated from information availability; or the complete 15-execution design exceeds the accepted resource ceiling. The result is `PARK` or `PREREG_REVISE`, never a waiver.

### Task 3: TDD public qualification scaffold, conditional on exact cast approval

**Files after admission only:**
- Create: `src/aac/r_w1w2_aba/contracts.py`
- Create: `src/aac/r_w1w2_aba/canonical.py`
- Create: `src/aac/r_w1w2_aba/validators.py`
- Create: `src/aac/r_w1w2_aba/stage1_state.py`
- Create: `src/aac/r_w1w2_aba/public_custody.py`
- Create: `tests/research/r_w1w2_aba/test_admission.py`
- Create: `tests/research/r_w1w2_aba/test_stage1_public_verifier.py`

`src/aac/` is the canonical Research Track code root. Do not introduce a parallel top-level Python namespace for this scaffold.

This source-root correction postdates the first exact cast approval. TDD remains write-closed until the calibrated reviewer approves this path-only delta.

**Interfaces and hard omissions:**
- Consumes only public B1-B5 manifests, public commitments, global seal and closed post-seal score receipt.
- Produces typed qualification failures and a public-only Stage 1 disposition state machine on synthetic public fixtures. It never loads private units, executes real arms or computes hidden scores.
- Does not provide `runner`, `executor`, candidate/baseline arm, real curator, scorer/freezer service, provider/tool adapter, signer, freeze receipt or run permit.

TDD sequence for every interface:

1. Write a bypass-detecting failing test for the exact missing/tampered/unauthorized case.
2. Run the single test and record the expected RED caused by absent behavior.
3. Add the minimal fail-closed implementation.
4. Run targeted tests, Ruff and Pyright.
5. Commit and request an independent exact-diff review.

**Mandatory first RED cases:** unknown bundle field, missing bundle acceptance, forbidden disposition, killer match incorrectly advancing, pre-global-seal scoring, unknown closed-output field, Stage 1 receipt relabelled as Stage 2, role collision, private-path reference and green-tests-mint-authority.

**Implemented TDD evidence:** RED was observed as two collection failures because `aac.r_w1w2_aba` did not exist. The minimal five-module implementation then passed 28 targeted tests and 121 combined Research tests, with Ruff and Pyright clean. Independent exact-head review returned `REVISE` (`P0=0 / P1=3 / P2=2`); the first correction RED was `28 failed, 8 passed`. That correction removed the required-child escape hatch, independently revalidated B1-B5 structure, bound manifests plus acceptance/review receipts to a separately supplied external root, and projected exact Stage 1 stage-spec/slot/block/scorer-subject digests into post-seal validation. The first correction re-review returned `REVISE` (`P0=0 / P1=1 / P2=0`) because direct dataclass construction could still bypass full parser invariants. The second RED reproduced both bypasses (`2 failed`), and both public trust boundaries now reparse `to_mapping()`. The second correction re-review returned `REVISE` (`P0=0 / P1=1 / P2=0`) because the qualifier still reused a stateful original object after replay. The third RED reproduced root/projection divergence; qualifier admission now captures a single mapping, reparses it and uses only retained canonical manifest/acceptance snapshots. The current head passes 40 targeted and 133 combined Research tests. Numeric scoring, strongest-killer computation, Stage 2 overlap, one-shot CAS and all execution/authority APIs remain `PARK` rather than being invented to satisfy tests.

### Task 4: Freeze and run remain separate future gates

Qualification-scaffold approval does not make the experiment implementation-ready, authorize experiment implementation or freeze the preregistration. A future evidence-closure decision, experiment implementation cast, exact-head review, external freeze receipt and separate founder one-shot run authorization are required. This plan neither selects units nor invokes a provider nor runs an experiment.
