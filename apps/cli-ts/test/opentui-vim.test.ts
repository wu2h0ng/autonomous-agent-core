/**
 * Vim normal-mode tests (vim.ts is pure — no renderer needed).
 * Bypass-detecting: a resolver that ignores the pending operator, maps motions
 * to the wrong composer primitive, or forgets that `c` returns to insert mode
 * fails these.
 */
import assert from "node:assert/strict";
import test from "node:test";
import {
  applyVimAction,
  offsetFromCursor,
  resolveVimKey,
} from "../src/opentui/vim.js";

const draft = { value: "hello world", cursor: 5 };

test("normal-mode entry: i/a/A/I and the motions", () => {
  assert.deepEqual(resolveVimKey("i", null), { kind: "insert" });
  assert.deepEqual(resolveVimKey("a", null), { kind: "insert", move: "right" });
  assert.deepEqual(resolveVimKey("A", null), { kind: "insert", move: "end" });
  assert.deepEqual(resolveVimKey("I", null), { kind: "insert", move: "home" });
  assert.deepEqual(resolveVimKey("h", null), { kind: "move", dir: "left" });
  assert.deepEqual(resolveVimKey("l", null), { kind: "move", dir: "right" });
  assert.deepEqual(resolveVimKey("j", null), { kind: "move", dir: "down" });
  assert.deepEqual(resolveVimKey("k", null), { kind: "move", dir: "up" });
  assert.deepEqual(resolveVimKey("0", null), { kind: "move", dir: "home" });
  assert.deepEqual(resolveVimKey("$", null), { kind: "move", dir: "end" });
  assert.deepEqual(resolveVimKey("w", null), { kind: "moveWord", motion: "forward" });
  assert.deepEqual(resolveVimKey("b", null), { kind: "moveWord", motion: "backward" });
  assert.deepEqual(resolveVimKey("e", null), { kind: "moveWord", motion: "end" });
  assert.deepEqual(resolveVimKey("x", null), { kind: "deleteForward" });
  assert.deepEqual(resolveVimKey("return", null), { kind: "submit" });
  assert.deepEqual(resolveVimKey("q", null), { kind: "ignore" });
});

test("operators: d/c await a motion; dd/dw/d$ do not ignore it", () => {
  assert.deepEqual(resolveVimKey("d", null), { kind: "pending", op: "d" });
  assert.deepEqual(resolveVimKey("c", null), { kind: "pending", op: "c" });
  assert.deepEqual(resolveVimKey("d", "d"), { kind: "operator", op: "d", motion: "d" });
  assert.deepEqual(resolveVimKey("w", "c"), { kind: "operator", op: "c", motion: "w" });
  assert.deepEqual(resolveVimKey("$", "d"), { kind: "operator", op: "d", motion: "$" });
  // An unknown motion cancels the operator (Ink parity).
  assert.deepEqual(resolveVimKey("q", "d"), { kind: "clearPending" });
  assert.deepEqual(resolveVimKey("escape", "c"), { kind: "clearPending" });
});

test("operator application edits the draft and c returns to insert", () => {
  const dd = applyVimAction(draft, { kind: "operator", op: "d", motion: "d" });
  assert.equal(dd.state.value, "");
  assert.equal(dd.insert, false);

  const d0 = applyVimAction(draft, { kind: "operator", op: "c", motion: "$" });
  assert.equal(d0.state.value, "hello");
  assert.equal(d0.insert, true, "change must return to insert mode");

  // x deletes the character under the caret; i/a enter insert mode.
  assert.equal(
    applyVimAction({ value: "abc", cursor: 1 }, { kind: "deleteForward" }).state.value,
    "ac",
  );
  const a = applyVimAction(draft, { kind: "insert", move: "right" });
  assert.deepEqual(a, { state: { value: "hello world", cursor: 6 }, insert: true });
  const I = applyVimAction(draft, { kind: "insert", move: "home" });
  assert.deepEqual(I, { state: { value: "hello world", cursor: 0 }, insert: true });
});

test("offsetFromCursor maps a logical caret to an offset", () => {
  const text = "ab\ncde";
  assert.equal(offsetFromCursor(text, 0, 0), 0);
  assert.equal(offsetFromCursor(text, 0, 2), 2);
  assert.equal(offsetFromCursor(text, 1, 0), 3);
  assert.equal(offsetFromCursor(text, 1, 2), 5);
  // Out-of-range clamps to the end of the text instead of throwing.
  assert.equal(offsetFromCursor(text, 9, 99), text.length);
});
