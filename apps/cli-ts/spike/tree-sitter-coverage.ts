/**
 * Decisive probe for #16 (syntax highlighting not applied).
 *
 * Hypothesis under test: the markdown/Code renderables DO get a TreeSitterClient
 * (CodeRenderable falls back to getTreeSitterClient()), but the *bundled*
 * default grammar set is only javascript/typescript/markdown/markdown_inline/zig
 * — so the fixture's ```python fence resolves to a filetype with NO parser and
 * therefore produces zero highlights (every token stays default white).
 *
 * Run:  bun run spike/tree-sitter-coverage.ts
 */
import { getTreeSitterClient } from "@opentui/core";

const CANDIDATES = [
  "python",
  "typescript",
  "javascript",
  "javascriptreact",
  "typescriptreact",
  "markdown",
  "markdown_inline",
  "zig",
  "rust",
  "go",
  "bash",
  "json",
  "sql",
  "yaml",
  "ruby",
  "c",
  "cpp",
  "java",
  "html",
  "css",
];

/** Exactly the fenced block the hermetic stub (scripts/dev_daemon.py) emits. */
const FIXTURE = [
  "# highlighted fixture for the syntax-scope check",
  "def greet(name: str) -> str:",
  '    return "hello " + name',
].join("\n");

const client = getTreeSitterClient();
await client.initialize();
console.log("client.isInitialized():", client.isInitialized());

const have: string[] = [];
const missing: string[] = [];
for (const filetype of CANDIDATES) {
  const ok = await client.preloadParser(filetype);
  (ok ? have : missing).push(filetype);
}
console.log("PARSERS PRESENT :", have.join(", ") || "(none)");
console.log("PARSERS ABSENT  :", missing.join(", ") || "(none)");

for (const filetype of ["python", "typescript"]) {
  const result = await client.highlightOnce(FIXTURE, filetype);
  const n = result.highlights === undefined ? null : result.highlights.length;
  console.log(`highlightOnce(filetype=${filetype}) -> highlights=${n}`, {
    warning: result.warning,
    error: result.error,
  });
  if (result.highlights) {
    console.log("  sample:", JSON.stringify(result.highlights.slice(0, 8)));
  }
}

await client.destroy();
