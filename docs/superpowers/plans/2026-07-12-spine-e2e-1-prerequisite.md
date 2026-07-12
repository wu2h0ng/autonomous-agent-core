# SPINE-E2E-1 Fresh Prerequisite Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build, preregister, freeze, and run a fresh Product Track instrument-validity evaluation proving the current Agent OS spine binds Goal-to-verified-outcome execution, avoids duplicate logical side effects after a real worker restart, and rehydrates to the same terminal projection as an uninterrupted twin.

**Architecture:** Add a standalone `product_evals` harness that drives only `AgentOSApplication` public methods and a frozen local OpenAI-compatible response bank. The harness writes mutable run state only below `.agent_runs/spine-e2e-1-20260712/evaluation`, uses separate SQLite/workspace directories per case and arm, and exposes `prepare`, `resume`, and `adjudicate` process phases. The tracked preregistration freezes the harness, corpus, provider bank, evaluator, and Product runtime files; it does not convert Product evidence into an autonomy claim.

**Tech Stack:** Python 3.11+, stdlib HTTP/SQLite/hashlib/json/statistics, Pydantic contracts already in the monorepo, `AgentOSApplication`, pytest 9, Ruff, Pyright, fixed workflow runner commit `0c87fb3`.

## Global Constraints

- Track is `product_eval`; claim class is `deployment-product`; actual target repo is `autonomous-agent-core`.
- The result is Product instrument evidence only; it is not `LH-RECOVERY-1`, autonomy, AGI, continual learning, or production 7x24 evidence.
- All Agent OS execution uses only `AgentOSApplication` public methods. Harness source must not access `.store`, `.tasks`, `.sandbox`, `.provider`, or `.provider_configured`.
- Provider behavior is a frozen model-response bank served through local HTTP. Unknown prompt digests fail closed; this does not claim live-provider robustness.
- Freeze occurs only from a clean committed Product worktree. Mutable outputs stay under `.agent_runs/spine-e2e-1-20260712/evaluation`.
- SPINE uses 12 frozen cases: four task families with three cases each. Every case has an uninterrupted twin and a post-apply worker-interruption run.
- A stale worker lease is recovered only after at least 360 real seconds. No virtual clock may satisfy the r-final recovery gate.
- Any policy/correction violation, unbound accepted outcome, duplicate logical apply receipt, target/spec/provider/evaluator drift, or private-runtime harness call makes the result `INVALID`.
- Tests precede implementation, and every task ends in a scoped commit on the isolated feature branch.

---

## File Structure

- `product_evals/__init__.py`: marks the tracked Product evaluation package.
- `product_evals/common/artifacts.py`: frozen JSON/hash loading, append-only phase ledger, atomic result writes.
- `product_evals/common/provider_bank.py`: local OpenAI-compatible frozen-response server.
- `product_evals/common/public_surface.py`: public `AgentOSApplication` construction and public event projection helpers.
- `product_evals/spine_e2e_1/protocol.py`: case contracts, workflow construction, prepare/resume/adjudication logic.
- `product_evals/spine_e2e_1/cli.py`: `prepare`, `resume`, and `adjudicate` CLI.
- `product_evals/spine_e2e_1/frozen_cases.json`: 12 held-out Product cases.
- `product_evals/spine_e2e_1/provider_responses.json`: exact prompt-digest response bank.
- `tests/product_eval/test_common_integrity.py`: fail-closed artifact and phase-ledger tests.
- `tests/product_eval/test_provider_bank.py`: known/unknown prompt behavior.
- `tests/product_eval/test_spine_protocol.py`: public-surface, restart, duplicate-effect, evidence-binding, and adjudication tests.
- `tests/product_eval/test_spine_cli.py`: fresh-process phase and real-time guard tests.
- `docs/research/SPINE-E2E-1-preregistration-spec.yaml`: exact preregistration and mechanism file list.
- `.agent_runs/spine-e2e-1-20260712/evaluation/*`: mutable raw/result artifacts; never committed as mechanism inputs.

### Task 1: Shared Frozen-Artifact and Phase-Ledger Kernel

