# CLS-F1 Qualification Instrument Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a freeze-candidate, non-result A→B→A qualification instrument that can kill dual-store CLS when a budget-matched single-store replay/stability baseline matches adaptation and retention.

**Architecture:** A standalone evaluator fixture owns phase, latent context, reward truth, feature/action bijections, and scoring. Online arms consume only closed raw-feature observations, delayed feedback, typed corrections, and equal operation budgets. Baselines are implemented before the dual-store candidate; a scorer computes frozen metrics and K1–K5 dispositions from sealed trajectories.

**Tech Stack:** Python 3.12, stdlib dataclasses/enums/random/hashlib/json, pytest, Ruff; no model training and no new dependency.

## Global Constraints

- Status remains `QUALIFICATION_CANDIDATE / NOT_FROZEN / NOT_RUN`.
- No result seed, result-bearing run, freeze authority, or result authority is created.
- No arm-visible seed, turn, phase, schedule, latent context ID, changed-context marker, optimal action, or scorer metric.
- Feature dimensions/value names and action tokens receive hidden per-seed bijections; mapped behavior must be equivariant.
- Dual-store and strongest single-store receive identical environment, update, replay, and search budgets.
- Single-store stability/detector parameters are selected only on qualification seeds and immutable for result seeds.
- Implement strongest single-store before dual-store; do not change the environment to rescue the candidate.
- K1–K5 and the claim ceiling are copied exactly from the approved design.

---

### Task 1: Closed contracts and evaluator fixture

**Files:**
- Create: `experiments/continual_retention_f1/__init__.py`
- Create: `experiments/continual_retention_f1/contracts.py`
- Create: `experiments/continual_retention_f1/fixture.py`
- Test: `tests/test_continual_retention_f1_contracts.py`
- Test: `tests/test_continual_retention_f1_fixture.py`

**Interfaces:**
- Produces: `RawObservation(features, authorized_actions)`, `FeedbackEvent`, `CorrectionEvent`, `ArmBudget`, `OperationLedger`, `EpisodePlan`, `EvaluatorFixture.build(seed, config)`, and the evaluator-only sealed-outcome method.
- Hidden evaluator-only types: `LatentStep(phase, context_index, optimal_action, reward_draw)` and `SeedBijection`.

- [ ] **Step 1: Write failing closed-contract tests**

```python
def test_observation_has_no_oracle_fields():
    observation = RawObservation(features=(("f-x", "v-y"),), authorized_actions=("act-z",))
    assert set(observation.to_dict()) == {"features", "authorized_actions"}
    for forbidden in ("seed", "turn", "phase", "schedule", "context_id", "optimal_action"):
        assert forbidden not in observation.to_dict()

def test_budget_rejects_non_positive_or_unequal_adaptive_limits():
    with pytest.raises(ValueError, match="positive"):
        ArmBudget(max_updates_per_feedback=0, max_replays_per_feedback=2)
```

- [ ] **Step 2: Run the tests and confirm RED**

Run: `PYTHONPATH=. python3 -m pytest tests/test_continual_retention_f1_contracts.py -q`

Expected: import failure for `experiments.continual_retention_f1`.

- [ ] **Step 3: Implement immutable contracts and charged ledger**

```python
@dataclass(frozen=True)
class ArmBudget:
    max_updates_per_feedback: int
    max_replays_per_feedback: int

class OperationLedger:
    # Mutable counters are private; each method validates and charges count.
    # snapshot returns an immutable CostRecord including state size.
```

Every dataclass validates closed primitives, unique non-empty action tokens,
finite rewards, non-empty event digests, and positive budgets.

- [ ] **Step 4: Write failing fixture leakage and bijection tests**

```python
def test_seed_fixture_balances_changed_and_unchanged_contexts_without_leaking_ids():
    plan = EvaluatorFixture.build(seed=7, config=TEST_CONFIG)
    assert len(plan.changed_contexts) == 4
    assert len(plan.unchanged_contexts) == 4
    assert all("context" not in step.observation.to_dict() for step in plan.public_steps)

def test_isomorphic_seed_bijection_maps_features_and_actions_only():
    left, right, mapping = EvaluatorFixture.isomorphic_pair(seed=7, config=TEST_CONFIG)
    assert mapping.map_plan(left).public_steps == right.public_steps
    assert left.latent_steps != right.latent_steps
```

- [ ] **Step 5: Implement seeded A→B→A fixture**

Use eight latent contexts, four actions, exactly four B-changed contexts, balanced
block-shuffled contexts, delayed feedback, common random numbers, and hidden
dimension/value/action bijections. Public steps contain raw features only.

