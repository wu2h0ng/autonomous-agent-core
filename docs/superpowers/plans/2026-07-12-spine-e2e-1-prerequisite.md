# SPINE-E2E-1 Fresh Prerequisite Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build, preregister, freeze, and run a fresh Product Track instrument-validity evaluation showing that the current public Agent OS spine can bind one Goal-to-verified-outcome path, survive an injected post-apply `WorkerInterrupted` followed by an actual process exit, naturally reacquire the expired SQLite lease in a fresh process, avoid a duplicate logical apply receipt, and converge to the same normalized terminal projection as an uninterrupted twin. This does not test arbitrary SIGKILL, power loss, or uncontrolled machine crash.

**Architecture:** Add a standalone `product_evals` harness which drives only public `AgentOSApplication` methods and a complete frozen OpenAI-compatible request/response bank. Twelve cases each run an uninterrupted arm and a post-apply-interrupted arm with separate file-backed SQLite databases and workspaces. Production phases are separate CLI processes. A context-bound, hash-chained phase ledger samples the local monotonic clock and host/boot identity internally; a phase-wide lock records each phase start before Product side effects and completion after write-once payload persistence. The 360-second claim is explicitly `NATURAL_EXPIRY_REACQUIRE`, not forced stale-worker takeover.

**Tech Stack:** Python 3.11+, stdlib HTTP/SQLite/hashlib/json/fcntl/time/subprocess, existing Pydantic Product contracts, `AgentOSApplication`, pytest 9, Ruff, Pyright, fixed workflow-runner commit `804c8d54bf5b78d9d850edb452db4affe3c1cd22` from branch `codex/agent-os-product-prereg-target-20260712` in `/Users/mima1234/Documents/AI-Agent-Projects/ai-agent-engineering-workflow/.worktrees/lh-prereg-target-fix-20260712`.

## Claim and Trust Boundary

- Track: `product_eval`; claim class: `deployment-product`; target repo: `autonomous-agent-core`.
- Maximum claim: run-local, single-host, same-boot, local SQLite and single-workspace Product instrument evidence for one frozen provider-response path.
- This is not `LH-RECOVERY-1`, hierarchical planning, live-provider robustness, 7x24 operation, autonomy, continual learning, self-evolution, or AGI evidence.
- Timing evidence level is `local_same_boot_monotonic_self_attestation_v1`. It does not resist malicious root/kernel/hypervisor/VM snapshot, a compromised Python clock, or coordinated rewriting of every local ledger. It is not an external timestamp or remote attestation.
- Product execution may call only public `AgentOSApplication` methods. Harness source must not access `.store`, `.tasks`, `.sandbox`, `.provider`, `.provider_configured`, or other private composition organs.
- Implementation runs in this isolated `codex/lh-recovery-1-20260712` worktree from the clean plan-only commit. RED means the new tests fail because the planned files/behavior are absent at that exact HEAD; historical commit `909c1c1` is not an execution authority.
- Provider behavior is a frozen full-request/full-response replay. Any request body drift or unknown digest fails closed; the server never synthesizes a response at runtime.
- Product-eval mutable payloads remain below `.agent_runs/spine-e2e-1-20260712/evaluation`; runner governance truth (`prereg.lock`, approval ledgers, and `agent_events.jsonl`) remains in the same run root under runner ownership. Tracked mechanism files and frozen corpora remain immutable after preregistration.
- Lease semantics are frozen as `NATURAL_EXPIRY_REACQUIRE`: the existing typed `WorkerInterrupted` path escapes the node loop before every normal/failure lease-release site, so `stop_after_node="apply"` leaves the production 300-second lease active. A fresh-process probe within 60 seconds must be denied, and resume after at least 360 seconds calls `recover_stale_lease=False`. This direct-local simulation hook is not exposed through HTTP/server routes; the frozen harness permits only the literal node `apply`, and AST tests reject caller-selected nodes or propagation into external APIs.
- A duplicate logical apply receipt, accepted outcome without bound evidence, private-runtime access, provider/spec/corpus/target drift, phase/context/boot/runner-anchor mismatch, unexpected policy/correction event, or incomplete phase makes the run `INVALID`. Ordinary Product failure with intact instrumentation is `NOT_PASS`.

