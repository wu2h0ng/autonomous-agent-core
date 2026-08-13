// Observe posture (Wave 2c): read-only projection of HelpRequests and
// unfinished-commitment signals from the task event stream.

import type { SurfaceEvent } from "../surface_client";

export interface ObserveItem {
  sequence: number;
  kind: "help_request" | "risk";
  summary: string;
}

/** Project HelpRequest / risk events read-only from the event stream. */
export function observeEvents(events: SurfaceEvent[]): ObserveItem[] {
  const items: ObserveItem[] = [];
  for (const event of events) {
    if (
      event.event_type !== "HELP_REQUESTED" &&
      event.event_type !== "TASK_FAILED" &&
      event.event_type !== "CORRECTION_WRITTEN"
    ) {
      continue;
    }
    let payload: Record<string, unknown>;
    try {
      payload = JSON.parse(event.payload_json) as Record<string, unknown>;
    } catch {
      continue;
    }
    const kind: ObserveItem["kind"] =
      event.event_type === "HELP_REQUESTED" ? "help_request" : "risk";
    const summary =
      typeof payload.reason === "string"
        ? payload.reason
        : typeof payload.scope === "string"
          ? payload.scope
          : event.event_type;
    items.push({ sequence: event.sequence, kind, summary });
  }
  return items;
}