**Files:**
- Create: `product_evals/__init__.py`
- Create: `product_evals/common/__init__.py`
- Create: `product_evals/common/artifacts.py`
- Test: `tests/product_eval/test_common_integrity.py`

**Interfaces:**
- Consumes: filesystem paths and canonical JSON objects.
- Produces: `sha256_file(path: Path) -> str`, `load_frozen_json(path: Path, expected_sha256: str) -> object`, `append_phase(path: Path, record: PhaseRecord) -> None`, `read_phases(path: Path) -> tuple[PhaseRecord, ...]`, and `write_json_atomic(path: Path, value: object) -> None`.

- [ ] **Step 1: Write the failing integrity tests**

```python
def test_frozen_json_rejects_digest_drift(tmp_path: Path) -> None:
    path = tmp_path / "bank.json"
    path.write_text('{"version":1}\n', encoding="utf-8")
    digest = sha256_file(path)
    path.write_text('{"version":2}\n', encoding="utf-8")
    with pytest.raises(IntegrityError, match="digest"):
        load_frozen_json(path, digest)


def test_phase_ledger_rejects_non_monotonic_or_rewritten_phase(tmp_path: Path) -> None:
    ledger = tmp_path / "phase_ledger.jsonl"
    append_phase(ledger, PhaseRecord(phase="prepare", ordinal=1, utc="2026-07-12T00:00:00Z"))
    with pytest.raises(IntegrityError, match="ordinal"):
        append_phase(ledger, PhaseRecord(phase="prepare", ordinal=1, utc="2026-07-12T00:00:01Z"))
```

- [ ] **Step 2: Run the tests and observe RED**

Run: `uv run --extra product-test pytest tests/product_eval/test_common_integrity.py -q`

Expected: collection fails because `product_evals.common.artifacts` does not exist.

- [ ] **Step 3: Implement the immutable interfaces**

```python
@dataclass(frozen=True)
class PhaseRecord:
    phase: str
    ordinal: int
    utc: str
    payload_sha256: str = ""


class IntegrityError(RuntimeError):
    pass


def load_frozen_json(path: Path, expected_sha256: str) -> object:
    actual = sha256_file(path)
    if actual != expected_sha256:
        raise IntegrityError(f"digest mismatch for {path}: {actual} != {expected_sha256}")
    return json.loads(path.read_text(encoding="utf-8"))
```

`append_phase` must parse every existing line, require `ordinal == previous.ordinal + 1`, reject an already-recorded phase name, append one canonical JSON line with `os.open(..., O_APPEND)`, flush, and `os.fsync`. `write_json_atomic` must write canonical sorted JSON to a same-directory temporary file, fsync, then `os.replace`.

- [ ] **Step 4: Run tests and commit**

Run: `uv run --extra product-test pytest tests/product_eval/test_common_integrity.py -q`

Expected: all tests pass.

```bash
git add product_evals/__init__.py product_evals/common tests/product_eval/test_common_integrity.py
git commit -m "feat(product-eval): add frozen artifact kernel"
```

### Task 2: Frozen OpenAI-Compatible Provider Bank

**Files:**
- Create: `product_evals/common/provider_bank.py`
- Create: `product_evals/spine_e2e_1/frozen_cases.json`
- Create: `product_evals/spine_e2e_1/provider_responses.json`
- Test: `tests/product_eval/test_provider_bank.py`

**Interfaces:**
- Consumes: exact OpenAI chat-completions request bodies and the tracked response bank.
- Produces: `prompt_digest(body: dict[str, object]) -> str` and `FrozenProviderServer(bank_path: Path)` with `.base_url` and context-manager lifecycle.

- [ ] **Step 1: Write known/unknown prompt tests**

