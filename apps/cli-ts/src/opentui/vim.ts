/**
 * Vim modal layer (normal mode) — pure so the key map is testable.
 *
 * Mirrors the frozen Ink keymap (src/App.tsx vim block): motions h/j/k/l/0/$/w/b/e,
 * x, operators d/c with dd/dw/d$, insert entry i/a/A/I, Enter submits. The view
 * supplies the textarea text + caret and applies the returned edit through
 * composer.ts primitives.
 */
import {
  deleteForward,
  deleteLine,
  deleteToLineEnd,
  deleteWordForward,
  move,
  moveWord,
  type ComposerState,
} from "../composer.js";

export type VimOperator = "d" | "c" | null;

export type VimAction =
  | { kind: "insert"; move?: "right" | "end" | "home" }
  | { kind: "pending"; op: "d" | "c" }
  | { kind: "operator"; op: "d" | "c"; motion: "d" | "w" | "$" }
  | { kind: "move"; dir: "left" | "right" | "up" | "down" | "home" | "end" }
  | { kind: "moveWord"; motion: "forward" | "backward" | "end" }
  | { kind: "deleteForward" }
  | { kind: "submit" }
  | { kind: "clearPending" }
  | { kind: "ignore" };

/** Normal-mode key -> action. `pending` is the operator awaiting a motion.
 * `shift` matters because opentui LOWERCASES the key name for A-Z and sets
 * shift=true (verified in @opentui/core), so A/I must be recognised via the
 * modifier, not the name. */
export function resolveVimKey(
  name: string,
  pending: VimOperator,
  shift = false,
): VimAction {
  if (pending !== null) {
    if (name === "d" || name === "w" || name === "$") {
      return { kind: "operator", op: pending, motion: name as "d" | "w" | "$" };
    }
    return { kind: "clearPending" }; // an unknown motion cancels the operator
  }
  switch (name) {
    case "escape":
      return { kind: "clearPending" };
    case "d":
      return { kind: "pending", op: "d" };
    case "c":
      return { kind: "pending", op: "c" };
    case "i":
      return shift ? { kind: "insert", move: "home" } : { kind: "insert" };
    case "a":
      return shift ? { kind: "insert", move: "end" } : { kind: "insert", move: "right" };
    case "A":
      return { kind: "insert", move: "end" };
    case "I":
      return { kind: "insert", move: "home" };
    case "h":
    case "left":
      return { kind: "move", dir: "left" };
    case "l":
    case "right":
      return { kind: "move", dir: "right" };
    case "j":
    case "down":
      return { kind: "move", dir: "down" };
    case "k":
    case "up":
      return { kind: "move", dir: "up" };
    case "0":
      return { kind: "move", dir: "home" };
    case "$":
      return { kind: "move", dir: "end" };
    case "w":
      return { kind: "moveWord", motion: "forward" };
    case "b":
      return { kind: "moveWord", motion: "backward" };
    case "e":
      return { kind: "moveWord", motion: "end" };
    case "x":
      return { kind: "deleteForward" };
    case "return":
      return { kind: "submit" };
    default:
      return { kind: "ignore" };
  }
}

export interface VimResult {
  state: ComposerState;
  /** Switch back to insert mode (operator `c`, or i/a/A/I). */
  insert: boolean;
}

/** Apply a resolved normal-mode action to the draft. */
export function applyVimAction(state: ComposerState, action: VimAction): VimResult {
  switch (action.kind) {
    case "insert": {
      const moved =
        action.move === undefined ? state : move(state, action.move);
      return { state: moved, insert: true };
    }
    case "operator": {
      const remove =
        action.motion === "d"
          ? deleteLine
          : action.motion === "w"
            ? deleteWordForward
            : deleteToLineEnd;
      return { state: remove(state), insert: action.op === "c" };
    }
    case "move":
      return { state: move(state, action.dir), insert: false };
    case "moveWord":
      return { state: moveWord(state, action.motion), insert: false };
    case "deleteForward":
      return { state: deleteForward(state), insert: false };
    default:
      return { state, insert: false };
  }
}

/** Caret offset from a logical (row, col) cursor over `text`. */
export function offsetFromCursor(text: string, row: number, col: number): number {
  const lines = text.split("\n");
  const safeRow = Math.min(Math.max(row, 0), Math.max(lines.length - 1, 0));
  let offset = 0;
  for (let i = 0; i < safeRow; i += 1) offset += (lines[i] ?? "").length + 1;
  const line = lines[safeRow] ?? "";
  return offset + Math.min(Math.max(col, 0), line.length);
}
