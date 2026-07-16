# R-STATE-CREDIT-1 Recast Design Amendment

> Status: `DESIGN_ONLY / NOT_FROZEN / NOT_IMPLEMENTED / NOT_RUN / NOT_EVIDENCE`
>
> Date: `2026-07-16`
>
> Scope: Resolve open concerns 2–5 from the independent recast design review at
> `docs/research/R-STATE-CREDIT-1-recast-design-review-2026-07-16.md`.
>
> Track: `Research Track`
>
> Claim class: `research-automation` — candidate-byte design only.

## 1. What this amendment changes

This amendment adds the missing freeze-close specifications for:

- Open concern 2: representation budget and pressure fail-closed behavior;
- Open concern 3: A0 truncation risk and hard cap semantics;
- Open concern 4: exact deterministic checkpoint trigger rule;
- Open concern 5: exact authority artifact format, signature/witness mechanism,
  and verification code outline.

It also consolidates the pre-freeze mechanical gates from the review table into
a single checklist with acceptance criteria.

No code is changed, no provider is called, no model is trained, no experiment is
run, and no freeze is created by this amendment.

## 2. Representation budget and pressure (open concern 2)

### 2.1 Frozen budget parameters

The following values are frozen in the preregistration candidate and cannot be
changed after freeze without a new candidate:

| Parameter | Symbol | Value | Meaning |
|---|---|---|---|
| Max turns per episode | `T_max` | 60 | Hard upper bound on episode length. |
| Min turns per episode | `T_min` | 20 | Hard lower bound on episode length. |
| Max observation bytes per turn | `O_max` | 8,192 bytes | Serialized JSON byte cap for a single `Observation` object. |
| Max cumulative A0 bytes per episode | `B_A0` | 262,144 bytes | Hard cumulative cap on the serialized observation tuple received by A0. |
| Max cumulative non-A0 bytes per arm | `B_arm` | 65,536 bytes | Hard cumulative cap on the serialized representation received by A1, A2, A3. |

All byte counts are measured on the UTF-8 JSON serialization produced by the
runner before it is passed to the actor.  Whitespace normalization is applied
consistently so that formatting choices do not affect the budget.

### 2.2 A0 overflow behavior

A0 is the mandatory strong full-log baseline.  It receives the exact ordered
tuple of observations released so far.  A0 is **not allowed** to truncate,
select, summarize, or compress observations.

If, at the start of turn `t`, adding the turn-`t` observation to A0's cumulative
observation tuple would cause the cumulative byte count to exceed `B_A0`, the
runner must:

1. Log `REPRESENTATION_PRESSURE_EXCEEDED` with the turn index, cumulative bytes
   before turn `t`, and the new observation size.
2. Inject the perturbation class `REPRESENTATION_PRESSURE` into the episode
   record.
3. Force the actor serving A0 to output `ABSTAIN` at the current checkpoint and
   at every remaining checkpoint in the episode.
4. Terminate scoring for A0 only; other arms continue if they are still within
   their own budgets.

If A0 overflows, the episode is still valid for the other arms, but A0's score
for all remaining checkpoints is the maximum checkpoint loss.  This preserves
the paired-comparison structure: an A0 overflow is treated as an A0 failure, not
as an episode exclusion.

### 2.3 Non-A0 arm overflow behavior

If a compressed or projected representation for A1, A2, or A3 would exceed its
frozen per-arm cumulative budget `B_arm`, the runner must:

1. Log `ARM_BUDGET_EXCEEDED` with the arm identifier, turn index, and byte
   counts.
2. Force that arm to output `ABSTAIN` at the current checkpoint and at every
   remaining checkpoint.
3. Continue the episode for the remaining arms.

Because A1, A2, and A3 are representation arms, the runner is permitted to
produce smaller projections, but it may not selectively drop observations that
would change the arm's semantic content.  The projection function is frozen in
the preregistration candidate.

### 2.4 Generator hard constraint

