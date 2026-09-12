/**
 * Terminal attention signals (gap P1 #18). Pure decision + sequence so the
 * trigger logic is testable; App writes the sequence to the terminal.
 *
 * Honesty note: focus detection needs DECSET 1004 which the client does not
 * enable, so the default is a plain bell. Desktop notification is opt-in
 * (`AGENT_OS_NOTIFY=osc`) because OSC 9 support varies by terminal.
 */
export type AttentionKind = "approval" | "turn_done" | "error" | null;

export function attentionFor(
  prevStatus: string,
  nextStatus: string,
  stopReason: string | null,
  lastError: string | null = null,
): AttentionKind {
  if (prevStatus === nextStatus) return null;
  if (nextStatus === "awaiting_approval") return "approval";
  if (nextStatus === "idle" && (prevStatus === "streaming" || prevStatus === "stalled")) {
    // An exception-failed turn has lastStopReason null, so it must be
    // classified from lastError, not silently reported as success.
    if (lastError) return "error";
    return stopReason !== null && stopReason !== "completed" ? "error" : "turn_done";
  }
  return null;
}

export interface AttentionOptions {
  bell?: boolean;
  notify?: boolean;
}

export function attentionSequence(kind: AttentionKind, options: AttentionOptions = {}): string {
  if (!kind) return "";
  const message =
    kind === "approval" ? "approval required" : kind === "error" ? "turn failed" : "turn complete";
  const bell = options.bell === false ? "" : "\u0007";
  const notify = options.notify ? `\u001b]9;Agent OS: ${message}\u0007` : "";
  return bell + notify;
}
