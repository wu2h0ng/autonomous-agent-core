# Active Discovery Batch-2B Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `superpowers:executing-plans` to implement this plan task-by-task in the
> existing single-writer worktree. Steps use checkbox (`- [x]`) syntax for
> tracking.

**Goal:** Build a freeze-ready but unfrozen, unrun and non-evidentiary Stage-A
instrument-qualification preregistration candidate plus a fail-closed validator.

**Architecture:** A deterministic builder derives exact F1-F4 manifest bindings,
the three-arm matched-budget matrix, hidden-truth commitment, policies and source
hashes from the approved mechanism bytes. A checked-in JSON candidate must equal
that builder output. A pure validator checks candidate integrity and hypothetical
qualification-audit precedence but has no freeze, runner, model, provider or
result authority.

**Tech Stack:** Python 3.10+ stdlib, frozen dataclasses/enums, canonical JSON,
domain-separated SHA-256, pytest, Ruff and Pyright.

## Global Constraints

- Approved mechanism base is exactly
  `fa9314ea8cd84c1ea33615d4382c5c5da7b74651`.
- Status remains `FREEZE_READY_CANDIDATE / NOT_FROZEN / NOT_RUN / NOT_EVIDENCE`.
- Verdicts are limited to `QUALIFIED_FOR_NEXT_SCORING_SPEC`, `REVISE`, named
  `INVALID_*` states and `STOPPED_NO_VERDICT`.
- No `PASS`, `MET`, `NOT_MET`, `NULL`, VOI advantage, arm ranking or scientific
  result is representable.
- No model/provider call, training, arm execution, freeze lock, result write,
  `CURRENT_STATE` edit, F4 semantic change, push or merge.
- F4 self-loop behavior is untouched.
- The user-authorized delivery is one final atomic commit; intermediate TDD
  cycles are verified but not separately committed.

---

### Task 1: Add F1 actor-surface leakage regression

**Files:**

- Modify: `tests/research_tools/test_active_discovery_unified_adapter.py`

**Interfaces:**

- Consumes: `UnifiedFamilyAdapter.build`, `ProbeRequest`, current actor-surface
  canonicalization.
- Produces: regression coverage for F1 hidden vocabulary without changing
  production behavior.

- [x] Extend the existing parametrization from F2-F4 to all `FamilyCode` values.
- [x] Add exact F1 forbidden terms:

```python
"source_precedence",
"repeat_mode",
"unknown_mode",
"empty_is_missing",
"atomic_on_error",
"opaquecli",
```

- [x] Run:

```bash
uv run --extra product-test pytest \
  tests/research_tools/test_active_discovery_unified_adapter.py \
  -k actor_surface -q
```

Expected: PASS. This is a characterization test for already-opaque behavior, not
a production-code TDD cycle.

### Task 2: Establish the Stage-A module with a real red-green cycle

**Files:**

- Create: `research_tools/active_discovery/stage_a_prereg.py`
- Create: `tests/research_tools/test_active_discovery_stage_a_prereg.py`

**Interfaces:**

- Produces constants `STAGE_A_PREREG_SCHEMA`, `EXPERIMENT_ID`,
  `APPROVED_MECHANISM_BASE` and exception `StageAPreregValidationError`.

- [x] Write the first test without importing the missing module:

```python
def test_stage_a_prereg_module_exists() -> None:
    assert importlib.util.find_spec(
        "research_tools.active_discovery.stage_a_prereg"
    ) is not None
```

- [x] Run the single test and observe an assertion failure because the module is
  absent, not because of a typo.
- [x] Create the minimal module containing the constants and exception only.
- [x] Rerun the single test and observe PASS.

### Task 3: Build the closed exact candidate

**Files:**

- Modify: `research_tools/active_discovery/stage_a_prereg.py`
- Modify: `tests/research_tools/test_active_discovery_stage_a_prereg.py`

**Interfaces:**

- Produces:

```python
def build_stage_a_candidate(repo_root: Path) -> dict[str, object]: ...
def candidate_digest(raw: Mapping[str, object]) -> str: ...
```