The episode generator must be designed so that no valid episode can exceed the
per-turn cap `O_max` or the cumulative caps `B_A0` and `B_arm` under the frozen
projection functions.  A pre-freeze validation test must generate 1,000
episodes from the development seed set and prove that zero episodes trigger an
overflow under normal conditions.  Overflow behavior exists only as a
fail-closed safety net.

## 3. A0 truncation risk (open concern 3)

### 3.1 No truncation rule

A0 must receive the complete ordered tuple of observations released so far.  No
observation may be omitted, summarized, or replaced by a pointer.  The runner
must validate this property before every checkpoint by recomputing the
serialized tuple and asserting that its bytes equal the sum of the individual
observation bytes plus the frozen tuple envelope overhead.

### 3.2 Per-turn hard cap

The frozen `O_max = 8,192 bytes` is the maximum serialized size of a single
`Observation` object.  If the environment produces an observation larger than
`O_max`, the runner must:

1. Emit `OBSERVATION_SIZE_EXCEEDED`.
2. Mark the episode as `INVALID_INTEGRITY`.
3. Stop the run with verdict `STOP_INVALID_INTEGRITY`.

This is a design-time failure, not an actor failure.  The generator must be
revised so that no observation exceeds `O_max`.

### 3.3 Consistency with cumulative budget

The cumulative A0 budget is `B_A0 = 262,144 bytes`.  Because `T_max = 60` and
`O_max = 8,192`, the worst-case uncompressed cumulative size is
`60 × 8,192 = 491,520 bytes`, which is larger than `B_A0`.  Therefore the
overflow behavior in §2.2 is reachable even when every observation is within
`O_max`.  The generator must target typical episodes well below `B_A0`, but the
fail-closed overflow path must be mechanically tested before freeze.

### 3.4 ABSTAIN semantics under overflow

When an arm is forced to `ABSTAIN` because of budget overflow, the following
rules apply:

- The action is recorded as `"action": "ABSTAIN"`, `"reason":
  "REPRESENTATION_BUDGET_OVERFLOW"`.
- The scorer assigns the maximum checkpoint loss to that arm for the current and
  all remaining checkpoints.
- The other arms continue normally.
- The episode is not excluded from aggregation unless the integrity stop rules
  are also triggered.

## 4. Checkpoint trigger semantics (open concern 4)

### 4.1 Checkpoint trigger definition

A checkpoint is triggered when a perturbation enters a terminal phase.  Each
episode contains exactly four checkpoints.  The checkpoints are determined
before the episode runs by a deterministic function of the episode seed.

### 4.2 Terminal-phase decision table

For each perturbation class, the terminal phase is defined as follows:

| Perturbation class | Terminal phase trigger | Turn when checkpoint may fire |
|---|---|---|
| `ALIAS_REBIND` | After the alias has been rebound and a second observation confirms the new binding. | The turn after confirmation. |
| `OBJECT_VERSION_CHANGE` | After the new version is observed and a dependent assertion exists. | The turn the dependent assertion is observed. |
| `PROCESS_RESTART` | After restart completes and the first recovery observation is released. | The turn of the recovery observation. |
| `OUT_OF_ORDER_TRANSACTION` | After the out-of-order assertion and the previously observed assertion have both been seen. | The turn after both are observed. |
| `HALF_OPEN_VALID_TIME_BOUNDARY` | After the boundary turn passes and an action would be affected by it. | The affected action turn. |
| `SIMULTANEOUS_CONFLICTING_EVIDENCE` | After all conflicting assertions have been observed. | The turn the last conflict is observed. |
| `DELAYED_DEPENDENT_ACTION` | After the dependent action is observed and later refuted. | The refutation turn. |
| `ASSERTION_SUPERSESSION` | After the superseding assertion and a dependent of the old assertion are both observed. | The turn after both are observed. |
| `LATE_REFUTATION` | After the refutation and all currently observed dependents are known. | The refutation turn. |
| `TRANSITIVE_INVALIDATION` | After the full invalidation chain is observed. | The turn the chain closes. |
| `PENDING_COMMITMENT` | After a commitment with preconditions is recorded and a precondition is later observed. | The precondition observation turn. |
| `PRECONDITION_REFUTATION` | After a precondition is refuted. | The refutation turn. |
| `ACTION_DISPATCH` | After the dispatch is observed and the effect receipt is expected but not yet received. | The expected-receipt turn. |
| `RECEIPT_LOSS` | After the expected receipt turn passes without receipt. | The first post-due turn. |
| `INTERRUPTION_BEFORE_EFFECT_VERIFICATION` | After interruption and the retry observation. | The retry observation turn. |
| `REPRESENTATION_PRESSURE` | After cumulative budget is exceeded. | The overflow turn. |
| `PROTECTED_STATE_AT_BOUND` | After protected records exactly fill the budget and an action would add new state. | The action turn. |
| `DETERMINISTIC_RECOVERY` | After the recovery record is released and a recovery action is possible. | The recovery record turn. |

