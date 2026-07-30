# Goal Card — Agent CLI P1 Streaming + Clean Interrupt

> Date: 2026-07-27
> Track: Product
> Status: **P1_STREAM_IMPLEMENTATION_AUTHORIZED / NO_RELEASE**
> Branch: `codex/agent-cli-v0-20260727` (worktree)
> Base: Agent CLI V0 + P1 on same branch
> Claim ceiling: `IMPLEMENTED_LOCAL / TARGETED_TESTED` only

## Goal

Stream provider assistant text deltas to the Agent CLI terminal as they arrive,
while preserving governed ProviderPort binding/receipt logic and failing closed
on user interrupt via task correction.

## Requirement taxonomy

- `U` — operator sees assistant output incrementally instead of waiting for the
  full provider response.
- `P` — `ProviderPort.complete_streaming`, OpenAI-compatible SSE parsing,
  DeterministicProvider chunked deltas, AgentLoop `on_text_delta`, CLI `--no-stream`.
- `A` — non-stream `complete()` path unchanged; auth/binding/correction/receipt
  gates preserved; KeyboardInterrupt triggers `correct_task` and exits REPL.
- `E` — `tests/product/test_agent_cli_stream.py`; targeted suite green; ruff clean.
- `R` — none.

## Done conditions

1. Default `ProviderPort.complete_streaming` falls back to `complete` + one delta.
2. `OpenAICompatibleProvider` parses SSE `data:` lines for content + tool_calls.
3. `DeterministicProvider` emits 8-char chunks for hermetic tests.
4. `AgentLoop` calls `complete_streaming` when `AgentLoopConfig.stream=True`.
5. Agent CLI prints deltas live; `--no-stream` forces non-streaming debug path.
6. KeyboardInterrupt during a turn halts correction and breaks REPL cleanly.

## Explicit non-goals

MCP/TUI, synthetic permits, release claim, weakening provider binding checks,
live-network tests in CI.

## Stop / REVISE_TO_SPEC

- Bypassing correction/receipt on streamed invocations
- Printing secrets or credential material from SSE payloads
- Claiming streaming as autonomy or release evidence
