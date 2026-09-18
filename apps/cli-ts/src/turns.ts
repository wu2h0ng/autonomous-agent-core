/**
 * Durable turn state, projected from the task event stream.
 *
 * The event stream is the only truth about which turns exist: a turn is open
 * while its `SESSION_TURN_STARTED` has no `SESSION_TURN_COMPLETED`. Two callers
 * need the same projection — the TUI controller (what to tell the operator about
 * a turn that can never finish) and the headless `noem session recover` (which
 * turn id to name in the recovery command) — and neither may guess it, so it
 * lives here once.
 *
 * A `dead_turn_recovery` block inside a completion is the durable record of an
 * operator declaring a dead turn closed; it survives restarts because it is in
 * the stream, not in a client's memory.
 */
import type { RecoveredUnknownTurn, TaskEvent } from "./contracts.js";

function payloadOf(event: TaskEvent): Record<string, unknown> {
  try {
    const value: unknown = JSON.parse(event.payload_json);
    return value !== null && typeof value === "object"
      ? (value as Record<string, unknown>)
      : {};
  } catch {
    return {};
  }
}

function turnIdOf(event: TaskEvent): string | null {
  const turnId = payloadOf(event).turn_id;
  return typeof turnId === "string" && turnId.length > 0 ? turnId : null;
}

/** Turn ids that were started and never completed, in start order. */
export function openDurableTurnIds(events: readonly TaskEvent[]): string[] {
  const started: string[] = [];
  const completed = new Set<string>();
  for (const event of events) {
    if (
      event.event_type !== "SESSION_TURN_STARTED" &&
      event.event_type !== "SESSION_TURN_COMPLETED"
    ) {
      continue;
    }
    const turnId = turnIdOf(event);
    if (turnId === null) continue;
    if (event.event_type === "SESSION_TURN_STARTED") {
      if (!started.includes(turnId)) started.push(turnId);
    } else {
      completed.add(turnId);
    }
  }
  return started.filter((turnId) => !completed.has(turnId));
}

/** The newest recorded dead-turn closure, or null when there is none. */
export function latestDeadTurnClosure(
  events: readonly TaskEvent[],
): RecoveredUnknownTurn | null {
  let latest: RecoveredUnknownTurn | null = null;
  for (const event of events) {
    if (event.event_type !== "SESSION_TURN_COMPLETED") continue;
    const block = payloadOf(event)["dead_turn_recovery"];
    if (block !== null && typeof block === "object") {
      latest = block as RecoveredUnknownTurn;
    }
  }
  return latest;
}
