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

function isWordChar(char: string | undefined): boolean {
  return char !== undefined && !/\s/.test(char);
}

export type WordMotion = "forward" | "backward" | "end";

/** Vim-style word motions over the whole buffer (newlines count as space). */
export function moveWord(state: ComposerState, motion: WordMotion): ComposerState {
  const value = state.value;
  const cursor = clamp(state.cursor, value);
  if (motion === "forward") {
    let i = cursor;
    while (i < value.length && isWordChar(value[i])) i += 1;
    while (i < value.length && !isWordChar(value[i])) i += 1;
    return { value, cursor: i };
  }
  if (motion === "backward") {
    let i = cursor - 1;
    while (i >= 0 && !isWordChar(value[i])) i -= 1;
    while (i >= 0 && isWordChar(value[i])) i -= 1;
    return { value, cursor: i + 1 };
  }
  // end: skip non-word chars, then move to the last char of the word
  let i = cursor;
  while (i < value.length && !isWordChar(value[i])) i += 1;
  if (i >= value.length) return { value, cursor };
  while (i < value.length && isWordChar(value[i])) i += 1;
  return { value, cursor: i - 1 };
}

export function isMultiline(state: ComposerState): boolean {
  return state.value.includes("\n");
}
