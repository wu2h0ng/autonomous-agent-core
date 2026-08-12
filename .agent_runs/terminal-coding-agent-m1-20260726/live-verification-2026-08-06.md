# Live-Provider Verification — terminal coding agent M1

> Date: 2026-08-06
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

- `live-verification-2026-08-06.transcript.txt` — full pty transcript (prompt,
  approval, assistant final message, `/exit`).
- `live-verification-2026-08-06.events.json` — durable task event stream (24 events,
  sequence/event_type/payload/occurred_at columns) dumped from the session's SQLite
  event store.

## Notes

- The run captured here happened on 2026-08-06 (all event timestamps confirm it). An
  earlier live run on 2026-07-30 produced the same four-receipt chain, but its `/tmp`
  artifacts were lost to a system temp cleanup before capture; this 2026-08-06 run is
  the first durably captured one. An earlier revision of this file was mislabeled
  2026-07-30 and was corrected in the independent-review fix pass.
- At capture time, tier-2 interactive approvals were corroborated only by this pty
  transcript; the event stream records no APPROVE marker for them. The
  independent-review fix pass added durable APPROVE recording for tier-2 grants, so
  later runs carry it in-stream.
- This verifies one real coding task on one live provider. It is not a benchmark,
  not a parity claim and not a release gate.
