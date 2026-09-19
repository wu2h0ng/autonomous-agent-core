/**
 * The durable turn projection shared by the TUI controller and the headless
 * `noem session recover`.
 *
 * What matters is that neither caller guesses: an uncommitted turn is
 * `SESSION_TURN_STARTED` minus `SESSION_TURN_COMPLETED`, and the dead-turn
 * closure record comes from the completion payload (so it survives a restart).
 */
import assert from "node:assert/strict";
import test from "node:test";
import { latestDeadTurnClosure, openDurableTurnIds } from "../src/turns.js";
import type { TaskEvent } from "../src/contracts.js";

function event(sequence: number, eventType: string, payload: Record<string, unknown>): TaskEvent {
  return {
    event_id: `e:${sequence}`,
    task_id: "task:1",
    event_type: eventType,
    payload_json: JSON.stringify(payload),
    occurred_at: "2026-09-19T00:00:00Z",
    sequence,
  };
}

test("openDurableTurnIds: started without completed, in start order", () => {
  const events = [
    event(1, "SESSION_TURN_STARTED", { turn_id: "turn:a" }),
    event(2, "SESSION_TURN_COMPLETED", { turn_id: "turn:a", stop_reason: "completed" }),
    event(3, "SESSION_TURN_STARTED", { turn_id: "turn:b" }),
    event(4, "SESSION_TURN_STARTED", { turn_id: "turn:c" }),
  ];
  assert.deepEqual(openDurableTurnIds(events), ["turn:b", "turn:c"]);
});

test("openDurableTurnIds: a malformed payload never fabricates a turn", () => {
  const broken: TaskEvent = {
    event_id: "e:1",
    task_id: "task:1",
    event_type: "SESSION_TURN_STARTED",
    payload_json: "{not json",
    occurred_at: "2026-09-19T00:00:00Z",
    sequence: 1,
  };
  const events = [broken, event(2, "SESSION_TURN_STARTED", { turn_id: 7 })];
  assert.deepEqual(openDurableTurnIds(events), []);
});

test("latestDeadTurnClosure: the newest closure record in the stream", () => {
  const events = [
    event(1, "SESSION_TURN_STARTED", { turn_id: "turn:a" }),
    event(2, "SESSION_TURN_COMPLETED", {
      turn_id: "turn:a",
      stop_reason: "unknown_requires_review",
      dead_turn_recovery: { turn_id: "turn:a", reason_code: "TURN_OWNER_PROCESS_GONE" },
    }),
    event(3, "SESSION_TURN_STARTED", { turn_id: "turn:b" }),
    event(4, "SESSION_TURN_COMPLETED", {
      turn_id: "turn:b",
      stop_reason: "unknown_requires_review",
      dead_turn_recovery: { turn_id: "turn:b", reason_code: "TURN_OWNER_PROCESS_GONE" },
    }),
  ];
  assert.equal(latestDeadTurnClosure(events)?.turn_id, "turn:b");
  // A normal completion is not a closure record.
  assert.equal(latestDeadTurnClosure([event(1, "SESSION_TURN_COMPLETED", { turn_id: "x" })]), null);
});
