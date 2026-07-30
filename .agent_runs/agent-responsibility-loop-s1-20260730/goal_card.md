# Goal Card — P-AGENT-RESPONSIBILITY-LOOP-1

Status: `IMPLEMENTATION_ACTIVE`

Primary class: `P`

Owner: Codex single writer

## User outcome

One foreground Agent CLI Work process maintains an attached Mandate's durable
responsibility across cycles and process restarts without requiring the Founder
to restate known state, while preserving typed authority, Outcome/Help truth,
C7 and externally governed HCW measurement.

## Exact design authority

- Approved design head: `5036ab7ffd6e919d92d66fdd91815523e18b76af`
- Approved design SHA-256:
  `f9e564cf4cb55da454568bebdc30212b68d144ad0e155bd39b5a217a05b654d7`
- Independent verdict: `SPEC_APPROVE`

## Slice 1 scope

- `agent run/status/answer/correct/resume` Work surface;
- deterministic responsibility source projection and admission;
- durable loop lease, heartbeat, TTL and fencing;
- cycle/checkpoint persistence and A-to-B-to-A restoration;
- existing Outcome/Help settlement path;
- append-only operator work events and HCW/cycle receipts;
- fail-closed provider, authority, schema, interrupt and waiting semantics.

## Excluded

- SELFDEV execution or promotion;
- BlueprintGap/ImprovementEpisode;
- daemon, TUI, MCP or general multi-agent runtime;
- internal-version or Founder-operated baseline;
- merge to main, activation or release;
- HCW-reduction, superiority, self-improvement or autonomy claims.

## Exit gate

Bypass-detecting tests fail before implementation and pass afterward; a real
two-process CLI fixture restores the same responsibility without user
restatement; targeted tests, Ruff, Pyright and diff checks pass; an independent
reviewer returns no P0/P1 on the exact implementation head.