### 4.3 Deterministic checkpoint selection algorithm

The following pseudo-algorithm must be implemented exactly and frozen in the
preregistration candidate:

```text
function select_checkpoint_turns(episode_seed, perturbation_schedule):
    # perturbation_schedule: list of (turn, perturbation_class, terminal_turn)
    # terminal_turn is computed from the perturbation class using the table above.

    eligible_terminal_turns = sorted(set(terminal_turn for (_, _, terminal_turn) in perturbation_schedule))
    eligible_terminal_turns = [t for t in eligible_terminal_turns if t >= 5 and t <= T_max - 2]

    if len(eligible_terminal_turns) < 4:
        raise INVALID_EPISODE("insufficient terminal phases for four checkpoints")

    # Enumerate every 4-element subset whose consecutive turns are at least
    # 3 turns apart.  This guarantees the spacing invariant whenever any valid
    # selection exists and makes the seeded choice independent of the order in
    # which turns are drawn.
    valid_combinations = []
    for combo in combinations(eligible_terminal_turns, 4):
        if all(right - left >= 3 for left, right in zip(combo, combo[1:])):
            valid_combinations.append(combo)

    if not valid_combinations:
        raise INVALID_EPISODE("cannot space four checkpoints")

    rng = random.Random(hash_bytes("checkpoint-v1", episode_seed))
    selected = valid_combinations[rng.randrange(len(valid_combinations))]
    return list(selected)  # length 4, ascending, deterministic for the seed
```

The `hash_bytes` function is the SHA-256 of the concatenation of the literal
string `"checkpoint-v1"`, the null byte `0x00`, and the 32-byte episode seed.
The first 32 bytes of the digest seed the `random.Random` instance.
The `combinations` helper produces all 4-element subsets of
`eligible_terminal_turns` in lexicographic order.

### 4.4 Checkpoint capture rule

At each selected checkpoint turn, after the environment has released the turn's
observation and before the actor acts, the runner captures the observable prefix
(the ordered tuple of observations released so far) and requests one action from
each arm.  The action is scored against the seed-specific state at that turn.

### 4.5 No checkpoint metadata leakage

The actor request must not contain the checkpoint ordinal, the turn index, or
any signal that a checkpoint is occurring.  The only difference from a normal
turn is that the runner records the state snapshot and collects actions from all
four arms.

## 5. Authority artifact format (open concern 5)

### 5.1 Signature/witness mechanism

Authority artifacts use a two-layer mechanism:

1. **Content layer:** a canonical JSON file with a deterministic byte
   representation (keys sorted, no trailing whitespace, UTF-8, LF line endings).
2. **Witness layer:** a detached Ed25519 signature over the SHA-256 digest of the
   canonical JSON file, plus an optional independent witness hash published to a
   separate `reviews/` repository that the builder cannot write.

