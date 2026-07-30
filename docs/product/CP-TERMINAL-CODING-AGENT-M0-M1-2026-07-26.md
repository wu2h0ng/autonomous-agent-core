# Terminal Coding Agent Context Pack — M0 + M1

> Date: 2026-07-26
> Track: Product
> Status: **SPECIFIED_ONLY**
> Goal Card: `docs/product/GC-TERMINAL-CODING-AGENT-M0-M1-2026-07-26.md`
> Architecture Brief: `docs/architecture/T-P-CORE-TERMINAL-CODING-AGENT-ARCHITECTURE.md`
> Dated benchmark: `docs/product/TERMINAL-AGENT-CLI-BENCHMARK-2026-07-26.md`
> Exact base: `27337578e15f307bec18edb5221356d5c3ed6c04`

## Reading order and authorities

1. Root workspace `AGENTS.md` (constitution): §5 track selection (this package is
   Product Track), §7 product-engineering hard boundaries, §9A requirement taxonomy,
   §13 medium/high-risk product flow, §14 engineering reality review.
2. Repo `AGENTS.md`: §3 non-negotiable boundaries, §4 Product Track flow, §6
   verification entry points, §7 founder-reserved decisions.
3. `docs/CURRENT_STATE.yaml`, `docs/AGENT-OS-PRODUCT-BLUEPRINT.md`,
   `docs/PROJECT_PLAN.md`, `codebase_index.md` for live state.
4. The dated Hermes / OpenClaw / Pi benchmark. It selects product-shape inputs but
   creates no parity claim.
5. This packet. The founder-approved route-A plan is the design input; this packet is
   the governing spec for M0+M1.

## Verified foundation (all inspected at base commit; none is an empty shell)

- `packages/contracts/src/agent_os_contracts/provider.py`
  - `ProviderMessageRole` already includes `TOOL` (line 32); `ProviderRequest.messages`
    supports multiple messages. The contract foundation for a multi-turn loop exists.
  - `ProviderMessage` (line 136) does **not** yet carry `tool_call_id` / `tool_calls`;
    M1 extends it.
- `packages/os_core/src/agent_os_core/provider.py`
  - `ProviderPort.complete()` plus `OpenAICompatibleProvider` (urllib-based, parses
    `tool_calls`, non-streaming) and `DeterministicProvider` for hermetic tests.
- `packages/os_core/src/agent_os_core/capability.py`
  - `WorkspaceSandbox` (line 69) registers four capabilities: `workspace.read`,
    `workspace.apply_patch` (whole-file replacement), `workspace.run_tests`,
    `artifact.write`, plus `workspace.compensate_patch`. All path access goes through
    `_safe_path` (line 279); permit matching, correction-epoch validation, idempotency
    and snapshot compensation are already enforced.
- `packages/os_core/src/agent_os_core/governance.py`
  - `PolicyKernel.decide()` + `permit()` issue per-action permits with approval/risk
    tiering.
- `packages/os_core/src/agent_os_core/execution.py`
  - Event-sourced durable `RunCoordinator` over a static `WorkflowGraph`. This is a
    graph executor, not a conversational loop; M1 adds a new execution form beside it
    and does not modify its semantics.
- `packages/os_core/src/agent_os_core/proposal_engine.py`
  - Single-turn provider call with a hard-coded single-file prompt. This is the shape
    M1 replaces, but its receipt-construction and binding-validation logic is reused
    (extracted into a shared helper).
- `apps/cli/__main__.py`
  - argparse one-shot commands only; no interactive entry point exists.

## Working-tree condition at authoring time

Base branch is `feature/awl-3-coordinator-decomposition` with pre-existing uncommitted
and untracked changes from other work (contracts/os_core edits, roadmap docs,
experiments). Those belong to other tasks: M1 implementation must start from a clean
dedicated feature branch, must not revert or absorb them, and must report Git state
separately per repo `AGENTS.md` §8.

## Constraints that bind implementation

- Zero new runtime dependencies in M1: stdlib REPL (`input()`), stdlib search
  (`fnmatch` + line regex), urllib provider. `rich`/`prompt_toolkit` are deferred to M3
  (root constitution §7.10 permits UI libraries; the kernel never takes a UI
  dependency).
- Every runtime behavior change is introduced by a failing or bypass-detecting test
  first (repo `AGENTS.md` §4; root §7.3).
- No pseudo implementation: no empty classes, mocked success, hard-coded outputs,
  unused adapters or constant-return tests (root §7.1).
- Agent Core stays domain-independent; the new capabilities are generic workspace
  primitives, not coding-business semantics (repo `AGENTS.md` §3.3).
- C7 is non-writable and non-bypassable; the loop holds no final execution authority
  (repo `AGENTS.md` §3.1–3.2).
- One writer per file scope; M1 implementation runs on its own feature branch with
  independent review before any merge (repo `AGENTS.md` §8; root §12, §16).
- No secrets, tokens or customer data in docs, tests, fixtures or event records
  (repo `AGENTS.md` §3.7).

## Verification entry points (repo `AGENTS.md` §6, Product Track base gates)

```bash
uv run --extra product-test pytest tests/product -q
uv run --extra product-test ruff check apps packages/contracts/src packages/os_core/src tests/product
uv run --extra product-test pyright apps packages/contracts/src packages/os_core/src tests/product
uv build --wheel --out-dir /tmp/agent-os-product-wheel packages/contracts
uv build --wheel --out-dir /tmp/agent-os-product-wheel packages/os_core
```

Passing these is necessary, not sufficient: it does not prove production readiness,
market parity with Claude Code / Codex CLI, Blueprint completion or any autonomy claim.
M1 additionally requires the targeted new tests and the manual live-provider end-to-end
record listed in the Goal Card.

## Evidence and claim boundary

- This package produces product-ledger evidence only (entry point + contract + failure
  path + integration + verification). It produces no research-ledger, process-ledger or
  commercial-ledger evidence, and none may be backfilled from it.
- Benchmark framing against Hermes, OpenClaw, Pi, Claude Code and Codex CLI is a design
  target, not a claim. No parity, market or customer statement is authorized.
- M1 stores typed turn metadata plus provider/action receipts in the Task event stream,
  but live conversation messages are not reconstructable as a resumable session yet.
  That gap stays explicit instead of being backfilled by Task persistence.
- Claim levels are reported separately as `specified / implemented / tested /
  integrated / verified`; the pre-implementation ceiling for everything in this packet
  is `specified`.
- Live-provider verification is manual and recorded with date, provider, task and
  transcript pointer; CI evidence uses `DeterministicProvider` only.