- [ ] **Step 6: Run Task 1 tests and commit**

Run: `PYTHONPATH=. python3 -m pytest tests/test_continual_retention_f1_contracts.py tests/test_continual_retention_f1_fixture.py -q`

Expected: PASS.

Commit: `git commit -m "feat(cls-f1): add closed permuted evaluator fixture"`

---

### Task 2: Strongest single-store replay/stability baseline and budget freeze

**Files:**
- Create: `experiments/continual_retention_f1/baselines.py`
- Create: `experiments/continual_retention_f1/qualification.py`
- Test: `tests/test_continual_retention_f1_single_store.py`

**Interfaces:**
- Consumes: Task 1 contracts.
- Produces: `OnlineArm.act(observation)`, `OnlineArm.observe(feedback)`, `OnlineArm.correct(correction)`, `OnlineArm.cost()`, `SingleStoreConfig`, `SingleStoreReplayStabilityArm`, and `FrozenQualificationConfig`.

- [ ] **Step 1: Write failing budget, replay, and immutability tests**

```python
def test_single_store_charges_every_update_and_replay():
    arm = SingleStoreReplayStabilityArm(config=CONFIG, budget=BUDGET)
    arm.observe(FEEDBACK)
    assert arm.cost().updates == BUDGET.max_updates_per_feedback
    assert arm.cost().replays == BUDGET.max_replays_per_feedback

def test_result_seed_cannot_retune_frozen_stability():
    frozen = FrozenQualificationConfig.freeze(
        qualification_seed_digest="a" * 64,
        selected=SingleStoreConfig(stability=0.25, detector_threshold=0.4),
    )
    with pytest.raises(ValueError, match="frozen"):
        frozen.for_result_seed(stability=0.5)
```

- [ ] **Step 2: Run tests and confirm RED**

Run: `PYTHONPATH=. python3 -m pytest tests/test_continual_retention_f1_single_store.py -q`

Expected: module/class import failure.

- [ ] **Step 3: Implement reservoir replay and functional stability**

Maintain one action-value vector per normalized raw feature tuple. For each
feedback, apply exactly the authorized update count, sample no more than the
authorized replay count from a deterministic reservoir, and apply a functional
penalty toward the frozen important-action snapshot. The arm stores source
event digests so correction can remove and deterministically rebuild state.

- [ ] **Step 4: Add correction and no-oracle tests**

```python
def test_single_store_correction_removes_invalidated_event_influence():
    before = arm.capture()
    arm.observe(FALSE_FEEDBACK)
    arm.correct(CorrectionEvent(invalidated_event_digest=FALSE_FEEDBACK.event_digest))
    assert arm.decision_state() == before.decision_state

def test_single_store_api_accepts_no_phase_or_context_label():
    assert tuple(inspect.signature(arm.act).parameters) == ("observation",)
```

- [ ] **Step 5: Run tests and commit strongest baseline before candidate**

Run: `PYTHONPATH=. python3 -m pytest tests/test_continual_retention_f1_single_store.py -q`

Expected: PASS.

Commit: `git commit -m "feat(cls-f1): add budget-matched single-store baseline"`

---

### Task 3: Reset, recency, static, and isolated oracle arms

**Files:**
- Modify: `experiments/continual_retention_f1/baselines.py`
- Create: `experiments/continual_retention_f1/oracle.py`
- Test: `tests/test_continual_retention_f1_baselines.py`

**Interfaces:**
- Produces: `ResetOnChangeArm`, `RecencyArm`, `StaticArm`, `WSLSDiagnosticArm`, `OracleCeiling`, and a named non-oracle arm factory.

- [ ] **Step 1: Write failing behavioral-distinction tests**

```python
def test_reset_recency_static_are_behaviorally_distinct_after_shift():
    traces = {name: synthetic_shift_trace(make_non_oracle_arm(name))
              for name in ("reset", "recency", "static")}
    assert len({trace.action_digest for trace in traces.values()}) == 3

def test_oracle_cannot_be_created_by_non_oracle_factory():
    with pytest.raises(ValueError, match="evaluator-only"):
        make_non_oracle_arm("oracle", budget=BUDGET)
```

- [ ] **Step 2: Run tests and confirm RED**

Run: `PYTHONPATH=. python3 -m pytest tests/test_continual_retention_f1_baselines.py -q`

Expected: missing arm failures.

- [ ] **Step 3: Implement cheap arms and separate oracle module**

