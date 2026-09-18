/**
 * Headless check: do fenced code blocks reach the screen with theme colours?
 *
 * Complements scripts/pty_highlight_check.py. The PTY check proves the colours
 * survive the real byte stream, but a 256-colour terminal reports palette RGB
 * and stale-cell artifacts need interpreting. This one drives opentui's own
 * TestRenderer and reads the renderer's cell buffer directly, so it can assert
 * the EXACT scope -> colour mapping.
 *
 * It also runs a negative control: the same document rendered WITHOUT the
 * renderNode hook must produce no coloured code tokens. That keeps the check
 * falsifiable — if `codeBlockRenderNode` stopped being wired up, the positive
 * half would fail rather than silently passing on an unhighlighted block.
 *
 * Must run under bun (the OpenTUI native renderer has no node FFI):
 *     bun run scripts/highlight_render_check.ts
 */
import { MarkdownRenderable, SyntaxStyle, type MarkdownOptions } from "@opentui/core";
import { createTestRenderer } from "@opentui/core/testing";
import { codeBlockRenderNode, highlightStyleTable } from "../src/opentui/code-highlight.js";
import { viewTheme } from "../src/opentui/theme-colors.js";

/** Exactly the fenced block the hermetic stub (scripts/dev_daemon.py) emits. */
const FIXTURE = [
  "# highlighted fixture for the syntax-scope check",
  "def greet(name: str) -> str:",
  '    return "hello " + name',
].join("\n");

const DOCUMENT = "cli-ts deterministic reply\n\n```python\n" + FIXTURE + "\n```\n";

interface Span {
  text: string;
  fg: unknown;
  attributes: number;
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

/** Render the document and return the non-blank span text on each row. */
async function renderRows(renderNode: MarkdownOptions["renderNode"] | undefined) {
  const setup = await createTestRenderer({ width: 100, height: 26 });
  const theme = viewTheme("default");
  const syntaxStyle = SyntaxStyle.create();
  for (const [scope, definition] of Object.entries(highlightStyleTable(theme))) {
    syntaxStyle.registerStyle(scope, definition);
  }
  const options: MarkdownOptions = { content: DOCUMENT, syntaxStyle, fg: theme.assistant, width: "100%" };
  if (renderNode !== undefined) options.renderNode = renderNode;
  setup.renderer.root.add(new MarkdownRenderable(setup.renderer, options));
  await setup.flush({ maxPasses: 60 });
  await setup.waitForVisualIdle({ quietFrames: 3, maxFrames: 120 }).catch(() => undefined);
  await setup.flush({ maxPasses: 60 });

  const frame = setup.captureSpans() as { lines: Array<{ spans: Span[] }> };
  // Raw per-row text (whitespace included) for content assertions, plus the
  // non-blank spans for colour lookups.
  const text = frame.lines.map((line) => line.spans.map((span) => span.text).join(""));
  const rows = frame.lines.map((line) =>
    line.spans
      .filter((span) => span.text.trim() !== "")
      .map((span) => ({ text: span.text.trim(), fg: toHex(span.fg), attributes: span.attributes })),
  );
  setup.renderer.destroy();
  return { theme, rows, text };
}

const failures: string[] = [];
const expect = (ok: boolean, message: string): void => {
  if (!ok) failures.push(message);
};

const { theme, rows, text } = await renderRows(codeBlockRenderNode());
const flat = rows.flat();
const colourOf = (token: string): string | undefined =>
  flat.find((span) => span.text === token)?.fg;

// --- positive: every scope family lands on its theme token -------------------
expect(colourOf("def") === theme.accent, `def should be accent ${theme.accent}, got ${colourOf("def")}`);
expect(
  colourOf("return") === theme.accent,
  `return should be accent ${theme.accent}, got ${colourOf("return")}`,
);
expect(
  colourOf('"hello "') === theme.toolDone,
  `string should be toolDone ${theme.toolDone}, got ${colourOf('"hello "')}`,
);
expect(
  colourOf("greet(name: str) -> str:") === theme.toolPending,
  `title/params should be toolPending ${theme.toolPending}, got ${colourOf("greet(name: str) -> str:")}`,
);
expect(
  colourOf("# highlighted fixture for the syntax-scope check") === theme.notice,
  "comment should be the notice colour",
);
// the code block must still be there, verbatim — colouring must not mangle it
const rendered = text.join("\n");
for (const line of FIXTURE.split("\n")) {
  expect(rendered.includes(line), `code line missing from the frame: ${JSON.stringify(line)}`);
}
// a scope we deliberately left unmapped keeps the default colour
expect(colourOf("+ name") === theme.assistant, `unscoped text should stay default, got ${colourOf("+ name")}`);

// --- negative control: without the hook the python block gets no colour ------
const without = await renderRows(undefined);
const withoutColours = new Set(
  without.rows
    .flat()
    .filter((span) => /def|return|hello|highlighted/.test(span.text))
    .map((span) => span.fg),
);
expect(
  [...withoutColours].every((fg) => fg === without.theme.assistant),
  `negative control should be uncoloured, saw ${JSON.stringify([...withoutColours])}`,
);

if (failures.length > 0) {
  console.error("HIGHLIGHT_RENDER_CHECK: FAIL");
  for (const failure of failures) console.error(` - ${failure}`);
  process.exit(1);
}
console.log("HIGHLIGHT_RENDER_CHECK: PASS");
console.log(`  keyword -> ${theme.accent} · string -> ${theme.toolDone}`);
console.log(`  title   -> ${theme.toolPending} · comment -> ${theme.notice}`);
process.exit(0);