## File Structure

- `product_evals/__init__.py`
- `product_evals/common/artifacts.py`: frozen JSON, strict hashes, local clock/identity sampling, context-bound phase ledger, phase-wide lock, atomic and write-once JSON.
- `product_evals/common/provider_bank.py`: exact canonical request matching and verbatim frozen response replay.
- `product_evals/common/public_surface.py`: public application construction and normalized public projections.
- `product_evals/spine_e2e_1/protocol.py`: case contracts, exact workflow/outcome construction, prepare/probe/resume/adjudication logic.
- `product_evals/spine_e2e_1/cli.py`: `prepare`, `interrupt-batch`, `probe-active-lease`, `resume`, `adjudicate`, and `finalize-result` commands.
- `product_evals/spine_e2e_1/coordinator.py`: frozen subprocess-only `interrupt-batch -> runner anchor -> probe-active-lease -> runner anchor` launcher; it imports no workflow-runner or Product-private module.
- `product_evals/spine_e2e_1/frozen_cases.json`: 12 Product cases.
- `product_evals/spine_e2e_1/provider_responses.json`: complete request and response objects.
- `tests/product_eval/*`: integrity, provider, protocol, and CLI tests.
- `docs/research/SPINE-E2E-1-preregistration-spec.yaml`: frozen spec and mechanism list.
- `.agent_runs/spine-e2e-1-20260712/evaluation/*`: mutable/write-once run evidence, never a mechanism input.

### Task 1: Shared Frozen-Artifact and Phase-Evidence Kernel

**Files:**
- Create: `product_evals/__init__.py`
- Create: `product_evals/common/__init__.py`
- Create: `product_evals/common/artifacts.py`
- Test: `tests/product_eval/test_common_integrity.py`

**Required interfaces:**

```python
sha256_file(path: Path) -> str
canonical_sha256(value: object) -> str
load_frozen_json(path: Path, expected_sha256: str) -> object
phase_context_sha256(bindings: Mapping[str, str]) -> str
read_phases(path: Path, expected_context_sha256: str) -> tuple[PhaseRecord, ...]
phase_guard(..., expected_context_sha256: str,
            elapsed_gates: tuple[ElapsedGate, ...] = ()) -> PhaseGuard
write_json_atomic(path: Path, value: object) -> None
write_json_once(path: Path, value: object) -> str
```

`PhaseRecord` fields are exact and runtime-validated: `schema_version`, `phase`, derived `ordinal`, `payload_sha256`, `chain_context_sha256`, a nested internally-derived `ClockSample`, `previous_record_sha256`, and `record_sha256`. `ClockSample` contains `mono_before_ns`, `utc_ns`, `mono_after_ns`, monotonic clock implementation/adjustability/resolution, and context-salted 64-hex host/boot hashes.

`chain_context_sha256` is the canonical digest of exact `schema`, `experiment_id`, `run_id`, target HEAD, prereg spec and lock digests, mechanism manifest, corpus, provider bank, evaluator, the workflow-runner common-dir binding and exact HEAD `804c8d54bf5b78d9d850edb452db4affe3c1cd22`, plus canonical digests of the preapproved `team.event.record` request and approval rows. Genesis is `H("agent-os-phase-ledger-v1\0" || context_digest)`. The Task 1 common kernel validates exact bindings and ledger consistency for a supplied expected digest; it does not claim provenance authority before the frozen run layout and runner rows exist. Task 5 owns the sole production resolver: it derives the expected context from the fixed run root, frozen target, `prereg.lock`, frozen spec/manifest/corpora, and exact runner ledger rows, then passes that digest to the common kernel. CLI digest/path arguments may only repeat resolver-derived values for equality checking and can never become an authority source or initialize a different context. Before every runner invocation, the fixed worktree must be clean and its source path, common-dir, branch, and `git rev-parse HEAD` must match these frozen values; ambient runner HEAD `bb3337f` or any other checkout is rejected. A process-global registry populated by calling `phase_context_sha256` is forbidden because it would confuse caller construction with provenance verification.

