// Agent Thread panel logic: a typed Surface consumer that renders the session
// transcript from resumable SSE events. Pure logic (client injected) so it is
// testable without a DOM.

import type { EventBatch, SessionSnapshot, SurfaceClient } from "../surface_client";

export interface ThreadMessage {
  sequence: number;
  kind: string;
  payload_json: string;
}

export interface AgentThreadState {
  messages: ThreadMessage[];
  nextSequence: number;
}

/** Resume the thread from the last known cursor; returns the new cursor. */
export async function resumeThread(
  client: SurfaceClient,
  taskId: string,
  lastSequence: number,
): Promise<AgentThreadState> {
  const batch: EventBatch = await client.events(taskId, lastSequence, 0);
  const messages = batch.events.map((event) => ({
    sequence: event.sequence,
    kind: event.event_type,
    payload_json: event.payload_json,
  }));
  return {
    messages,
    nextSequence: batch.next_sequence,
  };
}

/** Map a session snapshot to the thread's message count for the header. */
export function threadSummary(snapshot: SessionSnapshot): {
  messageCount: number;
  status: string;
} {
  return {
    messageCount: snapshot.message_count,
    status: snapshot.status,
  };
}
