# Active Discovery Batch-2A Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: use
> `superpowers:executing-plans` in the current single-writer worktree. Do not
> dispatch another writer for these files.

**Goal:** Add three genuinely different opaque development families and a
deterministic, matched-budget three-arm harness without creating research
evidence or exposing hidden truth.

**Architecture:** F2 logical-expiry, F3 quota/refill, and F4 graph-reachability
remain separate state machines with distinct public schemas and observations. A
referee-owned closed manifest binds each hidden configuration, public descriptor,
and family-specific probe catalogue. A unified adapter maps those catalogues into
the existing `HiddenAdapter` seam. The runner creates one fresh adapter per arm,
uses unit-cost probes until the exact budget is consumed, seals each transcript,
and returns receipts with no score or oracle field.

**Tech Stack:** Python 3.10+ stdlib, frozen dataclasses, canonical SHA-256
digests, pytest, Ruff, Pyright.

## Global Constraints

- Every new contract uses `mode = NOT_EVIDENCE` and rejects unknown fields.
- No model/provider call, arm comparison verdict, calibration, preregistration,
  result run, AGDE rewrite, autonomy claim, Product Runtime import, or
  `CURRENT_STATE` edit.
- F2-F4 public command and observation vocabularies are structurally distinct;
  the unified adapter contains explicit per-family catalogue mappings.
- VOI accepts only visible hypothesis weights, public candidate likelihoods, and
  normalized observations. Its API never accepts a hidden adapter, manifest
  configuration, transition function, score, or oracle.
- `SYSTEMATIC`, `RANDOM`, and `VOI` each receive a fresh adapter, the same family
  seed, the same candidate set, and the same exact unit budget.
- Hidden score access remains exclusively behind `SealedRefereeSession` and is
  never called by the matched-arm runner.

---

### Task 1: Closed family manifest and visible catalogue

**Files:**

- Create: `research_tools/active_discovery/families/manifest.py`
- Create: `research_tools/active_discovery/catalogue.py`
- Test: `tests/research_tools/test_active_discovery_family_manifest.py`

**Interfaces:**

- Produce `FamilyCode`, `FamilyManifest.from_mapping`,
  `FamilyManifest.manifest_digest`, `VisibleProbeCandidate`,
  and `VisibleProbeCatalogue`.
- Manifest fields bind schema/mode/family/seed/budget, descriptor digest,
  catalogue digest, and hidden-configuration digest. The manifest object is
  referee-owned and is not part of actor observations.

- [x] Write failing tests proving unknown fields, non-`NOT_EVIDENCE` modes,
  non-unit candidates, digest drift, and mismatched visible likelihood domains
  fail closed.
- [x] Run the new test file and confirm import/contract failures.
- [x] Implement the smallest frozen contracts and canonical digests.
- [x] Run the test file and confirm it passes.

### Task 2: F2 logical-expiry family

**Files:**

- Create: `research_tools/active_discovery/families/opaque_expiry.py`
- Test: `tests/research_tools/test_active_discovery_opaque_families.py`

**Interfaces:**

- Produce `OpaqueExpirySemantics`, `OpaqueExpirySnapshot`, and
  `OpaqueExpiryFamily` implementing `public_descriptor`, `state_digest`,
  `snapshot`, `restore`, `execute`, and `hidden_score`.
- Commands use opaque write/read/advance tokens; observations expose opaque
  presence/value/clock fields. Expiry is deterministic under logical time and
  all errors are atomic.

- [x] Write a failing expiry-boundary and snapshot-replay test.
- [x] Run only the F2 tests and confirm the family is missing.
- [x] Implement the deterministic state machine without filesystem, wall-clock,
  network, or model access.
- [x] Run the F2 tests and confirm they pass.

### Task 3: F3 quota/refill family

**Files:**

- Create: `research_tools/active_discovery/families/opaque_quota.py`
- Test: `tests/research_tools/test_active_discovery_opaque_families.py`

