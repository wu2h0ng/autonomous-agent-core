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
  | { layer: "panel"; action: "switch" | "scroll"; delta?: -1 | 1 }
  | { layer: "mention"; action: "complete" | "ignore" }
  | { layer: "history"; action: "prev" | "next" }
  | { layer: "editor" }
  | { layer: "vim"; action?: "normal" }
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
  /** An `@` mention list is showing matches. */
  mentionOpen: boolean;
  /** Currently selected panel id. */
  activePanel: string;
  /** Vim is enabled AND the composer is in normal (not insert) mode. */
  vimNormal: boolean;
  /** Vim is enabled and the composer is editing (insert mode). */
  vimInsertMode: boolean;
  /** A turn is streaming/stalled (Esc then belongs to the frozen global layer). */
  streaming: boolean;
  /** opentui key name, e.g. "escape", "return", "tab", "up", "c", "n". */
  name: string;
  ctrl: boolean;
  /** Printable text for this key, if any. */
  sequence: string;
}

export function resolveViewKey(ctx: ViewKeyContext): ViewKeyOwner {
  const { name, ctrl, sequence } = ctx;

  // 0a. Insert mode + Esc leaves vim editing for normal mode (unless a turn is
  //     streaming, where Esc must stay the frozen global correction).
  if (ctx.vimInsertMode && name === "escape" && !ctx.streaming) {
    return { layer: "vim", action: "normal" };
  }

  // 0. Vim normal mode owns every key (the composer is blurred there, so
  //    nothing else can consume them). Esc is the exception while a turn is
  //    streaming: it must still reach the frozen global correction mapping.
  if (ctx.vimNormal) {
    // Esc while streaming and Ctrl-C/Ctrl-L must keep their frozen global
    // meaning even in normal mode (otherwise vim would swallow the exit keys).
    if (name === "escape" && ctx.streaming) return { layer: "global" };
    if (ctrl && (name === "c" || name === "l")) return { layer: "global" };
    return { layer: "vim" };
  }

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
    // OWNED keys only. Printable keys must FALL THROUGH to the composer: an
    // overlay that swallowed them made "/stat" enter just "/" and Enter run the
    // palette's default item (/exit), which exited the app.
    if (name === "up") return { layer: "palette", action: "up" };
    if (name === "down") return { layer: "palette", action: "down" };
    if (name === "tab") return { layer: "palette", action: "complete" };
    if (name === "return") return { layer: "palette", action: "submit" };
  }

  // 5. An open @mention list takes Tab (to complete the path) but leaves other
  //    keys to the composer/history.
  if (ctx.mentionOpen) {
    // Owns Tab (path completion) only; letters keep typing and Enter submits.
    if (name === "tab") return { layer: "mention", action: "complete" };
  }

  // 7. Ctrl-G opens the external editor on the composer draft (Ink parity).
  //    Match the CONTROL BYTE, not the name: opentui reports Ctrl-G as
  //    name="g" with sequence="\u0007", while a plain "g" (name="g",
  //    sequence="g") reaches this resolver whenever the input is blurred (e.g.
  //    after Tab) and must stay composer text, never open an editor.
  if (sequence === "\u0007") return { layer: "editor" };

  // 8. Panel chrome: Tab selects the next panel, PgUp/PgDn scroll it. This must
  //    come after the palette (Tab completes commands while it is open) and
  //    after the frozen globals, but before the agents-panel/Enter handling.
  if (name === "tab") return { layer: "panel", action: "switch" };
  if (name === "pageup") return { layer: "panel", action: "scroll", delta: -1 };
  if (name === "pagedown") return { layer: "panel", action: "scroll", delta: 1 };

  // 7. The agents panel owns list movement (ctrl+arrows / ctrl+p|n).
  if (ctx.activePanel === "agents" && ctrl && ["up", "down", "p", "n"].includes(name)) {
    return { layer: "agents", action: "move", delta: name === "down" || name === "n" ? 1 : -1 };
  }
  if (ctx.activePanel === "agents" && (name === "up" || name === "down")) {
    return { layer: "agents", action: "move", delta: name === "down" ? 1 : -1 };
  }

  // 8. Readline-style history for the composer (only when no panel owns the
  //    arrows, so the agents panel keeps plain up/down).
  if (ctx.activePanel !== "agents" && (name === "up" || name === "down")) {
    return { layer: "history", action: name === "down" ? "next" : "prev" };
  }

  // 9. Enter belongs to the composer (the textarea submits on Enter). The
  //    agents panel is the exception: its Enter resumes the highlighted
  //    session, and the composer is blurred while that panel is selected so the
  //    two can never both fire.
  if (name === "return" && ctx.activePanel === "agents") return { layer: "enter" };

  // 10. Anything else (letters, plain arrows) belongs to the composer input.
  void sequence;
  return { layer: "ignore" };
}
