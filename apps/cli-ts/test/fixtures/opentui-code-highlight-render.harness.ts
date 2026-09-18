/**
 * Bun-only render harness: does a fenced code block reach the screen with OUR
 * highlight colours?
 *
 * Why a fixture and not a test file: `captureSpans()` needs OpenTUI's native
 * renderer, which only bun can load (under node, `@opentui/core` resolves to the
 * stub whose `CliRenderer` throws "OpenTUI native FFI is not available for this
 * runtime"). `npm test` runs under plain node, so `test/opentui-code-highlight-
 * glue.test.ts` spawns THIS file with bun and fails if it exits non-zero.
 *
 * The gap it closes: `codeBlockRenderNode()` is the glue that hands
 * `codeHighlightRanges()` to `CodeRenderable.onHighlight`. Deleting that
 * assignment (`code.onHighlight = …`, src/opentui/code-highlight.ts) left the
 * whole suite green: `opentui-code-highlight.test.ts` only checks the ranges and
 * the scope table, and `npm run check:highlight` is a manual script outside the
 * test gate. The negative control below (same document, no renderNode hook) keeps
 * the check falsifiable rather than passing on any unhighlighted block.
 *
 * Scope note: this asserts the same measured fact as
 * `scripts/highlight_render_check.ts` (which additionally covers the PTY byte
 * stream); that script is a manual check, this harness is the one the test suite
 * runs. Run directly: bun run test/fixtures/opentui-code-highlight-render.harness.ts
 */
import assert from "node:assert/strict";
import { MarkdownRenderable, SyntaxStyle, type MarkdownOptions } from "@opentui/core";
import { createTestRenderer } from "@opentui/core/testing";
import { codeBlockRenderNode, highlightStyleTable } from "../../src/opentui/code-highlight.js";
import { viewTheme } from "../../src/opentui/theme-colors.js";

/** Exactly the fenced block the hermetic stub (scripts/dev_daemon.py) emits. */
const FIXTURE = [
  "# highlighted fixture for the syntax-scope check",
  "def greet(name: str) -> str:",
  '    return "hello " + name',
].join("\n");

const DOCUMENT = "cli-ts deterministic reply\n\n```python\n" + FIXTURE + "\n```\n";

/** How long the async highlight pass may take before the harness gives up. */
const SETTLE_BUDGET_MS = 5_000;

interface Span {
  text: string;
  fg: unknown;
}

const toHex = (value: unknown): string => {
  const buffer = (value as { buffer?: ArrayLike<number> })?.buffer;
  if (buffer === undefined || buffer.length < 3) return "(none)";
  return (
    "#" +
    [buffer[0] ?? 0, buffer[1] ?? 0, buffer[2] ?? 0]
      .map((channel) => channel.toString(16).padStart(2, "0"))
      .join("")
  );
};

