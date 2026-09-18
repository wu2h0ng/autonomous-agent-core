# `tests/product_eval` triage — 2026-09-18

> Status: `MEASURED`
> Track: Meta (test-infrastructure / evidence visibility)
> Worktree: `autonomous-agent-core/.worktrees/wt-peval`, branch `codex/product-eval-triage-20260918`, base `origin/main` = `03ac66b5`
> Command measured: `uv run --extra product-test pytest tests/product_eval -q`
> Claim class: development-process evidence. Nothing here is product-capability, research or commercial evidence.

## 1. Why this report exists

`tests/product_eval` (~940 items, the product-evaluation instruments: SPINE-E2E-1..4,
LH-RECOVERY-1A, SRL, mandate-responsibility, terminal coding eval) is largely red and was
invisible: **no CI step in `.github/workflows/ci.yml` runs it, or any file in it, at all.**

Two facts were verified rather than assumed:

1. `grep -rn product_eval .github/ scripts/` returns **nothing**. The `Tests (deterministic)`
   step does not collect this directory either: `tests/product_eval/` has no `__init__.py` and no
   module in it defines a `unittest.TestCase`, and `python -m unittest discover -s tests -p
   "test_*.py"` really does run 1237 tests with **0** of them from `tests/product_eval`
   (measured 2026-09-18, `OK (skipped=16)`).
2. The only place any `tests/product_eval` file is named is `pyproject.toml:67-73` — the
   **pyright** `include` list, seven files — and `pyright` is not run by CI either.

The one CI step that does cover the eval instruments is therefore "none". That is weaker than
the brief assumed (which described a step running two named files); the measured state is
recorded here as found.

## 2. Measured tallies

| Run | Command | Result |
|---|---|---|
| before | `uv run --extra product-test pytest tests/product_eval -q` | **119 failed, 819 passed, 1 skipped** (939 items) |
| after isolation fix | same | 119 failed, 819 passed, 1 skipped |
| after isolation fix + frozen-status fix + 4 new guard tests | same | **119 failed, 823 passed, 1 skipped** (943 items) — the 119 failing node ids are **byte-identical** to the baseline (`diff` of the sorted `FAILED` lists is empty); the 4 gains are the new guard tests |

Reference runs used while triaging (all 2026-09-18):

- `pytest tests/product_eval -q -p no:randomly` — 119 failed, 819 passed, 1 skipped (same 119 names).
- `pytest tests/product_eval -q` with a throwaway autouse fixture that snapshots and restores the
  whole process environment around **every** test — **119 failed, 819 passed, 1 skipped, and the
  119 failing node ids are byte-identical** (`diff` of the sorted `FAILED` lists is empty).

That last measurement is the answer to "how many of the 119 does the isolation bug account for":
**zero, in this collection order.** The bug is real and is fixed (§4), but no current failure is
caused by it; it is a latent hazard, not an active cause. See §4.3.

## 3. Failure buckets (119 failures, every one attributed from its traceback)

Counts are exact; each bucket was confirmed by re-running the named modules in isolation, which
reproduces the per-module counts exactly (so none of these is an ordering artefact).

### A. 82 — the pinned cross-repository runner worktree does not exist  (class **c**)

Every one of these 82 fails on the same absent asset:

```
ai-agent-engineering-workflow/.worktrees/team-event-contract-v1-20260713
```

- `tests/product_eval/test_json_schema_contract.py:25-31` — 22 tests. Fails inside
  `_assert_pinned_runner_identity()` (`:43-47`), which shells `git branch --show-current` with
  `cwd=RUNNER_WORKTREE` → `FileNotFoundError: [Errno 2] No such file or directory`.
- `tests/product_eval/test_runner_contract_qualification.py:25-29` — 31 tests. Two shapes:
  `FileNotFoundError` from the same missing path, and
  `product_evals/common/runner_contract_qualification.py:180-181`
  (`if not worktree.is_dir(): raise ValueError("INVALID_RUNNER_IDENTITY")`). Many of the 31 then
  report the second-order symptom `Regex pattern did not match. Expected
  'INVALID_RUNNER_CONTRACT_QUALIFICATION' / Actual message: 'INVALID_RUNNER_IDENTITY'` — the
  identity check fires before the mutation under test can run, so the intended assertion is never
  reached. `test_qualification_rejects_dirty_runner_worktree` (`:480`) additionally shells
  `git clone --branch codex/team-event-contract-v1-20260713 <RUNNER_WORKTREE>` → exit 128.