- Candidate top-level fields are exactly:

```python
{
    "schema_version",
    "experiment_id",
    "mode",
    "candidate_state",
    "freeze_state",
    "run_state",
    "evidence_state",
    "authority_state",
    "approved_mechanism_base",
    "family_bindings",
    "family_matrix_digest",
    "arm_bindings",
    "random_arm_seed",
    "hidden_truth_contract",
    "qualification_metrics",
    "missing_data_policy",
    "leakage_policy",
    "c7_stop_policy",
    "verdict_grammar",
    "source_manifest",
    "source_manifest_digest",
    "candidate_digest",
}
```

- [x] Add tests that call the not-yet-present builder and assert the exact state
  strings, closed top-level fields and absence of scientific verdict tokens.
- [x] Run those tests and observe `AttributeError` for the missing builder.
- [x] Implement the minimal top-level builder and canonical candidate digest;
  leave family/source sections empty only until their next tests are written.
- [x] Rerun and observe PASS for the state/grammar tests.

### Task 4: Bind F1-F4, held-out allocation and identical budgets

**Files:**

- Modify: `research_tools/active_discovery/stage_a_prereg.py`
- Modify: `tests/research_tools/test_active_discovery_stage_a_prereg.py`

**Interfaces:**

- Family rows contain `family_code`, `family_role`, nullable
  `qualification_manifest`, required `evaluation_manifest`, and each manifest
  row contains `manifest` plus `manifest_digest`.
- Arm rows contain `arm_kind`, `budget_units` and `family_matrix_digest`.

- [x] Add failing tests for the exact allocation:

```python
expected = {
    "F1": ("QUALIFICATION_FAMILY", 101, 1009),
    "F2": ("QUALIFICATION_FAMILY", 103, 1013),
    "F3": ("QUALIFICATION_FAMILY", 107, 1019),
    "F4": ("HELD_OUT_FAMILY", None, 1021),
}
```

The tests reconstruct every non-null manifest through
`UnifiedFamilyAdapter.from_manifest`, assert qualification/evaluation seeds are
disjoint, and assert all three arms bind budget `4` and the same matrix digest.

- [x] Run the family/budget tests and observe failure on the empty sections.
- [x] Implement exact manifest creation, row digests and matrix digest.
- [x] Rerun and observe PASS.

### Task 5: Bind source bytes and hidden truth without exposing it

**Files:**

- Modify: `research_tools/active_discovery/stage_a_prereg.py`
- Modify: `tests/research_tools/test_active_discovery_stage_a_prereg.py`

**Interfaces:**

- `SOURCE_PATHS` is the exact sorted tuple named in the approved design,
  including `stage_a_prereg.py` and excluding the materialized candidate JSON.
- Hidden-truth policy is
  `REFEREE_ONLY_AFTER_TRANSCRIPT_SEAL`; its digest commits only to evaluation
  manifest and hidden-configuration digests plus the source-manifest digest.

- [x] Add failing tests that assert every source SHA-256 against raw bytes,
  source-path order/set, source-manifest digest and hidden-truth seal digest.
- [x] Add a temporary-repository test that copies all source files, mutates one
  byte and requires source drift to fail validation after Task 6.
- [x] Run the source/seal builder tests and observe failure on absent bindings.
- [x] Implement raw-byte hashing, source-manifest digest and hidden-truth seal.
- [x] Rerun builder tests and observe PASS; keep the future validator test red.

### Task 6: Implement the fail-closed validator and canonical loader

**Files:**

- Modify: `research_tools/active_discovery/stage_a_prereg.py`
- Modify: `tests/research_tools/test_active_discovery_stage_a_prereg.py`

**Interfaces:**

- Produces:

```python
@dataclass(frozen=True, slots=True)
class ValidatedStageAPrereg:
    candidate_digest: str
    source_manifest_digest: str
    family_matrix_digest: str
    candidate_state: str

def validate_stage_a_candidate(
    raw: Mapping[str, object], repo_root: Path
) -> ValidatedStageAPrereg: ...

def load_stage_a_candidate(
    path: Path, repo_root: Path
) -> ValidatedStageAPrereg: ...
```

