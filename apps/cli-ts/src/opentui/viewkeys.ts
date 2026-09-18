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
  | { layer: "search"; action: "open" | "up" | "down" | "pick" | "cancel" | "ignore" }
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
  /**
   * The Ctrl-R reverse history search is open. Any truthy value means open
   * (same convention as `selectorOpen`).
   */
  searchOpen: unknown;
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
  //     streaming, where Esc must stay the frozen global correction, or the
  //     Ctrl-R overlay is open, where Esc is the overlay's own cancel — taking
  //     it here left the search up and the NEXT key routed to normal mode, so
  //     the overlay became unreachable).
  if (ctx.vimInsertMode && name === "escape" && !ctx.streaming && !ctx.searchOpen) {
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

  // 1b. Ctrl-R reverse search (#14). The QUERY lives in the composer, so only
  //     the keys the overlay itself owns are intercepted and printable keys
  //     fall through to the composer (the same rule the palette follows, and
  //     the same rule that fixes the /exit trap: an overlay must never eat
  //     characters). Tab/PgUp/PgDn are swallowed rather than switching panels
  //     mid-search, which is what Ink does with every unhandled key here.
  if (ctx.searchOpen) {
    if (name === "up") return { layer: "search", action: "up" };
    if (name === "down") return { layer: "search", action: "down" };
    if (name === "return") return { layer: "search", action: "pick" };
    if (name === "escape") return { layer: "search", action: "cancel" };
    // Keys that would otherwise change mode mid-search: Tab/PgUp/PgDn move
    // panels, Ctrl-R would re-enter (and reset) the search, Ctrl-G would hand
    // the query to an external editor. Ink swallows every unlisted key here;
    // these three would be side effects rather than "no-op".
    if (name === "tab" || name === "pageup" || name === "pagedown") {
      return { layer: "search", action: "ignore" };
    }
    if (sequence === "\u0012" || sequence === "\u0007") {
      return { layer: "search", action: "ignore" };
    }
    // Everything else (printable text, backspace) edits the QUERY in the
    // composer, so it must keep falling through rather than return early.
  }

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

  // 7c. Ctrl-R opens the reverse history search (#14). Measured with opentui's
  //     own parser (spike/key-sequence-probe.ts): 0x12 -> name="r" ctrl=true
  //     sequence="\u0012". Both forms are accepted so a plain "r" — which
  //     reaches this resolver whenever the textarea is blurred — can never open
  //     it, which is the property that actually matters.
  if (sequence === "\u0012" || (ctrl && name === "r")) {
    return { layer: "search", action: "open" };
  }

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
