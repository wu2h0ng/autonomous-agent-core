/**
 * Syntax-highlight tests (ANSI asserted with FORCE_COLOR set before import).
 */
import assert from "node:assert/strict";
import test from "node:test";

// cli-highlight (chalk) samples the env at import time; set it before the
// dynamic import so ANSI is asserted for real.
process.env.FORCE_COLOR = "1";

const stripAnsi = (value: string): string => value.replace(/\u001b\[[0-9;]*m/g, "");

test("languageForPath maps common extensions", () => {
  return import("../src/highlight.js").then(({ languageForPath }) => {
    assert.equal(languageForPath("src/a.ts"), "typescript");
    assert.equal(languageForPath("x/README.md"), "markdown");
    assert.equal(languageForPath("noext"), undefined);
    assert.equal(languageForPath("weird.unknown"), undefined);
  });
});

test("highlightCode emits ANSI for known languages and fails soft otherwise", async () => {
  const { highlightCode } = await import("../src/highlight.js");
  const out = highlightCode("const x: number = 1;", "typescript");
  assert.ok(/\u001b\[/.test(out), "expected ANSI styling");
  assert.ok(stripAnsi(out).includes("const x"));
  assert.equal(highlightCode("plain text", undefined), "plain text");
  // unknown language: never throws, content preserved verbatim
  assert.ok(stripAnsi(highlightCode("some text", "definitely-not-a-language")).includes("some text"));
});