Phase names and ordinals are a frozen closed map. For phase `p`, `p_started` uses `H("SPINE-PENDING-v1\0" || p || context_digest)` as its pending payload digest. A successful terminal record `p_completed` binds the write-once payload digest. A caught protocol failure writes an exact write-once `{schema_version, phase, error_code}` payload and `p_failed` binds its digest; free-form exception text is never a gate input. `p_started` without a terminal record and every `p_failed` are terminal `INVALID_PARTIAL_PHASE`; neither may be retried or followed by another Product phase. Started and its mutually exclusive completed/failed terminal occupy the two frozen ordinals for that phase.

Darwin identity uses `kern.bootsessionuuid` and `IOPlatformUUID`; Linux uses `/proc/sys/kernel/random/boot_id` and `/etc/machine-id`. Raw identifiers are never persisted or logged. Missing/invalid/platform-unsupported identity is fail-closed; UTC is never a fallback for passing a gate.

- [ ] **Step 1: Write failing integrity and timing tests**

Tests must fail against the clean plan-only commit produced from this worktree and detect all of:

- frozen JSON TOCTOU and malformed JSON;
- caller-forged timestamps and any public clock/threshold injection;
- ledger transplant under a different run/prereg context;
- boot/host mismatch and clock implementation/rollback drift;
- non-exact schema, bool-as-int, non-positive or non-integer UTC nanoseconds, invalid/non-lowercase digests, blank lines, and a non-newline-terminated ledger;
- damaged ordinals, duplicate phases, chain/content tampering;
- shared reader lock and exclusive writer lock across the complete critical section;
- two-writer contention and a reader blocked from observing an in-flight short append;
- short writes, zero writes, and rollback to the original length after a recoverable append failure;
- file and parent-directory fsync using the correct descriptor type;
- `write_json_once` refusing overwrite with `O_EXCL` and `write_json_atomic` using same-directory replace;
- phase-wide nonblocking lock, zero mutation when a time gate is early, `phase_started` before yielded side effects, and terminal incomplete/failed phase handling.
- fixed lock acquisition order `phase.lock -> ledger lock`; parent-directory fsync on first creation, atomic replace, failed-append rollback/truncate, and cleanup/unlink paths;
- exact context-binding schema and deterministic digest construction, without a caller-populated process-global authorization registry. Production path/digest and runner-row provenance rejection is exercised by the Task 5 resolver tests after those frozen sources exist.

- [ ] **Step 2: Run RED**

Run: `uv run --extra product-test pytest tests/product_eval/test_common_integrity.py -q`

Expected: the new counterexample tests fail because `product_evals/common/artifacts.py` and its required behavior do not yet exist at the plan-only commit.

- [ ] **Step 3: Implement the smallest hardened kernel**

The clock sample must be taken internally as `mono_before = time.monotonic_ns(); utc = time.time_ns(); mono_after = time.monotonic_ns()`. Conservative elapsed lower bound is `current.mono_before_ns - anchor.mono_after_ns`; conservative elapsed upper bound is `current.mono_after_ns - anchor.mono_before_ns`. Minimum gates use the lower bound and maximum gates use the upper bound. Callers supply phase identity and payload digest only, never time/boot/derived hashes.

`phase_guard` holds an independent phase lock for the full command and always acquires it before the ledger lock. It validates chain/context/boot and every `ElapsedGate`, checks all lower/upper bounds before side effects, appends+fsyncs `<phase>_started`, then yields. Before completion it samples again and rechecks every maximum bound, so a 60-second probe gate covers the last denial rather than only phase entry. Completion requires a write-once payload digest and appends `<phase>_completed`; a classified failure writes the frozen failure payload and `<phase>_failed`. A crash between started and terminal is `INVALID_PARTIAL_PHASE` and cannot be silently retried.

