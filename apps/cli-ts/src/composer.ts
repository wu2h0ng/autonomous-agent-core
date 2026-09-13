/**
 * Composer text buffer — pure, cursor-aware, multi-line.
 *
 * ink-text-input@6 is single-line, so the TUI owns editing. Keeping this
 * module free of Ink/terminal imports makes the semantics unit-testable and
 * keeps App.tsx a thin key-router. Cursor indices are UTF-16 code units, but
 * movement and deletion are code-point aware so emoji/CJK behave.
 */

export interface ComposerState {
  value: string;
  /** Insertion point, 0..value.length. */
  cursor: number;
}

export type MoveDirection = "left" | "right" | "home" | "end" | "up" | "down";

function clamp(cursor: number, value: string): number {
  return Math.max(0, Math.min(value.length, cursor));
}

function isHighSurrogate(code: number): boolean {
  return code >= 0xd800 && code <= 0xdbff;
}

function isLowSurrogate(code: number): boolean {
  return code >= 0xdc00 && code <= 0xdfff;
}

/** Code units occupied by the glyph ending at `index` (>=1). */
function glyphBefore(value: string, index: number): number {
  if (index >= 2 && isLowSurrogate(value.charCodeAt(index - 1)) && isHighSurrogate(value.charCodeAt(index - 2))) {
    return 2;
  }
  return 1;
}

/** Code units occupied by the glyph starting at `index` (>=1). */
function glyphAt(value: string, index: number): number {
  if (
    index + 1 < value.length &&
    isHighSurrogate(value.charCodeAt(index)) &&
    isLowSurrogate(value.charCodeAt(index + 1))
  ) {
    return 2;
  }
  return 1;
}

export function insertText(state: ComposerState, text: string): ComposerState {
  if (!text) return state;
  const cursor = clamp(state.cursor, state.value);
  return {
    value: state.value.slice(0, cursor) + text + state.value.slice(cursor),
    cursor: cursor + text.length,
  };
}

export function insertNewline(state: ComposerState): ComposerState {
  return insertText(state, "\n");
}

export function backspace(state: ComposerState): ComposerState {
  const cursor = clamp(state.cursor, state.value);
  if (cursor === 0) return { value: state.value, cursor: 0 };
  const glyph = glyphBefore(state.value, cursor);
  return {
    value: state.value.slice(0, cursor - glyph) + state.value.slice(cursor),
    cursor: cursor - glyph,
  };
}

export function deleteForward(state: ComposerState): ComposerState {
  const cursor = clamp(state.cursor, state.value);
  if (cursor >= state.value.length) return { value: state.value, cursor };
  const glyph = glyphAt(state.value, cursor);
  return {
    value: state.value.slice(0, cursor) + state.value.slice(cursor + glyph),
    cursor,
  };
}

function lineStartOffset(value: string, line: number): number {
  let offset = 0;
  for (let i = 0; i < line; i += 1) {
    const next = value.indexOf("\n", offset);
    if (next === -1) return value.length;
    offset = next + 1;
  }
  return offset;
}

export function cursorLineCol(state: ComposerState): { line: number; column: number } {
  const cursor = clamp(state.cursor, state.value);
  const before = state.value.slice(0, cursor);
  const line = (before.match(/\n/g) ?? []).length;
  const lineStart = before.lastIndexOf("\n") + 1;
  return { line, column: cursor - lineStart };
}

export function move(state: ComposerState, direction: MoveDirection): ComposerState {
  const value = state.value;
  const cursor = clamp(state.cursor, value);
  switch (direction) {
    case "left":
      return { value, cursor: cursor === 0 ? 0 : cursor - glyphBefore(value, cursor) };
    case "right":
      return { value, cursor: cursor >= value.length ? value.length : cursor + glyphAt(value, cursor) };
    case "home":
      return { value, cursor: value.lastIndexOf("\n", cursor - 1) + 1 };
    case "end": {
      const next = value.indexOf("\n", cursor);
      return { value, cursor: next === -1 ? value.length : next };
    }
    case "up":
    case "down": {
      const lines = value.split("\n");
      const { line, column } = cursorLineCol({ value, cursor });
      const target = direction === "up" ? line - 1 : line + 1;
      if (target < 0 || target >= lines.length) return { value, cursor };
      const targetLength = lines[target]?.length ?? 0;
      return { value, cursor: lineStartOffset(value, target) + Math.min(column, targetLength) };
    }
  }
}

export function lineCount(value: string): number {
  return value.split("\n").length;
}

export type WordMotion = "forward" | "backward" | "end";

/** Vim-style word motions over the whole buffer (newlines count as space).
 * Code-point aware: the cursor always lands on a grapheme boundary. */
export function moveWord(state: ComposerState, motion: WordMotion): ComposerState {
  const value = state.value;
  const cursor = clamp(state.cursor, value);
  const isWord = (index: number): boolean =>
    index >= 0 && index < value.length && !/\s/.test(value[index] as string);
  const forward = (index: number): number => index + glyphAt(value, index);
  const backward = (index: number): number => index - glyphBefore(value, index);

  if (motion === "forward") {
    let i = cursor;
    while (i < value.length && isWord(i)) i = forward(i);
    while (i < value.length && !isWord(i)) i = forward(i);
    return { value, cursor: i };
  }
  if (motion === "backward") {
    let i = cursor;
    do {
      i = backward(i);
    } while (i > 0 && !isWord(i));
    if (!isWord(i)) return { value, cursor };
    while (i > 0 && isWord(backward(i))) i = backward(i);
    return { value, cursor: i };
  }
  // end: end of current word if not already there, else end of the next word
  let i = cursor;
  if (isWord(i) && !isWord(forward(i))) i = forward(i);
  while (i < value.length && !isWord(i)) i = forward(i);
  if (i >= value.length) return { value, cursor };
  while (i < value.length && isWord(i)) i = forward(i);
  return { value, cursor: Math.max(cursor, backward(i)) };
}

export function isMultiline(state: ComposerState): boolean {
  return state.value.includes("\n");
}

/** Remove [start, end) and place the cursor at `start` (clamped). */
function deleteRange(state: ComposerState, start: number, end: number): ComposerState {
  if (end <= start) return state;
  const value = state.value.slice(0, start) + state.value.slice(end);
  return { value, cursor: clamp(start, value) };
}

/** vim `dw` — delete from the cursor to the start of the next word. */
export function deleteWordForward(state: ComposerState): ComposerState {
  const cursor = clamp(state.cursor, state.value);
  return deleteRange(state, cursor, moveWord({ value: state.value, cursor }, "forward").cursor);
}

/** vim `d$` — delete from the cursor to the end of the line. */
export function deleteToLineEnd(state: ComposerState): ComposerState {
  const cursor = clamp(state.cursor, state.value);
  return deleteRange(state, cursor, move({ value: state.value, cursor }, "end").cursor);
}

/** vim `dd` — delete the current logical line (with its newline). */
export function deleteLine(state: ComposerState): ComposerState {
  const value = state.value;
  const cursor = clamp(state.cursor, value);
  const start = value.lastIndexOf("\n", cursor - 1) + 1;
  const end = value.indexOf("\n", cursor);
  if (end !== -1) return deleteRange(state, start, end + 1);
  if (start > 0) {
    // last line: drop the preceding newline and land on the previous line start
    const trimmed = value.slice(0, start - 1);
    return { value: trimmed, cursor: trimmed.lastIndexOf("\n") + 1 };
  }
  return { value: "", cursor: 0 };
}