async function renderRows(renderNode: MarkdownOptions["renderNode"] | undefined) {
  const setup = await createTestRenderer({ width: 100, height: 26 });
  const capture = (): { lines: Array<{ spans: Span[] }> } =>
    setup.captureSpans() as { lines: Array<{ spans: Span[] }> };
  const theme = viewTheme("default");
  const syntaxStyle = SyntaxStyle.create();
  for (const [scope, definition] of Object.entries(highlightStyleTable(theme))) {
    syntaxStyle.registerStyle(scope, definition);
  }
  const options: MarkdownOptions = {
    content: DOCUMENT,
    syntaxStyle,
    fg: theme.assistant,
    width: "100%",
  };
  if (renderNode !== undefined) options.renderNode = renderNode;
  setup.renderer.root.add(new MarkdownRenderable(setup.renderer, options));
  /**
   * Is the frame settled enough to assert on?
   *
   * With the hook installed, the block is laid out in one pass and coloured in
   * a later one (the highlight pass is async and goes through the native
   * tree-sitter worker), so waiting for the TEXT alone raced the colour: under
   * `npm test`, where 30 test files render at once, the code arrived uncoloured
   * and the capture showed no `def` span of its own. `waitFor`/
   * `waitForVisualIdle` cannot be used for this: they give up as soon as the
   * render scheduler goes idle, which it does while the worker is still running.
   * The negative control has no colour to wait for, so it waits for the block.
   */
  const settled = (): boolean => {
    const spans = capture().lines.flatMap((line) => line.spans);
    return renderNode === undefined
      ? spans.some((span) => span.text.includes("greet(name"))
      : spans.some((span) => span.text.trim() === "def" && toHex(span.fg) === theme.accent);
  };
  const deadline = Date.now() + SETTLE_BUDGET_MS;
  while (!settled() && Date.now() < deadline) {
    await setup.flush({ maxPasses: 60 });
    await new Promise((resolve) => setTimeout(resolve, 10));
  }
  await setup.waitForVisualIdle({ quietFrames: 3, maxFrames: 200 }).catch(() => undefined);
  await setup.flush({ maxPasses: 60 });

  try {
    const frame = capture();
    const text = frame.lines.map((line) => line.spans.map((span) => span.text).join(""));
    const spans = frame.lines.flatMap((line) =>
      line.spans
        .filter((span) => span.text.trim() !== "")
        .map((span) => ({
          text: span.text.trim(),
          fg: toHex(span.fg),
        })),
    );
    return { theme, spans, text: text.join("\n") };
  } finally {
    setup.renderer.destroy();
  }
}

async function main(): Promise<void> {
  const { theme, spans, text } = await renderRows(codeBlockRenderNode());
  const colourOf = (token: string): string | undefined =>
    spans.find((span) => span.text === token)?.fg;

  // Every one of these tokens is highlighted by OUR ranges: tree-sitter has no
  // python grammar in this bundle, so without them each token keeps the default
  // assistant colour - which is exactly what the negative control shows.
  const EXPECTED: Array<[string, string, string]> = [
    ["def", theme.accent, "keyword"],
    ["return", theme.accent, "keyword"],
    ['"hello "', theme.toolDone, "string"],
    ["greet(name: str) -> str:", theme.toolPending, "title/params"],
    ["# highlighted fixture for the syntax-scope check", theme.notice, "comment"],
  ];
  for (const [token, expected, label] of EXPECTED) {
    assert.equal(
      colourOf(token),
      expected,
      `${label} ${JSON.stringify(token)} should render as ${expected}, got ${colourOf(token)}`,
    );
  }
  assert.notEqual(
    theme.accent,
    theme.assistant,
    "the keyword colour must differ from the default, or this check cannot discriminate",
  );

  // Colouring must not mangle the block: every source line survives verbatim.
  for (const line of FIXTURE.split("\n")) {
    assert.ok(text.includes(line), `code line missing from the frame: ${JSON.stringify(line)}`);
  }
  // A scope we deliberately left unmapped keeps the default colour.
  assert.equal(colourOf("+ name"), theme.assistant, "unscoped text must stay the default colour");

  // --- negative control: without the hook the python block gets no colour -----
  const without = await renderRows(undefined);
  const controls = without.spans.filter((span) => /def|return|hello|highlighted/.test(span.text));
  assert.ok(controls.length > 0, "the negative control found no code tokens to compare");
  for (const span of controls) {
    assert.equal(
      span.fg,
      without.theme.assistant,
      `negative control (no renderNode hook) should be uncoloured: ${JSON.stringify(span.text)} was ${span.fg}`,
    );
  }

  console.log("OPENTUI_CODE_HIGHLIGHT_RENDER_HARNESS: PASS");
  console.log(`  keyword -> ${theme.accent} · string -> ${theme.toolDone}`);
  console.log(`  title   -> ${theme.toolPending} · comment -> ${theme.notice}`);
}

try {
  await main();
  process.exit(0);
} catch (error) {
  console.error("OPENTUI_CODE_HIGHLIGHT_RENDER_HARNESS: FAIL");
  console.error(error instanceof Error ? (error.stack ?? error.message) : String(error));
  process.exit(1);
}