- [x] Add tests that mutate then re-digest one field at a time: unknown top-level
  field, family role/seed/manifest digest, one arm budget, matrix digest, hidden
  seal, metric, missing-data rule, leakage rule, C7 rule, verdict token and source
  digest. Every mutation must raise `StageAPreregValidationError`.
- [x] Add a key-order permutation test proving canonical digest invariance.
- [x] Run validator tests and observe `AttributeError` for missing functions.
- [x] Implement exact-field/type validation, family reconstruction, source byte
  verification, cross-field digest checks and final equality with the
  deterministic candidate.
- [x] Implement a read-only JSON loader. Do not add a writer or CLI.
- [x] Rerun validator tests and observe PASS.

### Task 7: Implement qualification verdict precedence

**Files:**

- Modify: `research_tools/active_discovery/stage_a_prereg.py`
- Modify: `tests/research_tools/test_active_discovery_stage_a_prereg.py`

**Interfaces:**

- Produces `StageAQualificationVerdict`, frozen `QualificationAudit`, and:

```python
def qualification_verdict(
    audit: QualificationAudit,
) -> StageAQualificationVerdict: ...
```

- [x] Add failing tests for:

```python
# clean early halt; all missing cells are halt-caused
QualificationAudit(halted=True, missing_cells=12, halt_caused_missing_cells=12)
# -> STOPPED_NO_VERDICT

# leakage occurred before the same halt
QualificationAudit(
    halted=True,
    missing_cells=12,
    halt_caused_missing_cells=12,
    leakage_violations=1,
)
# -> INVALID_LEAKAGE
```

- [x] Add tests for pre-seal truth access, manifest/source/budget/post-stop
  violation, non-halt missing data, qualification failure and fully clean audit.
- [x] Run and observe failure because the verdict function is absent.
- [x] Implement precedence exactly: pre-halt/in-boundary integrity invalids →
  clean-halt exception → non-halt missing invalid → `REVISE` →
  `QUALIFIED_FOR_NEXT_SCORING_SPEC`.
- [x] Rerun and observe PASS.

### Task 8: Materialize the checked-in candidate

**Files:**

- Create: `research_tools/active_discovery/stage_a_prereg_candidate.json`
- Modify: `tests/research_tools/test_active_discovery_stage_a_prereg.py`

**Interfaces:**

- The JSON semantic object equals `build_stage_a_candidate(REPO_ROOT)` exactly.

- [x] Format and lint `stage_a_prereg.py` before hashing it.
- [x] Print the deterministic candidate as indented JSON to stdout; add those
  exact semantic fields with `apply_patch`. Do not add a production writer.
- [x] Add a test that loads the checked-in JSON, compares it to the builder and
  validates it.
- [x] Run the complete Stage-A test file and observe PASS.
- [x] Run the full `tests/research_tools` package and observe PASS.

### Task 9: Boundary verification and one local commit

**Files:**

- Modify only the Batch-2B files listed above if verification exposes a defect.
- Send verification/completion evidence to the coordinator after commit. The
  coordinator is the sole writer for the shared task-local message ledger.

- [x] Run:

```bash
uv run --extra product-test pytest tests/research_tools -q
uv run --extra product-test ruff check \
  research_tools/active_discovery tests/research_tools
uv run --extra product-test ruff format --check \
  research_tools/active_discovery tests/research_tools
uv run --extra product-test pyright \
  research_tools/active_discovery tests/research_tools
PYTHONPATH=src python -m unittest discover -s tests -v
git diff --check
```

- [x] Verify `opaque_graph.py` has no diff and no staged file lies outside the
  Batch-2B list.
- [x] Stage exact files, inspect `git diff --cached --check` and commit once with:

```bash
git commit -m "feat(research): add active discovery stage-a prereg candidate"
```

- [x] Report full commit SHA, materialized `candidate_digest`,
  `source_manifest_digest`, exact test counts, branch status and the ceiling
  `FREEZE_READY_CANDIDATE / NOT_FROZEN / NOT_RUN / NOT_EVIDENCE`.