The runner does not need to verify the cryptographic signature itself if a
separate witness repository is used; it must verify that the artifact digest is
listed in the witness repository under an identity distinct from the builder.
For standalone operation, Ed25519 signature verification is required.

### 5.2 Required artifacts and JSON schemas

#### 5.2.1 `prereg-acceptance-<reviewer_id>.json`

```json
{
  "schema_version": "1.0",
  "artifact_type": "prereg-acceptance",
  "reviewer_id": "<string, distinct from builder_id>",
  "reviewed_at": "<ISO-8601 UTC timestamp>",
  "candidate_repo": "autonomous-agent-core",
  "candidate_branch": "codex/r-state-credit-1-real-bindings-20260715",
  "candidate_commit_sha": "<exact 40-char SHA>",
  "candidate_sha256": "<SHA-256 of exact-content manifest>",
  "prereg_path": "docs/pre_spec/R-STATE-CREDIT-1.STAGE-A.PREREG-CANDIDATE-<date>.json",
  "prereg_sha256": "<SHA-256 of prereg file>",
  "acceptance": true,
  "conditions": [
    "INSTANCE_INDEPENDENCE_VALID",
    "NO_PUBLIC_METADATA_LEAKAGE",
    "ARM_BLINDING_AND_BALANCING_VALID",
    "A3_POLICY_CONFOUND_ABSENT",
    "AUTHORITY_NON_SELF_MINTING"
  ],
  "notes": "<optional free-text review notes>"
}
```

#### 5.2.2 `architecture-acceptance-<reviewer_id>.json`

```json
{
  "schema_version": "1.0",
  "artifact_type": "architecture-acceptance",
  "reviewer_id": "<string, distinct from builder_id and prereg reviewer>",
  "reviewed_at": "<ISO-8601 UTC timestamp>",
  "candidate_commit_sha": "<exact 40-char SHA>",
  "candidate_sha256": "<SHA-256 of exact-content manifest>",
  "rr_0029_delta": "<path to RR-0029 delta document>",
  "rr_0031_delta": "<path to RR-0031 delta document>",
  "mechanism_file_hashes": {
    "experiments/r_state_credit_1/real_corpus.py": "<SHA-256>",
    "experiments/r_state_credit_1/real_environment.py": "<SHA-256>",
    "experiments/r_state_credit_1/real_scorer.py": "<SHA-256>",
    "experiments/r_state_credit_1/arms.py": "<SHA-256>",
    "experiments/r_state_credit_1/run_contracts.py": "<SHA-256>"
  },
  "acceptance": true,
  "notes": "<optional>"
}
```

#### 5.2.3 `native-freeze-lock.json`

```json
{
  "schema_version": "1.0",
  "artifact_type": "native-freeze-lock",
  "freezer_id": "<string, distinct from builder and reviewers>",
  "frozen_at": "<ISO-8601 UTC timestamp>",
  "candidate_commit_sha": "<exact 40-char SHA>",
  "candidate_sha256": "<SHA-256 of exact-content manifest>",
  "prereg_acceptance_digest": "<SHA-256 of prereg-acceptance artifact>",
  "architecture_acceptance_digest": "<SHA-256 of architecture-acceptance artifact>",
  "review_record_digests": [
    "<SHA-256 of review record 1>",
    "<SHA-256 of review record 2>"
  ],
  "builder_id": "<string>",
  "builder_id_included_for_audit_only": true
}
```

#### 5.2.4 `c7-acceptance-<owner_id>.json`

```json
{
  "schema_version": "1.0",
  "artifact_type": "c7-acceptance",
  "owner_id": "<string, C7 owner identity>",
  "epoch": "<string, monotonic epoch identifier>",
  "capability_token_sha256": "<SHA-256 of capability token>",
  "stop_path": "<URI or file path where stop signal is published>",
  "freeze_lock_digest": "<SHA-256 of native-freeze-lock>",
  "issued_at": "<ISO-8601 UTC timestamp>",
  "acceptance": true
}
```

#### 5.2.5 `run-authorization-<founder_id>.json`