```python
def test_known_prompt_returns_one_apply_patch_tool_call(bank_path: Path) -> None:
    with FrozenProviderServer(bank_path) as server:
        response = post_chat(server.base_url, frozen_known_request())
    tool = response["choices"][0]["message"]["tool_calls"][0]
    assert tool["function"]["name"] == "workspace__apply_patch"


def test_unknown_prompt_fails_closed(bank_path: Path) -> None:
    with FrozenProviderServer(bank_path) as server:
        with pytest.raises(HTTPError) as exc:
            post_chat(server.base_url, {"messages": [{"role": "user", "content": "unknown"}]})
    assert exc.value.code == 422
```

- [ ] **Step 2: Run RED**

Run: `uv run --extra product-test pytest tests/product_eval/test_provider_bank.py -q`

Expected: import failure for `FrozenProviderServer`.

- [ ] **Step 3: Implement the server and frozen corpus**

The bank schema is exact and versioned:

```json
{
  "version": 1,
  "responses": {
    "<sha256-of-user-prompt>": {
      "path": "cases/string-01/subject.py",
      "content": "<complete replacement content>",
      "prompt_tokens": 128,
      "completion_tokens": 64
    }
  }
}
```

The handler must accept only `POST /v1/chat/completions` and `/chat/completions`, require one user message, hash the exact user `content`, reject missing/unknown digests with 422, and return exactly one `workspace__apply_patch` tool call. It must never synthesize a response at runtime.

The 12 cases must contain `case_id`, `family`, `target_path`, `goal`, `initial_content`, `patched_content`, and `pytest_source`. Families are `string_transform`, `numeric_reducer`, `validator`, and `formatter`, with three distinct cases each.

- [ ] **Step 4: Run tests and commit**

Run: `uv run --extra product-test pytest tests/product_eval/test_provider_bank.py -q`

Expected: all tests pass and unknown prompts return 422.

```bash
git add product_evals/common/provider_bank.py product_evals/spine_e2e_1 tests/product_eval/test_provider_bank.py
git commit -m "feat(product-eval): freeze SPINE provider corpus"
```

### Task 3: Public-Surface SPINE Prepare and Resume Protocol

**Files:**
- Create: `product_evals/common/public_surface.py`
- Create: `product_evals/spine_e2e_1/__init__.py`
- Create: `product_evals/spine_e2e_1/protocol.py`
- Test: `tests/product_eval/test_spine_protocol.py`

**Interfaces:**
- Consumes: `AgentOSApplication`, frozen case/bank paths, and an evaluation root.
- Produces: `prepare_spine(config: SpineConfig) -> Path`, `resume_spine(config: SpineConfig) -> Path`, `project_public_task(app: AgentOSApplication, task_id: str) -> PublicTaskProjection`, and `build_spine_workflow(case: SpineCase, now: datetime) -> WorkflowGraph`.

- [ ] **Step 1: Write public-surface and restart tests**

```python
def test_harness_source_does_not_use_private_application_organs() -> None:
    source = Path("product_evals/spine_e2e_1/protocol.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    forbidden = {"store", "tasks", "sandbox", "provider", "provider_configured"}
    assert not [node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute) and node.attr in forbidden]


def test_prepare_creates_uninterrupted_and_interrupted_public_tasks(tmp_path: Path) -> None:
    state = prepare_spine(test_config(tmp_path, allow_short_timing=True))
    payload = json.loads(state.read_text(encoding="utf-8"))
    assert len(payload["cases"]) == 12
    assert all(item["interrupted"]["phase"] == "POST_APPLY_INTERRUPTED" for item in payload["cases"])
    assert all(item["uninterrupted"]["outcome"] == "VERIFIED" for item in payload["cases"])
```

- [ ] **Step 2: Run RED**

Run: `uv run --extra product-test pytest tests/product_eval/test_spine_protocol.py -q`

Expected: missing protocol imports.

- [ ] **Step 3: Implement the public protocol**

`build_spine_workflow` must build exactly:

```text
read -> provider -> approve -> apply -> tests -> evaluate -> done
```

`prepare_spine` must, for every case:

1. create isolated `uninterrupted/` and `interrupted/` workspaces and SQLite files;
2. start `FrozenProviderServer`, set provider environment before each `AgentOSApplication` construction, and call only `create_task`, `commit_task`, `run_task`, `record_approval`, `task_json`, `evidence_json`, and `recovery_json`;
3. complete the uninterrupted twin to `VERIFIED`;
4. run the interrupted twin to approval, record approval, call `run_task(..., stop_after_node="apply")`, require `WorkerInterrupted`, and exit that application scope;
5. persist task IDs, paths, timestamps, frozen digests, and public projections with `write_json_atomic`.

`resume_spine` must reject elapsed time below `min_stale_lease_seconds` (360 in r-final), construct a fresh application against the same DB/workspace, call `run_task(..., recover_stale_lease=True)`, call it once more to prove terminal replay adds no apply receipt, and persist the final public projection.

- [ ] **Step 4: Run tests and commit**

Run: `uv run --extra product-test pytest tests/product_eval/test_spine_protocol.py -q`

Expected: all tests pass in short-timing test mode; production config still freezes 360 seconds.

```bash
git add product_evals/common/public_surface.py product_evals/spine_e2e_1/protocol.py tests/product_eval/test_spine_protocol.py
git commit -m "feat(product-eval): add public SPINE recovery protocol"
```

### Task 4: SPINE Baselines and Mechanical Adjudicator

**Files:**
- Modify: `product_evals/spine_e2e_1/protocol.py`
- Test: `tests/product_eval/test_spine_protocol.py`

**Interfaces:**
- Consumes: public task/evidence projections and baseline traces.
- Produces: `adjudicate_spine(config: SpineConfig) -> dict[str, object]` with verdict `PASS`, `NOT_PASS`, or `INVALID`.

- [ ] **Step 1: Write adjudication tests**

```python
def test_duplicate_apply_receipt_forces_invalid() -> None:
    raw = valid_spine_raw()
    raw["cases"][0]["interrupted"]["apply_receipts"].append(
        raw["cases"][0]["interrupted"]["apply_receipts"][0]
    )
    assert adjudicate_raw(raw)["verdict"] == "INVALID"


def test_terminal_projection_mismatch_is_not_pass() -> None:
    raw = valid_spine_raw()
    raw["cases"][0]["interrupted"]["final_file_sha256"] = "0" * 64
    assert adjudicate_raw(raw)["verdict"] == "NOT_PASS"
```

- [ ] **Step 2: Run RED**

Run: `uv run --extra product-test pytest tests/product_eval/test_spine_protocol.py -q`

Expected: `adjudicate_raw` is absent.

- [ ] **Step 3: Implement exact gates**

The adjudicator must mechanically enforce:

```python
invalid = any((digest_drift, missing_case, private_call, severe_policy_violation))
passed = (
    verified_outcomes == 12
    and rehydrated_equivalent == 12
    and duplicate_logical_apply_receipts == 0
    and every_outcome_has_expected_evaluator_and_evidence
)
verdict = "INVALID" if invalid else "PASS" if passed else "NOT_PASS"
```

Also emit contextual baselines:

- `direct_model_tools`: same frozen response and pytest, no event spine; a post-write restart replays the write and records duplicate work.
- `single_process`: same Product graph without injected process death; it is not credited with recovery evidence.

No baseline result may relax the absolute SPINE gates.

- [ ] **Step 4: Run tests and commit**

Run: `uv run --extra product-test pytest tests/product_eval/test_spine_protocol.py -q`

Expected: forced invalidity and NOT_PASS tests pass.

```bash
git add product_evals/spine_e2e_1/protocol.py tests/product_eval/test_spine_protocol.py
git commit -m "feat(product-eval): add SPINE mechanical adjudication"
```

### Task 5: Phase CLI, Preregistration, Review, Freeze, and Fresh Run

**Files:**
- Create: `product_evals/spine_e2e_1/cli.py`
- Create: `tests/product_eval/test_spine_cli.py`
- Create: `docs/research/SPINE-E2E-1-preregistration-spec.yaml`
- Create after the run: `docs/research/SPINE-E2E-1-result.md`

**Interfaces:**
- Consumes: tracked protocol/corpus and workflow-runner prereg gates.
- Produces: `python -m product_evals.spine_e2e_1.cli {prepare,resume,adjudicate}` and a frozen result artifact.

