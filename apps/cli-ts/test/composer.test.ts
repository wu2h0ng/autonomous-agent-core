/**
 * Composer model tests — pure text-buffer editing (multi-line, cursor aware).
 * ink-text-input@6 is single-line, so the TUI owns this logic and it must be
 * provably correct without a terminal.
 */
import assert from "node:assert/strict";
import test from "node:test";
import {
  backspace,
  cursorLineCol,
  deleteForward,
  insertNewline,
  insertText,
  isMultiline,
  lineCount,
  move,
  moveWord,
  type ComposerState,
} from "../src/composer.js";

const at = (value: string, cursor = value.length): ComposerState => ({ value, cursor });
const flat = (state: ComposerState): string => `${state.value}@${state.cursor}`;

test("insertText inserts at the cursor and advances it", () => {
  assert.equal(flat(insertText(at("ac", 1), "b")), "abc@2");
  assert.equal(flat(insertText(at("", 0), "hi")), "hi@2");
  assert.equal(flat(insertText(at("hello", 5), " world")), "hello world@11");
});

test("insertNewline splits the line and moves the cursor down", () => {
  const state = insertNewline(at("ab", 1));
  assert.equal(flat(state), "a\nb@2");
  assert.equal(lineCount(state.value), 2);
  assert.equal(isMultiline(state), true);
  assert.equal(isMultiline(at("one line")), false);
});

test("backspace/deleteForward respect boundaries and are code-point aware", () => {
  assert.equal(flat(backspace(at("abc", 2))), "ac@1");
  assert.equal(flat(backspace(at("abc", 0))), "abc@0"); // start: no-op
  assert.equal(flat(deleteForward(at("abc", 1))), "ac@1");
  assert.equal(flat(deleteForward(at("abc", 3))), "abc@3"); // end: no-op
  // surrogate pair (😀 = 2 code units) deletes as one glyph
  const emoji = insertText(at("", 0), "😀");
  assert.equal(emoji.value.length, 2);
  assert.equal(backspace({ value: emoji.value, cursor: 2 }).value, "");
});

test("move left/right/home/end stay within the line", () => {
  assert.equal(move(at("ab\ncd", 3), "left").cursor, 2); // left crosses onto the previous line's end
  assert.equal(move(at("ab\ncd", 2), "left").cursor, 1);
  assert.equal(move(at("ab\ncd", 2), "right").cursor, 3); // right crosses onto the next line
  assert.equal(move(at("ab\ncd", 4), "home").cursor, 3);
  assert.equal(move(at("ab\ncd", 3), "end").cursor, 5);
});

test("move up/down preserves the column and clamps to shorter lines", () => {
  const value = "long line\nab\nthird";
  // from line 2 col 1 (cursor 11) up to the longer line 1 keeps col 1
  assert.deepEqual(cursorLineCol(move(at(value, 11), "up")), { line: 0, column: 1 });
  // from line 1 col 5 (cursor 5) down to the 2-char line clamps to its end (cursor 12)
  assert.deepEqual(cursorLineCol(move(at(value, 5), "down")), { line: 1, column: 2 });
  // up on the first line is a no-op
  assert.equal(move(at(value, 3), "up").cursor, 3);
});

test("cursorLineCol reports zero-based line and column across lines", () => {
  assert.deepEqual(cursorLineCol(at("a\nbc\ndef", 5)), { line: 2, column: 0 });
  assert.deepEqual(cursorLineCol(at("", 0)), { line: 0, column: 0 });
});

test("moveWord: w/b/e across words and lines", () => {
  const text = "hello world foo";
  assert.equal(moveWord(at(text, 0), "forward").cursor, 6); // w -> "world"
  assert.equal(moveWord(at(text, 6), "backward").cursor, 0); // b -> "hello"
  assert.equal(moveWord(at(text, 0), "end").cursor, 4); // e -> end of "hello"
  assert.equal(moveWord(at(text, 6), "end").cursor, 10); // e -> end of "world"
  // already at a word end: e advances to the NEXT word's end (not stuck)
  assert.equal(moveWord(at(text, 4), "end").cursor, 10);
  assert.equal(moveWord(at(text, 10), "end").cursor, 14);
  assert.equal(moveWord(at(text, 14), "end").cursor, 14); // stays at the final word end
  // astral glyphs never land mid-surrogate
  assert.equal(moveWord(at("😀 hi", 0), "end").cursor, 4);
  // end at/beyond the final word stays put
  assert.equal(moveWord(at(text, 4), "forward").cursor, 6);
  assert.equal(moveWord(at(text, text.length), "forward").cursor, text.length);
  // newline is whitespace
  assert.equal(moveWord(at("ab\ncd", 0), "forward").cursor, 3);
  assert.equal(moveWord(at("ab\ncd", 4), "backward").cursor, 3);
  // backward at the start is a no-op
  assert.equal(moveWord(at(text, 0), "backward").cursor, 0);
});
