# R-NONORACLE-INTERVENTION-SHIFT-1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an oracle-deleted intervention-stability mechanism, synthetic qualification harness, strong cheap baselines, leak/shortcut attacks and a non-authorizing freeze-candidate manifest.

**Architecture:** A closed `InterventionDataset` is the only mechanism input. The discoverer emits typed directed ancestry hypotheses from deterministic split-stability and permutation calibration; baselines share the public view and output type. Synthetic qualification owns synthetic truth, while real hidden scoring remains absent and separately custodied.

**Tech Stack:** Python 3.12 stdlib, frozen dataclasses, SHA-256 canonical JSON, pytest.

## Global Constraints

- Base is exact `c72375acb71c6a60cb0287cbd185ff07a196e0bd` plus approved design commit `d2d0e48`.
- Mechanism code must not import or reference Sachs, protein names, `GROUND_TRUTH`, `ancestors`, gold or scorer modules.
- Unit and synthetic qualification are allowed; real Sachs scoring/result execution is forbidden.
- End state remains `QUALIFICATION_ONLY / NOT_FROZEN / NOT_RUN`.
- Use TDD: observe every new behavioral test fail before implementation.

---

### Task 1: Closed public dataset and hypothesis contracts

**Files:**
- Create: `research_tools/nonoracle_discovery/__init__.py`
- Create: `research_tools/nonoracle_discovery/contracts.py`
- Test: `tests/research_tools/test_nonoracle_discovery_contracts.py`

**Interfaces:**
- Produces: `InterventionDataset.create(variable_ids, control_rows, intervention_rows, intervention_targets) -> InterventionDataset`.
- Produces: `DirectedAncestryHypothesis(source, target, signed_effect_micros, stability_micros, evidence_digest)`.

- [ ] **Step 1: Write failing closed-contract tests**

```python
def test_dataset_rejects_missing_or_duplicate_binding():
    with pytest.raises(DiscoveryContractError):
        InterventionDataset.create(("v0", "v1"), ((0.0, 0.0),) * 4,
                                   {"do0": ((1.0, 2.0),) * 4}, {})

def test_hypothesis_rejects_self_edge():
    with pytest.raises(DiscoveryContractError):
        DirectedAncestryHypothesis("v0", "v0", 1, 1, "0" * 64)
```

- [ ] **Step 2: Run RED**

Run: `python -m pytest tests/research_tools/test_nonoracle_discovery_contracts.py -q`
Expected: FAIL because `research_tools.nonoracle_discovery` does not exist.

- [ ] **Step 3: Implement immutable validation and canonical public-view digest**

Implement exact-length finite numeric rows, unique anonymous IDs, at least four control and four rows per intervention, one legal target per intervention condition, no unknown serialized fields, and immutable sorted mappings.

- [ ] **Step 4: Run GREEN and commit**

Run: `python -m pytest tests/research_tools/test_nonoracle_discovery_contracts.py -q`
Expected: PASS.

Commit: `feat(research): add oracle-deleted discovery contracts`

### Task 2: Intervention-stability mechanism

**Files:**
- Create: `research_tools/nonoracle_discovery/mechanism.py`
- Test: `tests/research_tools/test_nonoracle_intervention_stability.py`

**Interfaces:**
- Consumes: `InterventionDataset`.
- Produces: `StabilityCalibration(permutation_offsets, minimum_effect_micros)` and `discover(dataset, calibration) -> tuple[DirectedAncestryHypothesis, ...]`.

- [ ] **Step 1: Write failing mechanism tests**

```python
def test_stability_keeps_consistent_effect_and_rejects_one_partition_artifact():
    found = discover(confounded_indirect_fixture().dataset, frozen_calibration())
    pairs = {(item.source, item.target) for item in found}
    assert ("v0", "v2") in pairs
    assert ("v1", "v2") not in pairs

def test_row_order_does_not_change_output():
    assert discover(dataset_a, calibration) == discover(reordered(dataset_a), calibration)
```

- [ ] **Step 2: Run RED**

Run: `python -m pytest tests/research_tools/test_nonoracle_intervention_stability.py -q`
Expected: FAIL because `mechanism.py` is absent.

- [ ] **Step 3: Implement deterministic split-stability and permutation null**

Canonical-sort rows, split by alternating canonical positions, compute signed standardized mean shift against matched control halves, derive a max-null threshold from frozen deterministic label permutations, require same non-zero sign in both halves and both absolute shifts above `max(null, minimum_effect)`; rank by minimum-half effect, pooled effect, source and target.

- [ ] **Step 4: Run GREEN and commit**

Run: `python -m pytest tests/research_tools/test_nonoracle_intervention_stability.py -q`
Expected: PASS.

Commit: `feat(research): add intervention stability discoverer`

### Task 3: Matched cheap baselines and decisive synthetic qualification

