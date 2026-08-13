// Diff panel logic (Wave 2b): render bounded action/effect diffs from the
// task event stream. Read-only; the panel never invokes an action itself.

import type { SurfaceEvent } from "../surface_client";

export interface DiffSummary {
  sequence: number;
  action_digest: string;
  path: string | null;
  old_excerpt: string;
  new_excerpt: string;
  truncated: boolean;
}

const MAX_EXCERPT = 120;

function excerpt(value: unknown): { text: string; truncated: boolean } {
  if (typeof value !== "string") {
    return { text: "", truncated: false };
  }
  return {
    text: value.slice(0, MAX_EXCERPT),
    truncated: value.length > MAX_EXCERPT,
  };
}

/** Extract bounded diff summaries from ACTION_PROPOSED / receipt events. */
export function recentDiffs(events: SurfaceEvent[]): DiffSummary[] {
  const diffs: DiffSummary[] = [];
  for (const event of events) {
    if (
      event.event_type !== "ACTION_PROPOSED" &&
      event.event_type !== "ACTION_RECEIPT_RECORDED"
    ) {
      continue;
    }
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
    const argumentsJson = actionRecord.arguments_json;
    let argumentsRecord: Record<string, unknown> = {};
    if (typeof argumentsJson === "string") {
      try {
        const parsed = JSON.parse(argumentsJson) as Record<string, unknown>;
        if (typeof parsed === "object" && parsed !== null) {
          argumentsRecord = parsed;
        }
      } catch {
        // keep empty
      }
    }
    const path = typeof argumentsRecord.path === "string"
      ? argumentsRecord.path
      : null;
    const oldExcerpt = excerpt(argumentsRecord.old_string);
    const newExcerpt = excerpt(argumentsRecord.new_string);
    if (path === null && oldExcerpt.text === "" && newExcerpt.text === "") {
      continue;
    }
    diffs.push({
      sequence: event.sequence,
      action_digest:
        typeof actionRecord.action_digest === "string"
          ? actionRecord.action_digest
          : "unknown",
      path,
      old_excerpt: oldExcerpt.text,
      new_excerpt: newExcerpt.text,
      truncated: oldExcerpt.truncated || newExcerpt.truncated,
    });
  }
  return diffs;
}
