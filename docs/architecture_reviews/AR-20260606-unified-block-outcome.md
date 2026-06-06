# AR-20260606 Unified failure / block result contract

> Status: Accepted
> Scope: `TrustedLoopRuntime` (`run` raise sites + new `evaluate`), new contracts
> `BlockCode` / `TrustedLoopBlock` / `TrustedLoopOutcome`, `TrustedLoopBlocked` exception,
> and the API/CLI surfaces that consume them.

## Problem

The Trusted Loop signalled expected business blocks with ad-hoc, stringly-typed exceptions:
`ValueError("SQL safety check failed: ...")`, `ValueError("No SQL template ...")`,
`KeyError("Unknown metric contract: ...")`, `KeyError("No provider can satisfy schemas: ...")`.
Surfaces (CLI/API/UI) could not distinguish an expected, user-facing block (unsupported metric,
unsafe SQL) from a programming/wiring error, nor render a consistent "blocked, here is why"
response. A block carried no machine-readable code.

## Decision

Distinguish **expected business blocks** from **programming/wiring errors**.

Expected business blocks — these now carry a structured, typed payload:

| Stage | Old | BlockCode |
|---|---|---|
| metric resolution (unknown metric) | `KeyError` | `UNKNOWN_METRIC` |
| provider selection (no provider for schemas) | `KeyError` | `NO_PROVIDER` |
| template selection (no template for metric) | `ValueError` | `NO_TEMPLATE` |
| SQL safety rejection | `ValueError` | `SQL_SAFETY` |

New contracts (`packages/contracts`):
- `BlockCode(StrEnum)`: `UNKNOWN_METRIC`, `NO_PROVIDER`, `NO_TEMPLATE`, `SQL_SAFETY`.
- `TrustedLoopBlock`: `code`, `message`, `stage`, `details: tuple[str, ...]`.
- `TrustedLoopOutcome`: `status` (`"ok"` | `"blocked"`), `result: TrustedLoopResult | None`,
  `block: TrustedLoopBlock | None`, with `ok` / `blocked` convenience properties.

OS Core:
- `TrustedLoopBlocked(Exception)` carries a `TrustedLoopBlock`. `run()` raises it at the four
  block sites above (it is NOT a `ValueError` subclass — a block is a first-class outcome, not a
  generic value error).
- New `evaluate(question, parameters) -> TrustedLoopOutcome`: runs the loop and returns a unified
  outcome — `ok` with the `TrustedLoopResult`, or `blocked` with the `TrustedLoopBlock`. `run()` is
  unchanged for the success path and still raises `TrustedLoopBlocked` for blocks, so existing
  success-path callers are untouched.

**Not converted (remain exceptions):** missing connector and missing snapshot raise `KeyError` —
these are wiring/config errors, not user-facing business blocks, and existing tests assert `KeyError`.

## Surfaces

- `outcome_service.run_service` uses `evaluate()` and returns `{"status": "ok", ...}` on success
  (existing keys preserved) or `{"status": "blocked", "block": {...}}` on a block.
- FastAPI `POST /runs` returns HTTP 422 with the block payload on a blocked outcome (instead of 500).
- CLI prints the status and the block payload; exits non-zero on a block.

## Verification

- `evaluate()` returns `ok` for a normal run and `blocked` with the right `BlockCode` for: unsafe SQL,
  unknown metric, missing template, no provider.
- `run()` raises `TrustedLoopBlocked` (carrying the block) at those sites.
- Surface tests: `run_service` returns the blocked contract; `/runs` → 422.
- Connector/snapshot `KeyError` paths remain unchanged (regression).