- `tests/product_eval/test_spine_e2e_4_scratch_cli.py:26-30,89-90` — 15 tests
  (`test_phase_anchor_*`, `test_anchor_fixture_*`).
- `tests/product_eval/test_spine_e2e_4_combined_qualification.py:23-28,97` — 12 tests.
- `tests/product_eval/test_spine_e2e_4_assets.py:27-32,59-60` — 2 tests.

The asset is gone, not merely un-checked-out. In
`/Users/mima1234/Documents/AI-Agent-Projects/ai-agent-engineering-workflow`:
`git cat-file -t 50eb4d27b17688f0943f80207dddb702983afd51` → `fatal: could not get object info`;
the branch `codex/team-event-contract-v1-20260713` is absent locally and from `origin/*`
(that repo's HEAD is now the unrelated `5fce9e9` on `main`); `.worktrees/` does not exist.

**Unsatisfiable here, and by design not repairable from this repo**: reconstructing that worktree
means writing into a sibling repository, and AGENTS.md §3.8 forbids cross-repo checkout/import
without an explicit founder/CTO ADR. The correct disposition is a decision (re-pin the runner
identity to a commit that exists, or retire the SPINE-E2E-3/4 runner-contract instruments), not a
test edit.

### B. 27 — Docker daemon and the pinned immutable image are unavailable  (class **c**)

`tests/product_eval/test_srl_docker_exec.py` (12) and
`tests/product_eval/test_srl_e2e_falsifier_docker_exec_wiring.py` (15), all with the identical
last frame:

```
product_evals/srl_e2e_falsifier/docker_exec.py:279:
    DockerExecutorUnavailable: allowed immutable Docker image is unavailable
```

Reached through `trusted_docker_executor()` → `_expected_policy()` → `_resolve_fixed_image()`
(`docker_exec.py:272-294`), which runs
`docker image inspect python@sha256:423ed6ab25b1921a477529254bfeeabf5855151dc2c3141699a1bfc852199fbf`
(`:37-42`) and requires the resolved `Id` **and** `RepoDigests` to match exactly.

Environment: `/opt/homebrew/bin/docker` exists (client 29.6.0, context `colima`) but the daemon
is not running (`Cannot connect to the Docker daemon at unix:///Users/mima1234/.colima/default/docker.sock`),
and the pinned image is therefore neither present nor inspectable. Neither test module has any
skip or availability guard today — they simply fail.

### C. 5 — frozen LH-RECOVERY-1A artefacts vs. the evolved `WorkflowGraph` contract  (class **a**, frozen artifact is **d**)

- `tests/product_eval/test_lh1a_design.py:7204` and `:7691`, via `_assert_exact_workflow` at
  `:4451`, compare `workflow.model_dump(mode="json")` against a literal containing
  `"schema_version": "1.0"`. The current contract reports `"WorkflowGraph/dag_v1"`:
  `AssertionError ... {'schema_version': 'WorkflowGraph/dag_v1'} != {'schema_version': '1.0'}`.
- `tests/product_eval/test_lh1a_design.py:7640` (the "incoming_prefix_edge" mutation): mutating an
  edge `condition` produces a graph that `dag_v1` itself rejects, and
  `apps/api_server/app.py:2997` (`replan_task` → `WorkflowGraph.model_validate`) lets
  `pydantic.ValidationError: dag_v1 does not support conditional edges` escape instead of the
  `ReplanRejectedError` the public failure path otherwise raises.
- `tests/product_eval/test_lh1a_design.py:9558` asserts that every basename in
  `FORBIDDEN_PRE_D1_BASENAMES` (`:126-138`, which includes `fixed_baseline.py`) is absent from
  `product_evals/lh_recovery_1a/`. That file exists (`7f6c5ef3 feat(eval): seal LH1A fixed
  baseline candidate`) and is itself bound as a required source by the combined-D1 precommit —
  the two frozen artefacts contradict each other.
- `tests/product_eval/test_lh1a_combined_d1.py:259`: the sealed candidate binds
  `tests/product_eval/test_lh1a_design.py` at sha256 `1827db86…` (recorded in
  `docs/research/LH-RECOVERY-1A-COMBINED-D1-PRECOMMIT.yaml:38`) while the file on disk is
  `65474719…`. The candidate therefore binds a stale digest of its own design test.

Four of the five are the instrument correctly failing closed against a product contract that moved
after the freeze; the fifth is the same drift expressed as a stale digest. Repairing them means
re-cutting a pre-registered artefact or changing the product's workflow schema version — both are
founder-reserved (root AGENTS.md §7), and patching a failed historical baseline to make an old gate
pass is forbidden (root AGENTS.md §11.8).

### D. 1 — historical run artefacts in the shared parent workspace  (class **c**/**d**)

`tests/product_eval/test_spine_e2e_4_scratch_cli.py:158` requires
`<workspace>/.agent_runs/spine-e2e-4-20260713/evaluation/phases.jsonl` (and three siblings) to be
absent. They are present — the adjudicated 2026-07-13 run's own artefacts, outside this repository
(`/Users/mima1234/Documents/AI-Agent-Projects/.agent_runs/`). The assertion encodes "no formal
output exists yet", which was true when the instrument was written and is not true of this
operator's workspace. It cannot be fixed from inside the repo, and deleting another workstream's
artefacts is not this task's call.

### E. 1 — a newer eval harness reaches into private Product organs  (class **a**)

`tests/product_eval/test_spine_protocol.py:91-104` walks **every** `.py` under `product_evals/`
(`_all_harness_python()` → `HARNESS.rglob("*.py")`, `:52-59`) and forbids attribute access named
`provider`, `provider_configured`, `tasks`, `_event_store`, `__dict__`, …

```
AssertionError: product_evals/terminal_agent_eval/l1_harness.py: private Product organs:
['_event_store', 'provider', 'provider_configured', 'tasks']
```

Offending lines: `product_evals/terminal_agent_eval/l1_harness.py:99-103`
(`app.provider = DeterministicProvider(...)`, `app.provider_configured = True`) and `:113`
(`for event in app.tasks._event_store.read(task_id)`). The guard's *scope* (all of `product_evals`)
is broader than the SPINE harnesses it was written to police, and the newer terminal coding eval
does not honour the same boundary. This is a genuine defect, not a stale expectation: the whole
point of the guard is that an instrument must drive the product through its public surface.
Reproducer:

```bash
uv run --extra product-test pytest \
  "tests/product_eval/test_spine_protocol.py::test_harness_rejects_private_product_organs_and_dynamic_reflection" -q
```

Left unfixed deliberately: removing the private access needs a public way for an eval instrument to
inject a scripted deterministic provider (there is none — `configure_provider` requires an HTTP
endpoint and rewrites `credential_ref_id`), and narrowing the guard instead would weaken it. That is
a separate change with its own design decision.

### F. 2 — the frozen provider banks no longer match the live tool wire format  (class **a**, frozen bank is **d**)

Both in `tests/product_eval/test_provider_bank.py`:

1. `:457` — `FrozenProviderServer` answers **HTTP 422 `UNKNOWN_REQUEST_DIGEST`**
   (`product_evals/common/provider_bank.py:407-431`). Measured with a minimal repro: the bank's
   recorded body hashes to `4670bd59eaecb91f753eb9476500f3ae13766aa0edf83cdd31040359a667e78b`,
   the body the current provider actually sends hashes to
   `dac5b0a96e1823ddf47eb0e210fafb12c0916a9250cf3a491fb9b5ae84c595c9`. The only difference is the
   tool definition: the bank records `"description": "Invoke typed capability
   workspace.apply_patch"` with `"parameters": {"type": "object", "additionalProperties": true}`,
   while `packages/os_core/src/agent_os_core/provider.py:1360-1378` (`_tool_definition`, plus the
   `_TOOL_DESCRIPTIONS`/`_WORKSPACE_TOOL_PARAMETERS` tables) now emits the real capability
   description and the strict per-capability JSON schema. The same holds for the e2e_2/3/4 banks
   (all four still carry the generic description).
   Cause: `0ef69521 feat(tools): tell the model what the tools and their results mean` changed the
   product's wire format **after** the banks were frozen (`d7d4d4d2`, `39b1991d`). The instrument
   fails closed, which is correct behaviour; the bank is stale.
2. `:382` — `agent_os_core.errors.RunExecutionError: bound provider invocation requires an exact
   configuration snapshot` from `packages/os_core/src/agent_os_core/execution.py:1350-1352`: a run
   whose app has a bound env provider but whose task carries no configuration snapshot is refused.
   The frozen test creates the task without one.

Repair requires either restoring the generic tool definitions in the product (a real product
behaviour change) or re-freezing four pre-registered provider banks — not a small, clearly-correct
fix, and not this change's call.

## 4. What was fixed

### 4.1 The process-environment leak (class **b**, test isolation)

`product_evals/common/public_surface.py:88-101` (`configure_provider_environment`) wrote
`AGENT_OS_PROVIDER_BASE_URL`, `AGENT_OS_PROVIDER_MODEL`, `AGENT_OS_PROVIDER_TEMPERATURE`,
`AGENT_OS_PROVIDER_API_KEY_ENV` and `SPINE_E2E_1_PROVIDER_KEY` into `os.environ` and **never
restored them**. The application reads its provider configuration from the process environment, so
the write has to be process-wide while an application is built — but a caller that shares its
process (any pytest session) then leaves every later arm pointed at a closed loopback endpoint. It
is the same hazard class that lets a harness reach the operator's real provider configuration.

Fix, in `product_evals/common/public_surface.py`:

- new `provider_environment(base_url)` context manager (`:104-136`): snapshots the exact prior value
  of every provider variable, applies the frozen configuration, and restores the snapshot in a
  `finally`.
- `prepare_case` (`:219-...`) now builds **each arm inside its own `provider_environment` scope**,
  and restores the caller's environment in an outer `finally` — so arm two starts from the same
  environment arm one did, and nothing outlives the call.
- the docstring of `configure_provider_environment` documents that shared-process callers must use
  the scoped form.

Tests added (`tests/product_eval/test_spine_protocol.py`):

- `test_provider_environment_leaves_no_configuration_behind_for_the_next_arm` — two arms in one
  process; asserts the second arm's entry environment is the pre-call one, and that a pre-existing
  ambient value is restored rather than dropped.
- `test_prepare_case_scopes_the_provider_environment_to_its_own_arms` — two arms passed through
  `prepare_case`; asserts every configuration entry point starts from the caller's environment and
  that the process environment is byte-identical afterwards.
- `test_provider_environment_is_cleared_then_set_exactly` (existing) now also asserts the ambient
  values are restored after the scope exits.

`configure_provider_environment` itself keeps its process-wide semantics — the SPINE CLIs are
processes whose scope *is* the arm, and silently turning the call into a no-op would be worse than
the leak — but its docstring now says that only a process-scoped caller may use it directly and that
everything sharing a process must use `provider_environment`.

Mutation checks in §6 confirm both new tests fail if the scoping is removed.

### 4.2 `tests/product_eval/conftest.py` — the backstop the frozen assets force

A new autouse fixture snapshots `os.environ` before each test in this directory and restores it
afterwards. Two reasons it is not optional:

1. `product_evals/spine_e2e_2/public_surface.py`, `spine_e2e_3/public_surface.py` and
   `spine_e2e_4/public_surface.py` carry **identical copies** of the leaking helper, and
   `tests/product_eval/test_spine_e2e_3_protocol.py:90` and `test_spine_e2e_4_protocol.py:68` call
   them directly. Those files are frozen assets: `test_spine_e2e_4_assets.py:207-236` requires every
   file directly under `product_evals/spine_e2e_{1,2,3}/` to be byte-identical to the commit that
   recorded the SPINE-E2E-3 result, and `test_spine_e2e_3_assets.py:95-137` binds a stored
   qualification receipt to `source_sha256["spine_identity.py"]`. Editing them was **tried and
   reverted**: it reddened `test_spine_e2e_3_assets.py::test_qualification_receipt_is_reproducible_without_legal_ledgers`
   and `test_spine_e2e_4_assets.py::test_e2e1_e2e2_e3_assets_remain_unchanged_since_e2e3_adjudication`.
2. The fixture therefore closes the leak that the frozen copies still contain, without touching a
   frozen byte. It was measured to change nothing else: with the fixture and without it, the tallies
   and the failing node ids are identical.

### 4.3 Measured effect of the isolation fix on the red suite

**119 → 119. The leak accounts for none of the currently failing tests.** Reported as measured, not
as hoped: the fix removes a latent ordering hazard (and the "an offline arm can be silently pointed
elsewhere" failure class) without changing today's tally.

### 4.4 A frozen-status contract that could never match (class **a**, small and clearly correct)

`open_application` in `product_evals/common/public_surface.py:138-153` compared
`AgentOSApplication.provider_status()` against a **five**-key literal, but the product reports six —
`apps/api_server/app.py:972-980` includes `model_revision_digest`. A dict of six keys is never equal
to a dict of five, so the check raised `RuntimeError("frozen provider status mismatch")` for *every*
correctly configured application:

```bash
uv run --extra product-test python -c "..."   # prints
# {'configured': True, 'provider_id': 'openai-compatible', 'model_id': 'spine-e2e-1-frozen',
#  'model_revision_digest': None, 'endpoint_class': 'openai-compatible',
#  'credential_ref_id': 'credential:default'}
```

Fix: the expected status in `product_evals/common/public_surface.py` now names
`"model_revision_digest": None` — the value the frozen arms really produce (they never set
`AGENT_OS_PROVIDER_MODEL_REVISION_DIGEST`), so a non-frozen digest from the operator's environment
still fails closed. Guarded by two new tests in `tests/product_eval/test_spine_protocol.py`:
`test_open_application_accepts_the_frozen_provider_status` and
`test_open_application_still_fails_closed_on_a_revision_digest`.

**This fix is necessary but not sufficient.** With the check repaired, the one test that drives a
real single case (`test_real_single_case_prepare_interrupt_and_immediate_probe`) now fails one layer
deeper, in bucket F.2 — `bound provider invocation requires an exact configuration snapshot`. So this
change removes a false refusal without turning the test green, and the tally is unchanged by it too.

`product_evals/spine_e2e_2/public_surface.py`, `spine_e2e_3/public_surface.py`,
`spine_e2e_4/public_surface.py` (both via `product_evals/common/spine_identity.py:113-120`) carry the
same stale five-key expectation. They were fixed and then **reverted** because those bytes are
frozen assets (§4.2). Their `open_application` is exercised only by their CLIs, never by a test
(the e2e_3/e2e_4 protocol tests monkeypatch `AgentOSApplication`), which is why they are red-free
today and why the same defect is still latent there.

## 5. Tallies after the fixes

| Suite / command | Before | After |
|---|---|---|
| `uv run --extra product-test pytest tests/product_eval -q` | 119 failed, 819 passed, 1 skipped | **119 failed, 823 passed, 1 skipped** (identical failing node ids) |
| `uv run --extra product-test pytest tests/product -q` | 2753 passed, 1 skipped | **2753 passed, 1 skipped** |
| `uv run --extra product-test ruff check apps packages/contracts/src packages/os_core/src tests/product` | clean | **All checks passed!** |
| `uv run --extra product-test ruff check product_evals tests/product_eval` (not a gate today; checked because this change touches those paths) | clean | **All checks passed!** |

The `tests/product_eval` tally is unchanged in its failures by design: §4.3 and §4.4 explain why the
two correctness fixes remove hazards and a false refusal without turning any currently failing test
green.

### 5.1 Why no test was given a skip

The brief allowed a narrow, explicitly justified skip for a test that genuinely cannot run without
an absent asset, with the repo's skip-budget discipline in mind (`tests/product` bounds its skips at
12 in CI, and the repo does use `pytest.mark.skipif` for platform prerequisites). No skip was added
here, deliberately:

- The two absent assets are not "absent on this machine". `ai-agent-engineering-workflow` has no
  worktree at that path and no branch or object for `50eb4d27…` at all, and no workflow in this
  repository pulls the pinned Docker image. A skip would therefore be **permanent**: it would turn
  109 instruments that currently say "I did not run" into 109 that say nothing, in a suite whose
  whole problem is that it says nothing.
- Skipping 109 of 943 items to make `pytest -q` print a green summary is exactly the "looks healthy"
  failure mode this task exists to remove, and it would exceed the repo's entire product-suite skip
  budget ninefold without a decision.
- Each of those 109 has a single, named, actionable precondition recorded in §3 A and §3 B (the
  exact commit, the exact image digest). The honest alternatives are to satisfy the precondition or
  to retire/re-pin the instrument under an explicit decision — not to silence it.

If the founder decides these instruments are dead, the change should delete or re-pin them and
record the decision; that is a route choice (root AGENTS.md §5, §7), not a test tweak.

## 6. Mutation checks (proving the guards bite)

Each mutation was applied to `product_evals/common/public_surface.py` on top of the final change,
run, and reverted (the file was restored from a byte copy — no `git stash`, which is shared across
worktrees).

1. **Isolation guard.** Restoring the original unscoped body of `prepare_case`
   (`configure_provider_environment` called directly, no per-arm scope, no outer restore) reddens
   `test_prepare_case_scopes_the_provider_environment_to_its_own_arms`:

   ```
   E       AssertionError: assert 2 == 3
   E        +  where 2 = len([{'SPINE_E2E_1_PROVIDER_KEY': None, 'AGENT_OS_PROVIDER_BASE_URL': None, ...
   ```
   (`tests/product_eval/test_spine_protocol.py` — file went from `2 failed, 92 passed` to
   `3 failed, 91 passed` with exactly that one new failure.)
2. **Scoped-restore guard.** Removing the `try/finally` from `provider_environment` reddens both
   isolation tests:
   `test_provider_environment_leaves_no_configuration_behind_for_the_next_arm` and
   `test_provider_environment_is_cleared_then_set_exactly` → `2 failed in 0.36s`. The
   `tests/product_eval/conftest.py` backstop does not mask this, because both assertions run inside
   a single test.
3. **Frozen-status guard.** Removing `"model_revision_digest": None` from the expected status reddens
   `test_open_application_accepts_the_frozen_provider_status` → `3 failed, 91 passed`.
4. **Frozen-asset guards (found by accident, kept as evidence).** Editing
   `product_evals/spine_e2e_2/public_surface.py`, `product_evals/spine_e2e_3/public_surface.py` and
   `product_evals/common/spine_identity.py` reddened
   `test_spine_e2e_4_assets.py::test_e2e1_e2e2_e3_assets_remain_unchanged_since_e2e3_adjudication` and
   `test_spine_e2e_3_assets.py::test_qualification_receipt_is_reproducible_without_formal_ledgers`.
   The edits were reverted; this is why §4.2 exists in its present shape.

## 7. CI visibility: what was done, and why the directory is still not gated

**No CI step was added.** The directory cannot be gated green on arrival, and adding a step that is
red on arrival is worse than no step.

Measured state after the fixes: 119 failures, of which

- 109 (buckets A + B) need an absent asset — a cross-repo worktree at a commit that no longer exists
  anywhere reachable, and a Docker daemon plus a pinned image that is not pulled;
- 8 (buckets C, D, F) are frozen instruments failing closed against product/contract drift that only
  a founder decision can resolve (re-cut a pre-registered artefact, change the workflow schema
  version, restore the generic tool wire format, or delete another workstream's 2026-07-13 artefacts);
- 2 (buckets E, F.2) are genuine defects whose repair is a design change, not a test edit.

The specific blockers, in the order they would have to be cleared:

1. Re-pin or retire the runner-contract instruments (82 tests). They need
   `ai-agent-engineering-workflow/.worktrees/team-event-contract-v1-20260713` at
   `50eb4d27b17688f0943f80207dddb702983afd51`; that commit is unreachable, and re-creating the
   worktree writes into a sibling repository, which needs an explicit cross-repo ADR.
2. Docker provisioning (27 tests): a daemon in CI plus a pre-pull of
   `python@sha256:423ed6ab25b1921a477529254bfeeabf5855151dc2c3141699a1bfc852199fbf` (the pinned
   digest in `product_evals/srl_e2e_falsifier/docker_exec.py:37-42`). GitHub's `ubuntu-latest` has a
   daemon but the workflow never pulls the image, so the same 27 would be red there.
3. Four founder-level frozen-artifact decisions (§3 C, §3 F).
4. A public way for an eval instrument to install a scripted provider (§3 E).

A defensible next step — but one that needs an explicit decision, because it freezes debt rather
than removing it — is an enumerated known-failure inventory in CI (run the whole directory; fail if
any failing node id is not in the checked-in list; bound the list's size; keep the existing
collection floor and file-set pattern from `tests/product`). That makes the suite visible and
regression-guarded without pretending it is green. It was **not** added here: it would enshrine 119
known failures in the repository's gate without the founder's authorization, and the brief's
instruction for this case is to say so plainly instead.

## 8. Not done / open

- The three frozen sibling copies of the leaking helper
  (`product_evals/spine_e2e_2/public_surface.py:88`, `spine_e2e_3/public_surface.py:89`,
  `spine_e2e_4/public_surface.py:89`) are still unscoped; the `tests/product_eval/conftest.py`
  fixture contains them but does not remove the defect. Closing it properly needs the frozen-asset
  re-cut decision (§4.2).
- The stale five-key `expected_provider_status()` in those same frozen modules is still stale (§4.4).
- Every bucket in §3 other than §4.1/§4.4 is left for a separate, explicitly-authorized change, with
  its root cause, file:line and reproducer recorded above.
- `~/.agent-os/` was not read or written; no daemon was started
  (`pgrep -f 'python -m apps\.runtime_daemon'` is empty); no fixed port was bound — the stub servers
  in this suite bind port 0.
