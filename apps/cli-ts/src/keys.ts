/**
 * Global keybindings, extracted as a pure dispatch so the semantics are
 * unit-testable without a renderer. Shared by the full-screen view
 * (`src/opentui/app.tsx`, "global" layer).
 *
 * Frozen mapping (mainstream parity, adapted to frozen correction semantics):
 *   Esc    streaming/stalled → interrupt() (correction, same as Ctrl-C);
 *          idle/awaiting_approval → no-op (approvals stay explicit y/n —
 *          a durable REJECT must never fire from a stray key)
 *   Ctrl-C streaming/stalled → interrupt(); idle → close.
 *          In the running full-screen TUI the renderer's own Ctrl-C handling
 *          exits the process first (a pty check asserts exit code 0), so Esc is
 *          the live correction key; this branch is retained for callers that
 *          disable that and is covered by keys.test.
 *   Ctrl-X streaming/stalled → stopTurn() (the real durable session PAUSE).
 *          Distinct from Esc on purpose: Esc writes a correction epoch, Ctrl-X
 *          moves the Run to PAUSED so the turn ENDS (`stopped_by_operator`) and
 *          stays stopped until an explicit resume. Routed here from every layer
 *          by `resolveViewKey`, so an operator who is mid-search, mid-picker or
 *          inside vim normal mode can still stop the run.
 *   Ctrl-L clear the local view (same semantics as /clear)
 */
import type { TuiController } from "./controller.js";

export interface KeyLike {
  ctrl?: boolean;
  escape?: boolean;
}

/** Returns true when the key was consumed here (caller skips further handling). */
export function handleGlobalKey(
  controller: TuiController,
  input: string,
  key: KeyLike,
): boolean {
  if (key.ctrl && input === "x") {
    // Fire-and-forget, like Esc: stopTurn reports every outcome on the
    // transcript itself (including a rejection), so the handler only has to
    // keep a rejection from becoming an unhandled promise.
    void controller.stopTurn().catch(() => undefined);
    return true;
  }
  if (key.ctrl && input === "c") {
    void controller.interrupt().catch(() => undefined);
    return true;
  }
  if (key.escape) {
    if (controller.status === "streaming" || controller.status === "stalled") {
      // The controller reports a failed correction on the transcript itself and
      // still rejects, so this handler only has to keep the rejection from
      // becoming an unhandled promise.
      void controller.interrupt("escape").catch(() => undefined);
    }
    return true; // Esc is always consumed; it never falls through to approval
  }
  if (key.ctrl && input === "l") {
    controller.clearView();
    return true;
  }
  return false;
}