- [ ] **Step 4: Verify and commit**

```bash
uv run --extra product-test pytest tests/product_eval/test_common_integrity.py -q
uv run --extra product-test ruff check product_evals/common/artifacts.py tests/product_eval/test_common_integrity.py
uv run --extra product-test ruff format --check product_evals/common/artifacts.py tests/product_eval/test_common_integrity.py
git diff --check
git add product_evals/__init__.py product_evals/common tests/product_eval/test_common_integrity.py
git commit -m "fix(product-eval): bind SPINE phase evidence"
```

### Task 2: Frozen Full-Wire OpenAI-Compatible Provider Bank

**Files:**
- Create: `product_evals/common/provider_bank.py`
- Create: `product_evals/spine_e2e_1/frozen_cases.json`
- Create: `product_evals/spine_e2e_1/provider_responses.json`
- Test: `tests/product_eval/test_provider_bank.py`

**Interfaces:** `request_body_digest(body: Mapping[str, object]) -> str` and `FrozenProviderServer(bank_path: Path)` with `.base_url` ending in `/v1`.

- [ ] **Step 1: Write RED tests**

Tests require only `POST /v1/chat/completions`, semantic `Content-Type: application/json`, and the frozen local dummy bearer credential; reject every other method/path or semantic auth/content header contract. Transport-generated `Host`, `Content-Length`, `User-Agent`, `Accept-Encoding`, and `Connection` headers are explicitly ignored/normalized rather than frozen across Python/platform versions. A known complete canonical request returns the stored response JSON object verbatim after decoding. Prompt, model, temperature, tool schema, `tool_choice`, or required semantic header drift each fails closed. Duplicate request-digest keys inside the frozen bank are rejected; a known case digest is allowed exactly its frozen `expected_calls=2` across the two arms, while a third call, an unknown digest, or a call-count mismatch is rejected/`INVALID`. No raw-byte identity claim is made after JSON decoding.

The frozen request is the exact body emitted by `OpenAICompatibleProvider`: fixed model `spine-e2e-1-frozen`, one exact execution prompt, temperature `0.0`, the `workspace__apply_patch` tool schema, and `tool_choice="auto"`. The frozen response contains exactly one tool call whose `function.arguments` is a JSON string with exactly `path` and `content`, plus integer usage fields and `finish_reason="tool_calls"`.

- [ ] **Step 2: Run RED**

Run: `uv run --extra product-test pytest tests/product_eval/test_provider_bank.py -q`

- [ ] **Step 3: Implement corpus and verbatim replay**

Bank schema stores `case_id`, the complete `request`, its digest, `expected_calls=2`, and the complete `response`; runtime handler performs strict canonical matching, records accepted and rejected attempts in a context-bound append-only/hash-chained run-local call ledger shared across phase processes, and returns the stored response without constructing tool calls. The ledger uses the same short-write/rollback discipline, exclusive lock, file and parent-directory fsync, and exact schema validation as the phase ledger. Every phase payload binds its call-ledger head and file SHA. Finalization replays it and requires exactly 24 accepted prepare calls, zero accepted calls in interrupt/probe/resume, the frozen rejected-attempt accounting, and no missing/truncated record.

Each of four families (`string_transform`, `numeric_reducer`, `validator`, `formatter`) has three distinct cases with `case_id`, `family`, `goal`, `target_path="subject.py"`, `test_path="test_subject.py"`, `initial_content`, `patched_content`, and `pytest_source`. Paths must be safe relative workspace paths. Goal/Workflow/Commitment times are not caller inputs: `prepare` derives one internally sampled contract time and shares it across both arms of a case.

- [ ] **Step 4: Verify and commit**

```bash
uv run --extra product-test pytest tests/product_eval/test_provider_bank.py -q
git add product_evals/common/provider_bank.py product_evals/spine_e2e_1 tests/product_eval/test_provider_bank.py
git commit -m "feat(product-eval): freeze SPINE provider wire bank"
```

