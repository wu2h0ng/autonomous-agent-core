// Terminal panel logic (Wave 2b): render governed shell-action events from
// the task event stream. READ-ONLY: the panel cannot invoke shell commands;
// only typed protocol commands may, and only with approval.

import type { SurfaceEvent } from "../surface_client";

export interface TerminalLine {
  sequence: number;
  kind: string;
  summary: string;
}

/** Filter shell-related action events into a bounded terminal transcript. */
export function terminalEvents(events: SurfaceEvent[]): TerminalLine[] {
  const lines: TerminalLine[] = [];
  for (const event of events) {
    let payload: Record<string, unknown>;
    try {
      payload = JSON.parse(event.payload_json) as Record<string, unknown>;
    } catch {
      continue;
    }
    const action = payload.action;
    if (typeof action !== "object" || action === null) {
      continue;
    }
    const actionRecord = action as Record<string, unknown>;
    const capabilityId =
      typeof actionRecord.capability_id === "string"
        ? actionRecord.capability_id
        : "";
    if (capabilityId !== "workspace.shell") {
      continue;
    }
    let argumentsRecord: Record<string, unknown> = {};
    if (typeof actionRecord.arguments_json === "string") {
      try {
        const parsed = JSON.parse(
          actionRecord.arguments_json,
        ) as Record<string, unknown>;
        if (typeof parsed === "object" && parsed !== null) {
          argumentsRecord = parsed;
        }
      } catch {
        // keep empty
      }
    }
    lines.push({
      sequence: event.sequence,
      kind: event.event_type,
      summary:
        typeof argumentsRecord.command === "string"
          ? argumentsRecord.command
          : "shell action",
    });
  }
  return lines;
}
