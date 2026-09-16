/**
 * Pure key-routing resolver for the full-screen view.
 *
 * The view has several key owners and the ORDER matters (selector > approval >
 * frozen global keys > command palette > agents panel > plain submit). An
 * earlier revision wired the palette branches inside the selector branch, which
 * made them dead code and was not caught by tests because the routing lived in
 * the component. Resolving the owner here makes the precedence testable.
 */
export type ViewKeyOwner =
  | { layer: "selector" }
  | { layer: "approval"; action: "approve" | "reject" | "ignore" }
  | { layer: "global" }
  | { layer: "palette"; action: "up" | "down" | "complete" | "submit" | "ignore" }
  | { layer: "agents"; action: "move"; delta: 1 | -1 }
  | { layer: "enter" }
  | { layer: "ignore" };

export interface ViewKeyContext {
  /**
   * A /resume|/theme|/mode picker is open. Any TRUTHY value means open: the
   * controller exposes `pendingSelector` as `null` (not `undefined`) when
   * closed, and `!== undefined` wiring once routed every key to the selector
   * layer and silently disabled Enter/movement.
   */
  selectorOpen: unknown;
  /** A human approval is pending. */
  awaitingApproval: boolean;
  /** The command palette is showing matches. */
  paletteOpen: boolean;
  /** Currently selected panel id. */
  activePanel: string;
  /** opentui key name, e.g. "escape", "return", "tab", "up", "c", "n". */
  name: string;
  ctrl: boolean;
  /** Printable text for this key, if any. */
  sequence: string;
}

export function resolveViewKey(ctx: ViewKeyContext): ViewKeyOwner {
  const { name, ctrl, sequence } = ctx;

  // 1. Selector owns every key while open (so Esc cancels the picker and never
  //    reaches the frozen global mapping).
  if (ctx.selectorOpen) return { layer: "selector" };

  // 2. A pending approval is answered explicitly; nothing else is routed.
  if (ctx.awaitingApproval) {
    if (name === "y") return { layer: "approval", action: "approve" };
    if (name === "n") return { layer: "approval", action: "reject" };
    return { layer: "approval", action: "ignore" };
  }

  // 3. Frozen global keys (Esc correction, Ctrl-C interrupt, Ctrl-L clear).
  if (name === "escape" || (ctrl && (name === "c" || name === "l"))) {
    return { layer: "global" };
  }

  // 4. Command palette beats the agents panel: typing "/st" + Enter must run the
  //    highlighted command, not switch sessions.
  if (ctx.paletteOpen) {
    if (name === "up") return { layer: "palette", action: "up" };
    if (name === "down") return { layer: "palette", action: "down" };
    if (name === "tab") return { layer: "palette", action: "complete" };
    if (name === "return") return { layer: "palette", action: "submit" };
    return { layer: "palette", action: "ignore" };
  }

  // 5. The agents panel owns list movement (ctrl+arrows / ctrl+p|n).
  if (ctx.activePanel === "agents" && ctrl && ["up", "down", "p", "n"].includes(name)) {
    return { layer: "agents", action: "move", delta: name === "down" || name === "n" ? 1 : -1 };
  }
  if (ctx.activePanel === "agents" && (name === "up" || name === "down")) {
    return { layer: "agents", action: "move", delta: name === "down" ? 1 : -1 };
  }

  // 6. Plain Enter submits the composer.
  if (name === "return") return { layer: "enter" };

  // 7. Anything else (letters, plain arrows) belongs to the composer input.
  void sequence;
  return { layer: "ignore" };
}
