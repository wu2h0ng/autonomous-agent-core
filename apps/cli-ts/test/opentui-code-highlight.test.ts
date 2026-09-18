/**
 * #16 tests: fenced-code highlighting ranges + the SyntaxStyle scope table.
 *
 * These cover the pure half of the fix — what ranges we hand opentui and which
 * scope names we register for them. Whether the frame actually renders colour
 * is asserted end-to-end by scripts/pty_highlight_check.py.
 */
import assert from "node:assert/strict";
import test from "node:test";
import type { SimpleHighlight } from "@opentui/core";
import {
  codeHighlightRanges,
  DIM_SCOPES,
  fenceLanguage,
  highlightStyleTable,
} from "../src/opentui/code-highlight.js";
import { viewTheme } from "../src/opentui/theme-colors.js";

/** Exactly the fenced block the hermetic stub (scripts/dev_daemon.py) emits. */
const FIXTURE = [
  "# highlighted fixture for the syntax-scope check",
  "def greet(name: str) -> str:",
  '    return "hello " + name',
].join("\n");

const slice = (content: string, range: SimpleHighlight): string =>
  content.slice(range[0], range[1]);

test("fenceLanguage resolves aliases, extensions and rejects unknown info strings", () => {
  assert.equal(fenceLanguage("python"), "python");
  assert.equal(fenceLanguage("py"), "python"); // fence alias -> canonical id
  assert.equal(fenceLanguage("ts"), "typescript");
  assert.equal(fenceLanguage("TypeScript"), "typescript");
  assert.equal(fenceLanguage("  bash  "), "bash");
  assert.equal(fenceLanguage("sh"), "bash");
  assert.equal(fenceLanguage("yml"), "yaml");
  assert.equal(fenceLanguage("py title=x"), "python"); // info string tail ignored
  assert.equal(fenceLanguage("definitely-not-a-language"), undefined);
  assert.equal(fenceLanguage(""), undefined);
  assert.equal(fenceLanguage(undefined), undefined);
});

test("highlightStyleTable covers the emitted vocabulary plus a default", () => {
  const table = highlightStyleTable(viewTheme("default"));
  assert.ok(table.default, "a `default` scope is required for unstyled spans");
  for (const scope of ["keyword", "string", "comment", "title", "number", "built_in"]) {
    assert.ok(table[scope], `missing style for ${scope}`);
    assert.match(table[scope].fg, /^#[0-9a-f]{6}$/i);
  }
  for (const scope of DIM_SCOPES) {
    assert.equal(table[scope]?.dim, true, `${scope} should be dim`);
  }
  // keyword and function must not collapse onto the same colour by accident
  assert.notEqual(table.keyword?.fg, table.title?.fg);
});

test("highlightStyleTable follows the active theme", () => {
  const dark = highlightStyleTable(viewTheme("default"));
  const ansi = highlightStyleTable(viewTheme("ansi"));
  assert.notEqual(dark.keyword?.fg, ansi.keyword?.fg);
});

test("codeHighlightRanges finds python keywords, strings and comments", () => {
  const ranges = codeHighlightRanges(FIXTURE, "python");
  assert.ok(ranges.length > 0, "expected highlights for a python fence");

  for (const range of ranges) {
    assert.ok(range[0] < range[1], "empty range");
    assert.ok(range[1] <= FIXTURE.length, "range past end of content");
  }

  const byScope = (scope: string): string[] =>
    ranges.filter((r) => r[2] === scope).map((r) => slice(FIXTURE, r));

  assert.ok(byScope("keyword").includes("def"));
  assert.ok(byScope("keyword").includes("return"));
  assert.ok(byScope("string").some((text) => text.includes('"hello "')));
  assert.ok(byScope("comment").some((text) => text.startsWith("#")));
  assert.ok(byScope("title").includes("greet"));
});

test("codeHighlightRanges fails soft on unknown or missing languages", () => {
  assert.deepEqual(codeHighlightRanges(FIXTURE, undefined), []);
  assert.deepEqual(codeHighlightRanges(FIXTURE, ""), []);
  assert.deepEqual(codeHighlightRanges(FIXTURE, "definitely-not-a-language"), []);
  // plain text in a known language still yields a usable (possibly empty) list
  assert.ok(Array.isArray(codeHighlightRanges("plain prose", "python")));
});