### Task 3: Exact Public-Surface Prepare, Lease Probe, and Natural Resume

**Files:**
- Create: `product_evals/common/public_surface.py`
- Create: `product_evals/spine_e2e_1/__init__.py`
- Create: `product_evals/spine_e2e_1/protocol.py`
- Create: `product_evals/spine_e2e_1/coordinator.py`
- Modify: `tests/product/test_e2_long_horizon_recovery.py`
- Test: `tests/product_eval/test_spine_protocol.py`

**Frozen Product contract:**

```text
read(TOOL, workspace.read, IDEMPOTENT)
-> provider(PROVIDER, provider.chat)
-> approve(APPROVAL)
-> apply(TOOL, workspace.apply_patch, COMPENSATABLE, risk=1)
-> tests(TOOL, workspace.run_tests, IDEMPOTENT)
-> evaluate(EVALUATION)
-> done(TERMINAL)
```

`WorkflowGraph` freezes the six sequential edges, version 1, local tenant/workspace/principal, `policy_version="policy-1"`, `evaluator_refs=("evaluator:pytest:1",)`, and `max_replans=0`. `ExpectedOutcome` freezes evaluator `pytest:1`, threshold 1.0, 3600-second observation window, pytest/apply/final-digest evidence requirements, and explicit non-zero/missing/digest-mismatch failure semantics. The mechanical adjudicator, not the Product evaluator, owns final digest and receipt semantics.

Goal freezes local tenant/workspace/principal, the case statement, and the internally sampled case contract time; Goal has no expiry claim. Commitment freezes matching IDs/scope, deliverable `subject.py patch`, acceptance `python -m pytest exits 0`, `workspace:read/write` authority, risk tier 1, exit `verified`, a fixed 3600-second duration/expiry window, and fixed provider/tool/cost budgets large enough for the 360-second lease wait but not caller-adjustable. Resume must also satisfy a conservative maximum of 1800 seconds from `prepare_started`, leaving at least the frozen margin before Commitment expiry; missing that upper bound is `INVALID_TIMING`, not an ordinary recovery failure.

Every call to `run_task`, including approval continuation, resume, and terminal replay, passes exactly `{"target_path": case.target_path, "test_command": "python -m pytest"}`. Fixture setup writes `initial_content` and `pytest_source` before Product execution; it is not a hidden workflow node.

Each arm uses `cases/<case_id>/<arm>/workspace/` and an explicit file DB `state/agent-os.sqlite3`; `:memory:` and omitted DB paths are forbidden. Each phase command starts exactly one frozen provider server backed by the shared locked call ledger; before every application construction the harness clears the exact frozen provider-variable set, sets `AGENT_OS_PROVIDER_BASE_URL`, fixed model, `AGENT_OS_PROVIDER_TEMPERATURE=0`, `AGENT_OS_PROVIDER_API_KEY_ENV=SPINE_E2E_1_PROVIDER_KEY`, and a non-secret fixed local dummy value for that resolver key, then constructs the app and verifies public `provider_status()`. It never mutates private provider fields.

- [ ] **Step 1: Write RED public-surface and contract tests**

Tests AST-reject private organ access across every harness Python file, including `coordinator.py`, dynamic `getattr`, `vars`, `__dict__`, direct Product SQLite reads, imports of Product persistence internals, or an in-process workflow-runner import; validate exact Goal/Commitment/graph/outcome/input/DB/env/header values; reject deterministic fallback; and assert normalized projections exclude random IDs, timestamps, and pytest-duration-dependent artifact hashes. Coordinator tests prove exact child-process commands, fixed runner binding, immediate interrupt-anchor-probe order, and refusal of alternate executables/arguments. A GREEN Product regression guard proves the already-shipped behavior at `execution.py:390-393`: literal `stop_after_node="apply"` raises `WorkerInterrupted` after durable `NODE_COMPLETED` without reaching a lease-release site; an immediate fresh application with `recover_stale_lease=False` receives `ConcurrentWriteError`; normal returns and non-interrupt failures still release their lease. Server/HTTP/CLI AST tests prove `stop_after_node` is not externally routable, while harness AST tests permit only the literal `apply` value and forbid `recover_lease`, `os._exit`, and caller-selected interrupt nodes.