Reset uses only public prediction error; recency uses a bounded valid-event
window; static uses a fixed public update count; WSLS remains diagnostic only.
`OracleCeiling` consumes evaluator-only `LatentStep` and is absent from the
non-oracle registry.

- [ ] **Step 4: Test corrections for every adaptive baseline**

```python
@pytest.mark.parametrize("name", ["single-store", "reset", "recency"])
def test_adaptive_baseline_invalidates_corrected_event(name):
    arm = make_non_oracle_arm(name, budget=BUDGET)
    assert corrected_trace(arm).invalidated_digest_absent
```

- [ ] **Step 5: Run tests and commit**

Run: `PYTHONPATH=. python3 -m pytest tests/test_continual_retention_f1_baselines.py tests/test_continual_retention_f1_single_store.py -q`

Expected: PASS.

Commit: `git commit -m "feat(cls-f1): add cheap baseline battery and oracle ceiling"`

---

### Task 4: Dual-store candidate implemented last

**Files:**
- Create: `experiments/continual_retention_f1/dual_store.py`
- Test: `tests/test_continual_retention_f1_dual_store.py`

**Interfaces:**
- Consumes: the same `RawObservation`, feedback, correction, and `ArmBudget` as Task 2.
- Produces: `DualStoreConfig` and `DualStoreRetentionArm` implementing `OnlineArm`.

- [ ] **Step 1: Write failing information, budget, and state tests**

```python
def test_dual_store_has_no_phase_or_context_oracle_surface():
    assert tuple(inspect.signature(DualStoreRetentionArm.act).parameters) == (
        "self", "observation"
    )

def test_dual_store_and_single_store_receive_equal_budget():
    assert DualStoreRetentionArm(CONFIG, BUDGET).budget == BUDGET
    assert SingleStoreReplayStabilityArm(BASE_CONFIG, BUDGET).budget == BUDGET
```

- [ ] **Step 2: Run tests and confirm RED**

Run: `PYTHONPATH=. python3 -m pytest tests/test_continual_retention_f1_dual_store.py -q`

Expected: missing class failure.

- [ ] **Step 3: Implement the minimal candidate**

Implement a fast recent value store and a slow versioned prototype bank.
Prediction-error evidence may copy the fast state into the slow bank, reset fast
state, and retrieve a prototype. Charge every comparison/copy/replay/retrieval.
Store event provenance and deterministically rebuild both stores after correction.

- [ ] **Step 4: Add action/feature renaming equivariance test**

```python
def test_dual_store_behavior_is_equivariant_under_hidden_bijections():
    left = execute_isomorphic_trace(DualStoreRetentionArm(CONFIG, BUDGET), LEFT)
    right = execute_isomorphic_trace(DualStoreRetentionArm(CONFIG, BUDGET), RIGHT)
    assert MAPPING.map_actions(left.actions) == right.actions
```

- [ ] **Step 5: Run tests and commit**

Run: `PYTHONPATH=. python3 -m pytest tests/test_continual_retention_f1_dual_store.py -q`

Expected: PASS.

Commit: `git commit -m "feat(cls-f1): add non-oracle dual-store candidate"`

---

### Task 5: Trajectory executor, hidden scoring, and K1–K5 adjudication

**Files:**
- Create: `experiments/continual_retention_f1/harness.py`
- Create: `experiments/continual_retention_f1/scorer.py`
- Test: `tests/test_continual_retention_f1_harness.py`
- Test: `tests/test_continual_retention_f1_scorer.py`

**Interfaces:**
- Produces: `EpisodeExecutor.execute(plan, arm) -> SealedTrajectory`, `HiddenScorer.score(plan, trajectory) -> ArmMetrics`, and `adjudicate(candidate, baselines, oracle, thresholds) -> Disposition`.

- [ ] **Step 1: Write failing coverage and correction tests**

```python
def test_missing_actions_are_scored_as_failure_not_removed():
    metrics = scorer.score(plan, trajectory_with_half_coverage)
    assert metrics.coverage == 0.5
    assert metrics.total_regret_denominator == plan.authorized_steps

def test_executor_delivers_correction_without_hidden_fields():
    trace = executor.execute(plan, recording_arm)
    assert trace.correction_deliveries == 1
    assert recording_arm.forbidden_fields_seen == ()
```

- [ ] **Step 2: Run harness tests and confirm RED**

Run: `PYTHONPATH=. python3 -m pytest tests/test_continual_retention_f1_harness.py -q`

Expected: missing executor/scorer failures.

- [ ] **Step 3: Implement deterministic execution and sealed trajectory**

The executor iterates public observations, schedules delayed feedback and the
typed correction, rejects unauthorized actions, records full authorized-step
coverage, and never passes `LatentStep` to a non-oracle arm.