- [ ] **Step 1: Write CLI phase-guard tests**

```python
def test_resume_before_real_lease_window_is_denied(tmp_path: Path) -> None:
    result = run_cli("resume", tmp_path, now_utc="2026-07-12T00:05:59Z")
    assert result.returncode == 2
    assert "360" in result.stderr


def test_adjudicate_requires_prepare_and_resume(tmp_path: Path) -> None:
    result = run_cli("adjudicate", tmp_path)
    assert result.returncode == 2
    assert "phase" in result.stderr.lower()
```

- [ ] **Step 2: Run RED, implement argparse CLI, and run GREEN**

Run: `uv run --extra product-test pytest tests/product_eval/test_spine_cli.py -q`

Expected before implementation: missing module. Expected after implementation: all tests pass.

CLI commands must require `--run-dir`, `--target-head`, `--spec-sha256`, `--cases-sha256`, and `--provider-bank-sha256`; every phase rechecks all digests and the Git HEAD.

- [ ] **Step 3: Write and self-check the preregistration spec**

The YAML must freeze:

- ProductFailureRef and bounded Product claim;
- 12 exact case IDs and their corpus digest;
- provider bank/evaluator digests;
- the two baselines;
- 360-second real stale-lease window;
- PASS/NOT_PASS/INVALID rules above;
- `builder_id: claude-builder`;
- every `product_evals/**/*.py`, corpus JSON, `apps/api_server/app.py`, Developer Agent domain pack, and every Product contract/runtime `.py` file in `mechanism.files`.

Run: `rg -n "TBD|TODO|post-hoc|autonomy proved" docs/research/SPINE-E2E-1-preregistration-spec.yaml`

Expected: no placeholder or overclaim match.

- [ ] **Step 4: Commit the exact freeze candidate**

```bash
git add product_evals tests/product_eval docs/research/SPINE-E2E-1-preregistration-spec.yaml
git commit -m "test(product-eval): preregister fresh SPINE-E2E-1"
git status --porcelain
```

Expected: clean output.

- [ ] **Step 5: Execute RR-0031, exact-content review, and freeze with the fixed runner**

Use `PYTHONPATH=/Users/mima1234/Documents/AI-Agent-Projects/ai-agent-engineering-workflow/.worktrees/lh-prereg-target-fix-20260712/src` and run the already-created `spine-e2e-1-20260712` packet through:

```text
context-calibration blind verify
-> bounded delta review and verify
-> prereg manifest-verify
-> prereg review (OpenCode content reviewer)
-> prereg architecture-review (independent calibrated reviewer)
-> prereg freeze --frozen-by codex-cto
```

Record the lock SHA-256 immediately. Any review or digest failure stops the task; do not edit the frozen gate to rescue it.

- [ ] **Step 6: Run fresh phases and adjudicate**

```bash
python -m product_evals.spine_e2e_1.cli prepare --run-dir "$ROOT/.agent_runs/spine-e2e-1-20260712/evaluation" ...
# wait until the frozen real 360-second lease window expires
python -m product_evals.spine_e2e_1.cli resume --run-dir "$ROOT/.agent_runs/spine-e2e-1-20260712/evaluation" ...
python -m product_evals.spine_e2e_1.cli adjudicate --run-dir "$ROOT/.agent_runs/spine-e2e-1-20260712/evaluation" ...
```

Expected: a mechanically generated `result.json`. `PASS` unlocks final LH preregistration; `NOT_PASS` or `INVALID` keeps LH blocked.

- [ ] **Step 7: Independent result review and truth update**

Run workflow-runner `prereg verify --result` before any documentation commit. Then create `docs/research/SPINE-E2E-1-result.md` from the immutable result hashes, update the smallest authoritative truth set, and commit without changing the frozen raw artifacts.

```bash
git add docs/research/SPINE-E2E-1-result.md docs/CURRENT_STATE.yaml codebase_index.md
git commit -m "docs(product-eval): record SPINE-E2E-1 result"
```