**Files:**
- Create: `research_tools/nonoracle_discovery/baselines.py`
- Create: `research_tools/nonoracle_discovery/qualification.py`
- Test: `tests/research_tools/test_nonoracle_discovery_qualification.py`

**Interfaces:**
- Produces: `correlation_baseline(dataset, k)`, `pooled_shift_baseline(dataset, threshold_micros)`, `finite_screen_baseline(dataset)`.
- Produces: `confounded_indirect_fixture()` and `run_synthetic_qualification() -> QualificationReceipt`.

- [ ] **Step 1: Write failing decisive-case test**

```python
def test_qualification_contains_load_bearing_confounded_and_unstable_cases():
    receipt = run_synthetic_qualification()
    assert receipt.mechanism_recovers_true_relation
    assert receipt.correlation_selects_confounded_relation
    assert receipt.pooled_shift_selects_unstable_artifact
    assert receipt.mechanism_rejects_unstable_artifact
```

- [ ] **Step 2: Run RED**

Run: `python -m pytest tests/research_tools/test_nonoracle_discovery_qualification.py -q`
Expected: FAIL because baseline and qualification modules are absent.

- [ ] **Step 3: Implement baselines and synthetic-only receipt**

All arms consume identical `InterventionDataset` bytes and emit the same hypothesis type. Qualification may compare against synthetic truth declared inside `qualification.py`, but cannot import any real dataset or scorer.

- [ ] **Step 4: Run GREEN and commit**

Run: `python -m pytest tests/research_tools/test_nonoracle_discovery_qualification.py -q`
Expected: PASS.

Commit: `test(research): add decisive nonoracle qualification`

### Task 4: Oracle-leak and shortcut attack suite

**Files:**
- Test: `tests/research_tools/test_nonoracle_discovery_attacks.py`

**Interfaces:**
- Consumes public APIs from Tasks 1-3.
- Produces no runtime API; establishes bypass-detection evidence.

- [ ] **Step 1: Add attacks and observe at least one RED shortcut**

```python
def test_hidden_gold_mutation_cannot_change_mechanism_bytes():
    assert discover(dataset, calibration) == discover(dataset, calibration)

def test_variable_rename_is_equivariant():
    assert rename(discover(dataset, calibration), mapping) == discover(rename(dataset, mapping), calibration)

def test_missing_intervention_metadata_fails_closed():
    with pytest.raises(DiscoveryContractError):
        dataset_without_bindings()

def test_public_source_contains_no_oracle_tokens_or_imports():
    assert forbidden_source_hits(repo_root) == ()

def test_public_evidence_change_changes_output():
    assert discover(dataset, calibration) != discover(remove_stable_effect(dataset), calibration)
```

Run: `python -m pytest tests/research_tools/test_nonoracle_discovery_attacks.py -q`
Expected: at least one attack FAIL before hardening.

- [ ] **Step 2: Apply minimum hardening required by the failing attacks**

Only change Tasks 1-3 modules; do not add allowlists for real labels or expected edges.

- [ ] **Step 3: Run GREEN and commit**

Run: `python -m pytest tests/research_tools/test_nonoracle_discovery_attacks.py -q`
Expected: PASS.

Commit: `test(research): block nonoracle discovery shortcuts`

### Task 5: Exact freeze-candidate manifest without run authority

**Files:**
- Create: `research_tools/nonoracle_discovery/freeze_candidate.py`
- Test: `tests/research_tools/test_nonoracle_discovery_freeze_candidate.py`

**Interfaces:**
- Produces: `build_freeze_candidate(repo_root) -> FreezeCandidateManifest` with exact source/test SHA-256s, calibration digest, baseline IDs, attack IDs and fixed `NOT_FROZEN/NOT_RUN` fields.

- [ ] **Step 1: Write failing manifest tests**

```python
def test_manifest_is_exact_and_grants_no_run_authority():
    manifest = build_freeze_candidate(repo_root)
    assert manifest.status == "FREEZE_CANDIDATE_ONLY"
    assert manifest.run_authorized is False
    assert manifest.real_result_artifacts == ()
```

- [ ] **Step 2: Run RED**

Run: `python -m pytest tests/research_tools/test_nonoracle_discovery_freeze_candidate.py -q`
Expected: FAIL because freeze-candidate builder is absent.

- [ ] **Step 3: Implement exact-file binding and drift failure**

Bind every mechanism, baseline, qualification and attack-test byte; reject missing files, symlinks, duplicate paths and digest drift. Do not create a lock, permit, score or result.

- [ ] **Step 4: Run focused and inherited suites**

Run: `python -m pytest tests/research_tools/test_nonoracle_discovery_*.py -q`
Expected: PASS.

Run: `python -m pytest tests/research_tools -q`
Expected: existing 152 tests plus new tests PASS.

- [ ] **Step 5: Verify and commit**

Run: `git diff --check && git status --short`

Commit: `feat(research): seal nonoracle discovery freeze candidate`