- [ ] **Step 4: Write one synthetic metric fixture for every disposition**

```python
@pytest.mark.parametrize(
    ("fixture", "expected"),
    [(K1_MATCH, "KILL_TC1"), (K2_UNSAFE, "NO_ADOPT"),
     (K3_COSTLY, "OVERHEAD"), (K4_LEAK, "INVALID"),
     (K5_TRIVIAL, "TRIVIAL_INVALID")],
)
def test_k1_k5_are_mechanical(fixture, expected):
    assert adjudicate(**fixture).status == expected
```

- [ ] **Step 5: Implement metrics and exact disposition ordering**

Evaluate invalidity before triviality, then K1 match, safety/no-adopt, overhead,
and finally narrow qualification. Use the exact margins in the approved design:
one context cycle/10% horizon, `0.03`, `2×`, `0.05`, `0.95`, and `0.03`.

- [ ] **Step 6: Add equal-budget and equivariance integration tests**

```python
def test_candidate_and_single_store_use_same_budget_and_isomorphic_scores():
    assert candidate_trace.authorized_budget == single_trace.authorized_budget
    assert left_score.mapped_digest == right_score.mapped_digest
```

- [ ] **Step 7: Run tests and commit**

Run: `PYTHONPATH=. python3 -m pytest tests/test_continual_retention_f1_*.py -q`

Expected: PASS, with no multi-seed experiment output written.

Commit: `git commit -m "feat(cls-f1): add qualification scorer and kill rules"`

---

### Task 6: Freeze-candidate artifact and no-run closure

**Files:**
- Create: `docs/pre_spec/CLS-F1-QUALIFICATION.PREREG-CANDIDATE-2026-07-18.json`
- Create: `docs/pre_spec/CLS-F1-QUALIFICATION.EXACT-CONTENT-MANIFEST-2026-07-18.json`
- Create: `tests/test_cls_f1_qualification_freeze_candidate.py`
- Modify: `experiments/continual_retention_f1/__init__.py`

**Interfaces:**
- Produces: exact candidate bytes and `QUALIFICATION_CANDIDATE / NOT_FROZEN / NOT_RUN` status only.

- [ ] **Step 1: Write failing closure tests**

```python
def test_candidate_manifest_covers_every_mechanism_and_test_byte():
    assert set(manifest["artifact_sha256"]) == expected_paths()
    assert all(sha256(path.read_bytes()) == digest
               for path, digest in resolved_manifest_entries())

def test_package_cannot_mint_freeze_or_result_authority():
    for forbidden in ("freeze", "authorize_run", "run_result", "mint_receipt"):
        assert not hasattr(package, forbidden)
```

- [ ] **Step 2: Run closure tests and confirm RED**

Run: `PYTHONPATH=. python3 -m pytest tests/test_cls_f1_qualification_freeze_candidate.py -q`

Expected: missing prereg/manifest failure.

- [ ] **Step 3: Write closed preregistration candidate**

Bind exact environment constants, arm access, qualification/result custody,
budget equality, metrics, K1–K5 ordering, claim ceiling, and explicit
`result_run_authorized: false`.

- [ ] **Step 4: Generate exact-content manifest from committed mechanism bytes**

The manifest has `active_freeze_input: false`, status
`QUALIFICATION_CANDIDATE / NOT_FROZEN / NOT_RUN`, and hashes every package, test, design,
plan, and preregistration candidate file. The manifest cannot hash itself.

- [ ] **Step 5: Run focused and full verification**

Run:

```bash
PYTHONPATH=. python3 -m pytest tests/test_continual_retention_f1_*.py tests/test_cls_f1_qualification_freeze_candidate.py -q
ruff check experiments/continual_retention_f1 tests/test_continual_retention_f1_*.py tests/test_cls_f1_qualification_freeze_candidate.py
ruff format --check experiments/continual_retention_f1 tests/test_continual_retention_f1_*.py tests/test_cls_f1_qualification_freeze_candidate.py
git diff --check
PYTHONPATH=. python3 -m pytest tests/product -q
```

Expected: all PASS; no `.result.*`, run receipt, freeze receipt, or active manifest appears.

- [ ] **Step 6: Commit freeze candidate**

Commit: `git commit -m "research(cls-f1): add NOT_RUN freeze candidate"`

---

## Completion boundary

Completion means the instrument, arm battery, scorer, kill rules, exact-content
candidate, and tests exist and pass. It does not mean the preregistration is
frozen, a result run is authorized, a result exists, or CLS is supported.
