/**
 * Unified-diff tests.
 */
import assert from "node:assert/strict";
import test from "node:test";
import { diffLines, previewToDiff } from "../src/diffview.js";

const flat = (lines: { kind: string; text: string }[]): string[] =>
  lines.map((line) => `${line.kind[0]}:${line.text}`);

test("diffLines: context, replacement, addition and deletion", () => {
  assert.deepEqual(flat(diffLines("a\nb\nc", "a\nb\nc")), ["c:a", "c:b", "c:c"]);
  assert.deepEqual(flat(diffLines("a\nb\nc", "a\nX\nc")), ["c:a", "d:b", "a:X", "c:c"]);
  assert.deepEqual(flat(diffLines("a\nc", "a\nb\nc")), ["c:a", "a:b", "c:c"]);
  assert.deepEqual(flat(diffLines("a\nb\nc", "a\nc")), ["c:a", "d:b", "c:c"]);
});

test("diffLines: empty sides", () => {
  assert.deepEqual(flat(diffLines("", "x")), ["a:x"]);
  assert.deepEqual(flat(diffLines("x", "")), ["d:x"]);
  assert.deepEqual(flat(diffLines("", "")), []);
});

test("previewToDiff: keeps the target-path header, fails soft on empty/shapeless previews", () => {
  const preview = "edit fixture.txt\n--- old ---\nhello\n--- new ---\nhello world";
  assert.deepEqual(flat(previewToDiff(preview) ?? []), [
    "c:edit fixture.txt",
    "d:hello",
    "a:hello world",
  ]);
  assert.equal(previewToDiff("no markers here"), null);
  assert.equal(previewToDiff("--- new ---\nx"), null);
  // unchanged old/new -> no diff -> null so the caller falls back, never empty card
  assert.equal(previewToDiff("edit f\n--- old ---\nsame\n--- new ---\nsame"), null);
});
