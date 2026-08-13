# Live-Provider Verification — terminal coding agent M1

> Date: 2026-07-30
> Status: `LIVE_PROVIDER_TASK_VERIFIED`
> Reviewer-facing evidence for `docs/CURRENT_STATE.yaml` P-TERMINAL-CODING-AGENT-1

## Setup

- Provider: OpenAI-compatible live endpoint (`AGENT_OS_PROVIDER_BASE_URL` from the
  operator's local `.env`, model `kimi-k2-0711-preview`). Credentials were read from
  the environment at runtime and are not stored in this artifact.
- Workspace: `/tmp/agent-os-live-check` containing
  - `fixture.txt` = `wrong-content\n` (before)
  - `test_fixture.py` asserting `fixture.txt == "hello-world\n"` (failing before)
- Entry point: interactive `python -m apps.cli chat` driven over a pty; the single
  confirmation prompt was answered `y` by the driver.

## Task prompt

```text
The test test_fixture.py is failing. Read it, fix fixture.txt so the test passes,
then run the tests to confirm.
```

## Result

- The agent completed one turn with four governed actions, all
  `ACTION_PROPOSED -> POLICY_DECIDED -> ACTION_RECEIPT_RECORDED SUCCEEDED`:
  1. `workspace.read` (`test_fixture.py`)
  2. `workspace.read` (`fixture.txt`)
  3. `workspace.edit` (`fixture.txt` -> `hello-world\n`) — required and received one
     interactive terminal approval (tier-2 confirmation)
  4. `workspace.run_tests` — pytest exit code 0
- `fixture.txt` after the run: `hello-world\n`; `python3 -m pytest` in the workspace
  passes.
- Assistant final message confirms the fix and the green test run (see transcript).
- The session exited cleanly via `/exit`; a `TASK_CONFIGURATION_SNAPSHOT_SEALED`
  event and durable `ProviderExecutionReceipt`s bind the provider calls (see events
  dump).

## Evidence files

- `live-verification-2026-07-30.transcript.txt` — full pty transcript (prompt,
  approval, assistant final message, `/exit`).
- `live-verification-2026-07-30.events.json` — complete durable task event stream
  (24 events) dumped from the session's SQLite event store.

## Notes

- An identical run earlier on 2026-07-30 produced the same four-receipt chain; its
  `/tmp` artifacts were lost to a system temp cleanup, which is why this run was
  repeated with durable capture.
- This verifies one real coding task on one live provider. It is not a benchmark,
  not a parity claim and not a release gate.