```json
{
  "schema_version": "1.0",
  "artifact_type": "run-authorization",
  "authorizer_id": "<founder/CTO identity>",
  "authorized_at": "<ISO-8601 UTC timestamp>",
  "freeze_lock_digest": "<SHA-256 of native-freeze-lock>",
  "c7_acceptance_digest": "<SHA-256 of c7-acceptance artifact>",
  "run_id": "<unique run identifier bound to this authorization>",
  "max_runs": 1,
  "result_bearing": true,
  "acceptance": true,
  "notes": "<optional>"
}
```

### 5.3 Verification code outline

The following Python outline must be implemented in
`run_contracts.py::verify_binding_artifacts`:

```python
def verify_binding_artifacts(builder_id: str, artifact_dir: Path) -> dict:
    results = {
        "prereg": False,
        "architecture": False,
        "freeze_lock": False,
        "c7": False,
        "run_authorization": False,
    }

    # 1. Load canonical JSON artifacts and recompute digests.
    prereg = load_canonical_json(artifact_dir / "prereg-acceptance-*.json")
    arch = load_canonical_json(artifact_dir / "architecture-acceptance-*.json")
    freeze = load_canonical_json(artifact_dir / "native-freeze-lock.json")
    c7 = load_canonical_json(artifact_dir / "c7-acceptance-*.json")
    authz = load_canonical_json(artifact_dir / "run-authorization-*.json")

    # 2. Verify identities are distinct from builder and from each other.
    identities = {
        prereg["reviewer_id"],
        arch["reviewer_id"],
        freeze["freezer_id"],
        c7["owner_id"],
        authz["authorizer_id"],
    }
    if builder_id in identities:
        raise AuthorityError("builder_id must not appear in authority artifacts")
    if len(identities) < 5:
        raise AuthorityError("authority identities must be distinct")

    # 3. Verify cross-references and digests.
    assert_sha256_match(prereg, freeze["prereg_acceptance_digest"])
    assert_sha256_match(arch, freeze["architecture_acceptance_digest"])
    assert_sha256_match(freeze, c7["freeze_lock_digest"])
    assert_sha256_match(c7, authz["c7_acceptance_digest"])

    # 4. Verify acceptance flags are true and not placeholders.
    for artifact in (prereg, arch, freeze, c7, authz):
        if artifact.get("acceptance") is not True:
            raise AuthorityError("artifact acceptance must be boolean true")

    # 5. Verify run authorization is result-bearing, limited to one run, and bound to the run id.
    if authz["max_runs"] != 1 or authz["result_bearing"] is not True:
        raise AuthorityError("run authorization must authorize exactly one result-bearing run")
    if run_id is not None and authz.get("run_id") != run_id:
        raise AuthorityError(f"run authorization run_id mismatch: expected {run_id}, got {authz.get('run_id')}")

    # 6. Verify signatures or witness-repository entries (implementation-specific).
    verify_signatures_or_witnesses(artifact_dir)

    return {"valid": True, "identities": identities}
```

### 5.4 Builder-generated authority rejection test

A pre-freeze test must construct a builder-generated authority artifact (same
schema, `reviewer_id == builder_id`, `acceptance: true`) and assert that
`verify_binding_artifacts` raises `AuthorityError`.  This test must pass before
any freeze can be authorized.

### 5.5 Witness repository layout

If a separate witness repository is used, each authority artifact must be
copied to:

```text
reviews/
  R-STATE-CREDIT-1/
    <candidate_commit_sha>/
      prereg-acceptance-<reviewer_id>.json
      architecture-acceptance-<reviewer_id>.json
      native-freeze-lock.json
      c7-acceptance-<owner_id>.json
      run-authorization-<founder_id>.json
      manifest.sha256
```

The `manifest.sha256` file lists the SHA-256 digest and relative path of every
file in the directory.  The builder's CI pipeline must not have write access to
this repository.

## 6. Pre-freeze mechanical gates