- [ ] **Step 2: Implement prepare**

For each case, `prepare`:

1. completes the uninterrupted arm: `create_task -> commit_task -> run_task(inputs) -> WAITING_APPROVAL -> record_approval -> run_task(inputs) -> VERIFIED`;
2. creates/commits the interrupted arm, runs it to `WAITING_APPROVAL`, records approval, and stops before apply with no active lease;
3. makes exactly two provider requests per case across those two arms.

- [ ] **Step 3: Implement active-lease probe and natural resume**

`interrupt_batch` is a separate process. Under one phase guard it calls `run_task(inputs, stop_after_node="apply")` for all 12 approved interrupted arms, requires typed `WorkerInterrupted` after every durable apply completion, persists public projections after each exception, and exits normally after the full batch. Because the typed exception escapes before all lease-release sites, process exit leaves each 300-second lease active without `SIGKILL`, private mutation, forced takeover, or a runtime change. Its batch-start sample is the conservative upper-bound anchor.

`probe_active_lease` is another fresh process. Its final internally sampled completion must satisfy `probe_completed.mono_after_ns - interrupt_started.mono_before_ns <= 60s`, not merely start within 60 seconds. It calls every arm with `recover_stale_lease=False`, requires exact active-lease `ConcurrentWriteError`, and proves task sequence/run lease fence/evidence/workspace/provider-request counts are unchanged. The frozen `coordinator.py` launches `interrupt-batch` as a child process, records/verifies its fixed-runner anchor, and immediately launches the probe child process, avoiding interactive agent/tool latency while preserving distinct process boundaries.

`resume_spine` runs in another fresh process only after the phase guard proves at least 360 seconds from `interrupt_batch_completed` and at most 1800 seconds from `prepare_started`. It calls `run_task(inputs, recover_stale_lease=False)`, requires the public run `lease_fence` to increase exactly once from the interrupted value, completes tests/evaluation, calls it once more to prove terminal replay adds no apply receipt, issues zero provider requests, and persists normalized public projections.

- [ ] **Step 4: Verify and commit**

```bash
uv run --extra product-test pytest tests/product/test_e2_long_horizon_recovery.py tests/product_eval/test_spine_protocol.py -q
git add product_evals/common/public_surface.py product_evals/spine_e2e_1/protocol.py product_evals/spine_e2e_1/coordinator.py tests/product/test_e2_long_horizon_recovery.py tests/product_eval/test_spine_protocol.py
git commit -m "feat(product-eval): add natural-expiry SPINE protocol"
```

### Task 4: Mechanical SPINE Adjudication

**Files:**
- Modify: `product_evals/spine_e2e_1/protocol.py`
- Test: `tests/product_eval/test_spine_protocol.py`

- [ ] **Step 1: Write RED verdict tests**

Cover duplicate logical receipts, terminal projection mismatch, missing/extra cases, wrong workflow/evaluator/provider digests, unexpected policy/correction events, phase/boot/context/runner-anchor drift, incomplete phases, wrong/absent active-lease denial, probe mutation, lease-fence drift, provider-request drift, any recovery call configured for forced takeover, and an intact ordinary Product failure.

- [ ] **Step 2: Implement exact normalized projection**

Compare: workflow digest; `SUCCEEDED`; outcome `VERIFIED`, score 1, evaluator `pytest:1`; exact completed node set; final target SHA; pytest exit 0; exactly one `workspace.apply_patch` receipt and one unique idempotency key; terminal replay receipt count unchanged. Require all 12 probes to raise `ConcurrentWriteError` with task sequence, public lease fence, evidence, workspace tree digest, and provider-request count unchanged; require resume fence = interrupted fence + 1; require exactly two provider requests per case before interruption and zero during probe/resume. Static/AST configuration evidence must show every recovery call uses `recover_stale_lease=False`. Exclude random IDs, timestamps, and timing-sensitive pytest artifact digests.