**Interfaces:**

- Produce `OpaqueQuotaSemantics`, `OpaqueQuotaSnapshot`, and
  `OpaqueQuotaFamily` over integer amount/progress inputs and opaque
  accepted/remaining outputs.
- Refill and denial semantics are numeric-state dynamics, not source precedence
  or expiry aliases.

- [x] Write failing consume/deny/refill and replay tests.
- [x] Run only the F3 tests and confirm the family is missing.
- [x] Implement the minimal deterministic quota state machine.
- [x] Run the F3 tests and confirm they pass.

### Task 4: F4 graph-reachability family and unified adapter

**Files:**

- Create: `research_tools/active_discovery/families/opaque_graph.py`
- Create: `research_tools/active_discovery/families/unified.py`
- Test: `tests/research_tools/test_active_discovery_opaque_families.py`
- Test: `tests/research_tools/test_active_discovery_unified_adapter.py`

**Interfaces:**

- Produce `OpaqueGraphSemantics`, `OpaqueGraphSnapshot`, and
  `OpaqueGraphFamily` with opaque add/remove/query tokens and deterministic
  directed multi-hop reachability.
- Produce `UnifiedFamilyAdapter.build` and
  `UnifiedFamilyAdapter.from_manifest`. Each family mapping builds at least six
  distinct unit probes from only its public descriptor and binds the resulting
  catalogue to the manifest.

- [x] Write failing graph mutation/reachability/replay tests and an assertion
  that F2/F3/F4 schemas and observations are structurally distinct.
- [x] Write failing unified-adapter tests for all four family codes, exact
  manifest reconstruction, descriptor/catalogue/configuration digest binding,
  and actor-surface leakage.
- [x] Run the two test files and confirm missing implementations.
- [x] Implement F4 and explicit F1-F4 adapter/catalogue mappings.
- [x] Run the two test files and confirm they pass.

### Task 5: Deterministic matched-arm runner

**Files:**

- Create: `research_tools/active_discovery/arm_runner.py`
- Test: `tests/research_tools/test_active_discovery_arm_runner.py`

**Interfaces:**

- Produce `ArmKind`, `MatchedArmRunSpec.from_mapping`, `ArmRunReceipt`,
  `MatchedArmReceipt`, `select_visible_voi_candidate`,
  `update_visible_beliefs`, and `run_matched_arms`.
- `SYSTEMATIC` selects by stable order. `RANDOM` uses a canonical digest rank of
  the public seed and probe id. `VOI` uses existing information gain and updates
  weights only from the selected candidate's public likelihoods and the returned
  status bucket.

- [x] Write failing closed-spec, label-permutation, fresh-adapter, exact-budget,
  replay-digest, halt, and no-hidden-score tests.
- [x] Run the runner test file and confirm imports/behaviors fail.
- [x] Implement selection, visible Bayes update, execution, seal, and receipt
  digests. Do not call `score_sealed`.
- [x] Run the runner tests and confirm they pass.

### Task 6: Boundary verification and one local commit

**Files:**

- Modify only Batch-2A files listed above if verification exposes a defect.
- Append a verification/completion event to the existing task-local
  `.agent_runs/accelerated-foundational-lanes-20260715/messages.jsonl` after the
  commit; do not add it to the product repository commit.

- [x] Run `uv run --extra product-test pytest tests/research_tools -q`.
- [x] Run `uv run --extra product-test ruff check research_tools/active_discovery tests/research_tools`.
- [x] Run `uv run --extra product-test ruff format --check research_tools/active_discovery tests/research_tools`.
- [x] Run `uv run --extra product-test pyright research_tools/active_discovery tests/research_tools`.
- [x] If runtime is reasonable, run the repository Research gate used by the
  accepted Batch-1 review and record its exact pass/skip counts.
- [x] Run `git diff --check`, inspect the exact staged range, commit once on
  `codex/r-active-discovery-1-core`, and report the full SHA without push/merge.
