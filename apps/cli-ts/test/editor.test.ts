/**
 * External-editor bridge tests — real spawn against a tiny stub editor so
 * the contract (round-trip, trailing-newline strip, graceful absence) is
 * proven rather than mocked.
 */
import assert from "node:assert/strict";
import { chmodSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { openExternalEditor } from "../src/editor.js";

function stubEditor(script: string): string {
  const dir = mkdtempSync(join(tmpdir(), "cli-ts-editor-"));
  const file = join(dir, "editor.sh");
  writeFileSync(file, `#!/bin/sh\n${script}\n`, "utf8");
  chmodSync(file, 0o755);
  return file;
}

test("round-trips text through the editor and strips the trailing newline", () => {
  const editor = stubEditor('printf "edited line\\n" > "$1"');
  const result = openExternalEditor("original", { editor });
  assert.ok(result);
  assert.equal(result?.text, "edited line");
  assert.equal(result?.changed, true);
});

test("reports changed=false when the editor leaves the buffer untouched", () => {
  const editor = stubEditor('true');
  const result = openExternalEditor("same text", { editor });
  assert.ok(result);
  assert.equal(result?.text, "same text");
  assert.equal(result?.changed, false);
});

test("supports an editor command with arguments", () => {
  const editor = stubEditor('printf "%s" "$1" > /dev/null');
  const result = openExternalEditor("x", { editor: `sh ${editor}` });
  assert.equal(result?.text, "x");
});

test("returns null when no editor is configured or the binary is missing", () => {
  assert.equal(openExternalEditor("x", { editor: "" }), null);
  assert.equal(openExternalEditor("x", { editor: "definitely-not-an-editor-xyz" }), null);
});