Verdict priority:

```python
if instrumentation_or_protocol_invalid:
    verdict = "INVALID"
elif all_12_verified_and_rehydrated_without_duplicate_effect:
    verdict = "PASS"
else:
    verdict = "NOT_PASS"
```

- [ ] **Step 3: Verify and commit**

```bash
uv run --extra product-test pytest tests/product_eval/test_spine_protocol.py -q
git add product_evals/spine_e2e_1/protocol.py tests/product_eval/test_spine_protocol.py
git commit -m "feat(product-eval): add SPINE mechanical adjudication"
```

### Task 5: Phase CLI, Preregistration, Freeze, Real Run, and Truth Update

**Files:**
- Create: `product_evals/spine_e2e_1/cli.py`
- Create: `tests/product_eval/test_spine_cli.py`
- Create: `docs/research/SPINE-E2E-1-preregistration-spec.yaml`
- Create after run: `docs/research/SPINE-E2E-1-result.md`

- [ ] **Step 1: Write CLI and phase-guard RED tests**

CLI exposes only fixed commands and equality assertions over frozen bindings. `--now`, `--clock`, `--min-seconds`, `--test-mode`, `allow_short_timing`, caller-authoritative context/path/digest inputs, threshold environment overrides, and equivalent aliases are forbidden by parser/help/AST tests. Unit tests may monkeypatch the private clock sampler; production CLI/config may not inject it. Every production command derives target/spec/lock/manifest/corpus/bank/evaluator and runner bindings from the frozen run and fails if an optional repeated assertion differs.

Test: early probe/resume rejection has zero DB/workspace/ledger mutation; completed phase replay is denied; the sole production context resolver refuses caller-selected paths/digests, a wrong runner common-dir/branch/HEAD, dirty runner worktree, or changed request/approval row digest; AST/call-path tests reject any production caller that constructs authority directly with `phase_context_sha256` or invokes `phase_guard` without the resolver-derived context; changed host/boot/context/HEAD/spec/lock/corpus/bank/evaluator or missing runner anchor fails closed; write-once phase payload/result refuses overwrite.

- [ ] **Step 2: Implement production phase sequence**

```text
prepare_started/completed
-> fixed runner prepare anchor
-> frozen coordinator launches interrupt_batch_started/completed
-> fixed runner anchor
-> coordinator launches probe_active_lease_started/completed
   (last denial conservative upper bound <=60s from interrupt start)
-> wait
-> resume_started/completed (>=360s from interrupt_batch_completed)
-> fixed runner resume anchor
-> adjudicate_started/completed (writes adjudication_payload.json once)
-> fixed runner adjudicate anchor
-> finalize-result (pure packaging; writes result.json once)
```

Every experimental command holds `phase.lock`, validates Git HEAD and all frozen digests, verifies the prior phase's runner receipt, records `<phase>_started` before Product side effects, writes its phase payload once, records `<phase>_completed`, and writes `evaluation/anchor_requests/<phase>.json` once with record head, ledger SHA, provider-call-ledger head/SHA, payload SHA, boot hash, context hash, runner workspace-relative common-dir, runner frozen HEAD, request ID, and the canonical request/approval row digests. `prepare` is the only genesis phase and therefore the only phase with no prior runner receipt; its Product work must be followed by the prepare anchor before interrupt can start. The coordinator immediately calls that exact fixed runner's approval-gated `team event --type EVIDENCE_APPENDED`, using the run-relative anchor path as both `artifact` and `evidence-ref`; the frozen summary format is `SPINE_PHASE_ANCHOR phase=<phase> request_sha256=<64hex>`. Before every later Product side effect, the command reads `.agent_runs/<run>/agent_events.jsonl`, requires exactly one matching preapproved `team.event.record` event with the exact summary/request SHA, artifact, evidence-ref, approval ID, runner binding, and rehashes the write-once file plus canonical permission rows. No Product/runtime package imports the workflow runner; the frozen coordinator may invoke its CLI only as a subprocess after verifying the binding.

