# Agent CLI review-debt remediation — 2026-07-27

> Track: Product  
> Status: `IMPLEMENTED_LOCAL / TARGETED_TESTED`  
> Branch: `codex/agent-cli-v0-20260727`  
> Closes baseline debt from `AGENT-CLI-V0-independent-review-2026-07-27.md`

## Changes

1. **One-shot `-p` gateway** — `apps/cli/__main__.py` now uses `AutoApproveGateway` for prompt/one-shot (tier &lt; 3). Shell (tier ≥ 3) remains rejected headlessly. `NonInteractiveDenyGateway` stays available for explicit deny tests.
2. **Database binding** — `terminal_session.json` schema bumped to `agent-cli-session.v1` with required resolved `database`. Resume checks session + Mandate attach against `--database`. `ensure_local_mandate_session` fail-closes on attach/database mismatch.
3. **Resume activity** — Resume rejects non-resumable `RunStatus` and `correction.halted(...)` runs.

## Evidence

`uv run pytest tests/product/test_terminal_chat_loop.py tests/product/test_agent_cli_v0.py tests/product/test_agent_cli_p1.py tests/product/test_agent_cli_stream.py tests/product/test_agent_cli_review_debt.py -q`

## Claim ceiling

Still no merge / release / usable-alpha / Autonomy claim. Old `agent-cli-session.v0` sidecars fail closed (start fresh).