The following gates instantiate the required close conditions from the
independent review table.  Each gate has a mechanical test, a pass criterion,
and a failure disposition.

| # | Gate | Mechanical test | Pass criterion | Failure disposition |
|---|---|---|---|---|
| G1 | Dummy classifier leakage | Train a dummy classifier (e.g., scikit-learn `DummyClassifier` with `family + checkpoint` as the sole features) to predict sealed truth on held-out seeds. | Accuracy ≤ max-class prior + 0.05 and Cohen's κ ≤ 0.05. | `STOP_INVALID_INTEGRITY` |
| G2 | Instance independence | `test_instance_independence.py` clusters episodes by event-graph digest, decision graph, and sealed labels using the development seed set. | No clustering into ≤ 7 equivalence classes; at least 30% of checkpoints within each family have seed-dependent correct actions. | `STOP_INSTANCE_INDEPENDENCE` |
| G3 | χ² arm-order uniformity | Across development episodes, count arm occurrences per position. Run χ² goodness-of-fit against uniform. | p > 0.05; all expected counts ≥ 5. | `STOP_INVALID_INTEGRITY` |
| G4 | Arm-order independence | Compute mutual information between arm order permutation and `(family, seed)` on development episodes. | Normalized mutual information ≤ 0.05. | `STOP_INVALID_INTEGRITY` |
| G5 | Byte-level absence of arm names | For every actor request generated on development episodes, search bytes for substrings `A0`, `A1`, `A2`, `A3`, `full log`, `rolling summary`, `retrieval`, `typed state`, and any arm role description. | Zero matches across all requests. | `STOP_INVALID_INTEGRITY` |
| G6 | No directive in arm output | Parse every arm representation produced on development episodes; assert no field named `recovery_directive`, `action_hint`, `policy`, or `recommended_action`. | Zero occurrences. | `STOP_INVALID_INTEGRITY` |
| G7 | Reversibility | Materialize every family on development seeds in a temporary directory, run the full episode, then delete the directory and rerun; compare state snapshots and scores. | Bit-identical state snapshots and scores across reruns; no files left outside the temp directory. | `STOP_INVALID_INTEGRITY` |
| G8 | Authority builder rejection | Construct builder-minted artifacts and run `verify_binding_artifacts`. | Raises `AuthorityError` for builder-minted artifacts; accepts real distinct-identity artifacts. | `STOP_INVALID_INTEGRITY` |
| G9 | Budget overflow fail-closed | Inject synthetic episodes that exceed `O_max`, `B_A0`, and `B_arm`; verify runner behavior. | `OBSERVATION_SIZE_EXCEEDED` triggers integrity stop; A0 overflow forces `ABSTAIN`; non-A0 overflow forces arm `ABSTAIN`. | `STOP_INVALID_INTEGRITY` |
| G10 | Checkpoint determinism | For a fixed seed, call `select_checkpoint_turns` twice and compare; verify exactly four checkpoints with minimum spacing of 3 turns. | Identical results across calls; four checkpoints; spacing ≥ 3; all within `[5, T_max - 2]`. | `STOP_INVALID_INTEGRITY` |

All gates must pass before the design can be converted into a frozen
preregistration candidate.  No gate may be moved, weakened, or skipped after the
preregistration lock.

## 7. Amendment status and next steps

This amendment resolves open concerns 2–5 from the independent recast design
review.  The design remains `DESIGN_ONLY / NOT_FROZEN / NOT_IMPLEMENTED /
NOT_RUN / NOT_EVIDENCE`.

Before a new exact head can be frozen, the implementation gate must produce code
satisfying:

- §2 and §3 (representation budgets and A0 truncation),
- §4 (checkpoint trigger algorithm),
- §5 (authority artifact format and verification),
- §6 (pre-freeze mechanical gates).

The remaining gates from the recast design packet §10 still apply.

---

**End of amendment.** No code was changed, no provider was called, no model was
trained, no experiment was run, and no freeze was created.