`adjudicate` writes only `adjudication_payload.json` before its completion/runner anchor, avoiding self-verification. After that anchor exists, `finalize-result` performs no Product action and appends no self-referential phase; under `phase.lock` it verifies all completed phases and runner anchors and writes `result.json` once. External `prereg verify --result` is the final independent integrity check.

- [ ] **Step 3: Preapprove the fixed runner anchor authority**

Before writing/committing the preregistration spec, create one `team.event.record` request with affected path `.agent_runs/spine-e2e-1-20260712/agent_events.jsonl` and exact run-relative `evidence_refs` for the five future files `evaluation/anchor_requests/{prepare,interrupt_batch,probe_active_lease,resume,adjudicate}.json`. Permission-request creation may name those future evidence paths before they exist; each event is allowed only after its exact file exists and is supplied as both run-relative `artifact` and `evidence-ref`. The founder must decide the request `approved_session`; `approved_once` is forbidden for the repeated anchor sequence. Freeze `run_id`, request ID, requester, permission action, affected path, evidence refs, canonical request-row digest, canonical approval-row digest, `decision=approved_session`, `decided_by`, both row timestamps, runner common-dir, and runner HEAD. Live approvals have no expiry field: require exactly one valid approved row for that request ID and no later conflicting decision. The approval authorizes recording only, not Product execution or a PASS verdict.

- [ ] **Step 4: Write the preregistration spec**

Freeze the bounded Product claim, 12 case IDs, complete Goal/Commitment/request/response/semantic-header/DAG/outcome/input/DB/env contracts, provider per-digest call counts, natural-expiry semantics, conservative upper/lower 60/360/1800-second formulas, timing evidence level/trust assumptions, Darwin/Linux identity sources, frozen context derivation, runner commit/common-dir plus preapproved request/approval row digests, exact anchor paths and summary schema, coordinator/phase/finalization protocol, exact pending/completed/failed ledger semantics, exact verdict/invalidity codes, and every Product/harness mechanism file. Builder and reviewer IDs must be distinct.

- [ ] **Step 5: Commit a clean candidate and complete review/freeze**

Precondition: this plan, the parent LH tombstone, and the separate LH-RECOVERY-1A plan have already passed independent plan review and landed in their own plan-only commit. They must not remain as dirty files while the freeze candidate is built.

```bash
git add product_evals tests/product_eval docs/research/SPINE-E2E-1-preregistration-spec.yaml
git commit -m "test(product-eval): preregister fresh SPINE-E2E-1"
git status --porcelain
```

Using the fixed runner via the workflow feature worktree:

```text
RR-0031 controlled delta review and verify
-> exact-content manifest verify
-> independent content review
-> independent architecture review
-> prereg freeze
```

Any mismatch stops; no frozen gate may be edited to rescue the run.

- [ ] **Step 6: Run the real phases**

Run `prepare -> prepare anchor`, then the frozen coordinator for `interrupt-batch -> interrupt anchor -> active-lease probe -> probe anchor`; require the final probe sample within 60 seconds of interrupt start. Wait until the internal same-boot monotonic lower bound reaches 360 seconds from interrupt completion while remaining below the frozen 1800-second prepare-to-resume maximum; run `resume -> resume anchor -> adjudicate -> adjudicate anchor -> finalize-result`. No virtual clock or threshold override is permitted.

- [ ] **Step 7: Verify result and update truth**

Run workflow-runner `prereg verify --result`, then independent result review. Create `SPINE-E2E-1-result.md` from immutable hashes and update only the smallest authoritative truth set. Preserve `NOT_PASS` or `INVALID` without rerun or gate changes.

```bash
git add docs/research/SPINE-E2E-1-result.md docs/CURRENT_STATE.yaml codebase_index.md
git commit -m "docs(product-eval): record SPINE-E2E-1 result"
```
