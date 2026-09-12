/**
 * Global keybindings, extracted from App.tsx as a pure dispatch so the
 * semantics are unit-testable without an Ink renderer.
 *
 * Frozen mapping (mainstream parity, adapted to frozen correction semantics):
 *   Esc    streaming/stalled → interrupt() (correction, same as Ctrl-C);
 *          idle/awaiting_approval → no-op (approvals stay explicit y/n —
 *          a durable REJECT must never fire from a stray key)
 *   Ctrl-C streaming/stalled → interrupt(); idle → close. NOTE: Ink's default
 *          exitOnCtrlC intercepts Ctrl-C before this handler in the running
 *          TUI, so Esc is the live correction key; this branch is retained
 *          for renders that disable exitOnCtrlC and is covered by keys.test.
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
  if (key.ctrl && input === "c") {
    void controller.interrupt().catch(() => undefined);
    return true;
  }
  if (key.escape) {
    if (controller.status === "streaming" || controller.status === "stalled") {
      void controller.interrupt().catch(() => undefined);
    }
    return true; // Esc is always consumed; it never falls through to approval
  }
  if (key.ctrl && input === "l") {
    controller.clearView();
    return true;
  }
  return false;
}
