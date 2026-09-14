/**
 * Unified-diff tests.
 */
import assert from "node:assert/strict";
import test from "node:test";
import {
  collectDiffEntries,
  diffLines,
  editArgsToDiff,
  editPathFromArgs,
  hunkStarts,
  previewToDiff,
} from "../src/diffview.js";

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

test("editArgsToDiff: edit-shaped args only; null when nothing changed or not an edit", () => {
  const args = JSON.stringify({ path: "src/a.ts", old_string: "a\nb", new_string: "a\nc" });
  assert.deepEqual(flat(editArgsToDiff(args) ?? []), ["c:a", "d:b", "a:c"]);
  assert.equal(
    editArgsToDiff(JSON.stringify({ path: "x", old_string: "same", new_string: "same" })),
    null,
  );
  assert.equal(editArgsToDiff(JSON.stringify({ command: "ls" })), null);
  assert.equal(editArgsToDiff("not json"), null);
  assert.equal(editPathFromArgs(args), "src/a.ts");
  assert.equal(editPathFromArgs(JSON.stringify({ command: "ls" })), null);
  assert.equal(editPathFromArgs("not json"), null);
});

test("hunkStarts: one start per changed hunk, none for an unchanged run", () => {
  const twoHunks = diffLines("a\nb\nc\nd\ne\nf", "a\nX\nc\nd\ne\nY");
  assert.deepEqual(hunkStarts(twoHunks), [1, 6]);
  assert.deepEqual(hunkStarts(diffLines("a\nb", "a\nb")), []);
  assert.deepEqual(hunkStarts(diffLines("", "x")), [0]);
});

test("collectDiffEntries: pending approval first, then newest edits; bounded and honest", () => {
  const messages = [
    { tool: { capabilityId: "workspace.shell", argsJson: JSON.stringify({ command: "ls" }) } },
    {
      tool: {
        capabilityId: "workspace.edit",
        argsJson: JSON.stringify({ path: "a.ts", old_string: "x", new_string: "y" }),
      },
    },
    {
      tool: {
        capabilityId: "workspace.edit",
        argsJson: JSON.stringify({ path: "b.ts", old_string: "1", new_string: "2" }),
      },
    },
  ];
  const entries = collectDiffEntries(messages, {
    title: "approval · workspace.edit",
    preview: "edit fixture.txt\n--- old ---\nhello\n--- new ---\nhello world",
  });
  assert.equal(entries.length, 3);
  assert.match(entries[0]?.title ?? "", /^approval/);
  assert.equal(entries[0]?.lang, undefined, "unknown extension highlights nothing");
  assert.match(entries[0]?.lines[0]?.text ?? "", /edit fixture\.txt/);
  // newest edit first; shell (no old/new) is never a diff entry
  assert.match(entries[1]?.title ?? "", /b\.ts/);
  assert.equal(entries[1]?.lang, "typescript");
  assert.match(entries[2]?.title ?? "", /a\.ts/);

  // no pending, no edits -> empty (the viewer says so, it does not invent one)
  assert.deepEqual(collectDiffEntries([], null), []);
  assert.deepEqual(
    collectDiffEntries([{ tool: { capabilityId: "workspace.shell", argsJson: "{}" } }], null),
    [],
  );

  // bounds are declared, not silent: caps trim and set `truncated`
  const capped = collectDiffEntries(
    messages,
    { title: "approval", preview: "edit f\n--- old ---\na\nb\n--- new ---\nc\nd" },
    { maxEntries: 1, maxLines: 2 },
  );
  assert.equal(capped.length, 1);
  assert.equal(capped[0]?.truncated, true);
  assert.equal(capped[0]?.lines.length, 2);
});
