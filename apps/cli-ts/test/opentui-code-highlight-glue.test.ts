/**
 * Does `codeBlockRenderNode()` really wire OUR highlighter into the code block?
 *
 * The gap this closes (verified by the independent review): deleting the
 * `code.onHighlight = …` assignment in `src/opentui/code-highlight.ts` left the
 * whole suite green. `opentui-code-highlight.test.ts` covers the ranges and the
 * scope table (the pure half), and the rendered half —
 * `scripts/highlight_render_check.ts` / `check:highlight` — is a manual script
 * that `npm test` never runs.
 *
 * Two layers here:
 *  1. the glue contract, driven directly against a stub code renderable (no
 *     renderer needed): the hook is attached, the language reaches `filetype`,
 *     the ranges are ours, and every scope carries a theme colour;
 *  2. the rendered output — that those colours actually land in the frame — which
 *     needs OpenTUI's native renderer and therefore bun, so it runs as the
 *     harness `test/fixtures/opentui-code-highlight-render.harness.ts` (run it
 *     directly with `bun run …` to see the underlying failure).
 */
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import test from "node:test";
import type { SimpleHighlight } from "@opentui/core";
import { codeBlockRenderNode, highlightStyleTable } from "../src/opentui/code-highlight.js";
import { viewTheme } from "../src/opentui/theme-colors.js";

const FIXTURE = [
  "# highlighted fixture for the syntax-scope check",
  "def greet(name: str) -> str:",
  '    return "hello " + name',
].join("\n");

const PACKAGE_ROOT = fileURLToPath(new URL("..", import.meta.url));
const HARNESS = "test/fixtures/opentui-code-highlight-render.harness.ts";
const TIMEOUT_MS = 120_000;

type Hook = (highlights: SimpleHighlight[]) => SimpleHighlight[];

interface CodeStub {
  filetype?: string;
  onHighlight?: Hook;
}

/** The tree-sitter result the block would get without our hook. */
const FROM_TREE_SITTER: SimpleHighlight[] = [[0, 1, "keyword"]];

function renderCode(token: Record<string, unknown>, stub: CodeStub | null) {
  let defaultRenderCalls = 0;
  const returned = codeBlockRenderNode()(token as never, {
    defaultRender: () => {
      defaultRenderCalls += 1;
      return stub as never;
    },
  } as never);
  return { returned, defaultRenderCalls };
}

test("a fenced block with a known language gets our filetype and our ranges", () => {
  const stub: CodeStub = {};
  const { returned, defaultRenderCalls } = renderCode(
    { type: "code", lang: "python", text: FIXTURE },
    stub,
  );
  // defaultRender()'s returnable must be returned verbatim: the markdown
  // renderable destroys a default renderable it does not get back.
  assert.equal(returned, stub, "the default renderable must be returned unchanged");
  assert.equal(defaultRenderCalls, 1, "the default renderable must be asked for exactly once");
  assert.equal(stub.filetype, "python", "a non-empty filetype is what makes the highlight pass run");

  const hook = stub.onHighlight;
  if (typeof hook !== "function") {
    assert.fail("onHighlight must be attached or no colour reaches the block");
  }
  const ours = hook(FROM_TREE_SITTER);

  // Ours, not tree-sitter's: this bundle has no python grammar, so falling back
  // would leave the whole block uncoloured.
  assert.notStrictEqual(ours, FROM_TREE_SITTER, "the hook must return our ranges for python");
  const byScope = (scope: string): string[] =>
    ours.filter((range) => range[2] === scope).map((range) => FIXTURE.slice(range[0], range[1]));
  assert.ok(byScope("keyword").includes("def"), `no keyword range for \`def\`: ${JSON.stringify(ours)}`);
  assert.ok(byScope("keyword").includes("return"), "no keyword range for `return`");
  assert.ok(byScope("string").some((text) => text.includes('"hello "')), "no string range");

  // The colour carrier: every scope we emit must have a style in the table the
  // view registers with SyntaxStyle, otherwise the token renders uncoloured.
  const table = highlightStyleTable(viewTheme("default"));
  for (const [, , scope] of ours) {
    assert.ok(scope in table, `scope ${JSON.stringify(scope)} has no style registered`);
  }
  assert.ok(ours.length > 0, "an empty highlight list would leave the block uncoloured");
});

test("a block we cannot highlight keeps tree-sitter's own list", () => {
  const stub: CodeStub = {};
  renderCode({ type: "code", lang: "python", text: "plain prose" }, stub);
  assert.equal(typeof stub.onHighlight, "function");
  const fallback = (stub.onHighlight as Hook)(FROM_TREE_SITTER);
  assert.strictEqual(fallback, FROM_TREE_SITTER, "with no ranges of our own, tree-sitter stays in charge");
});

test("an unknown language is left entirely to the default renderable", () => {
  const stub: CodeStub = { filetype: "" };
  const { returned } = renderCode({ type: "code", lang: "not-a-language", text: FIXTURE }, stub);
  assert.equal(returned, stub);
  assert.equal(stub.filetype, "", "an unknown fence must not set a filetype");
  assert.equal(stub.onHighlight, undefined, "an unknown fence must not install our hook");
});

test("non-code tokens and a null default render pass through untouched", () => {
  const paragraph: CodeStub = {};
  const { returned, defaultRenderCalls } = renderCode(
    { type: "paragraph", text: FIXTURE },
    paragraph,
  );
  assert.equal(returned, undefined, "prose must be left to the default rendering");
  assert.equal(defaultRenderCalls, 0, "prose must not even reach defaultRender");
  assert.equal(paragraph.onHighlight, undefined);

  const { returned: nullReturned } = renderCode({ type: "code", lang: "python", text: FIXTURE }, null);
  assert.equal(nullReturned, null, "a null default renderable must be returned as null");
});

test("the colours are actually rendered into the frame (native renderer, bun)", () => {
  const result = spawnSync(process.env.BUN_BIN ?? "bun", ["run", HARNESS], {
    cwd: PACKAGE_ROOT,
    encoding: "utf8",
    timeout: TIMEOUT_MS,
  });
  const output = `${result.stdout ?? ""}${result.stderr ?? ""}`;
  if (result.error !== undefined) {
    assert.fail(
      `cannot run \`bun run ${HARNESS}\`: ${result.error.message}. ` +
        "Rendering the view needs bun (OpenTUI has no node FFI); install bun >= 1.4 or set BUN_BIN.",
    );
  }
  assert.equal(result.status, 0, `the highlight render harness failed:\n${output}`);
  assert.match(
    output,
    /OPENTUI_CODE_HIGHLIGHT_RENDER_HARNESS: PASS/,
    "the harness did not report a pass",
  );
});
