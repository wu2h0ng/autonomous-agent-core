/**
 * P2 panel logic tests (panels.ts is pure — no Bun/@opentui needed).
 * These are bypass-detecting: a constant or always-first panel focus, a status
 * parser that ignores the porcelain status column, or an unbounded line
 * expander would each fail here.
 */
import assert from "node:assert/strict";
import test from "node:test";
import {
  displayLines,
  filePanelLines,
  nextPanel,
  parseGitStatus,
  parseViewFlags,
  visiblePanels,
} from "../src/opentui/panels.js";

test("parseViewFlags: panels default on, animation default on", () => {
  assert.deepEqual(parseViewFlags([]), {
    noAnimation: false,
    withPanels: true,
    withAgents: true,
  });
  assert.deepEqual(parseViewFlags(["--no-animation"]), {
    noAnimation: true,
    withPanels: true,
    withAgents: true,
  });
  assert.deepEqual(parseViewFlags(["--no-panels", "--no-agents"]), {
    noAnimation: false,
    withPanels: false,
    withAgents: false,
  });
});

test("visiblePanels: sidebar needs width; agents panel is opt-out", () => {
  assert.deepEqual(visiblePanels(120, true), [
    "transcript",
    "agents",
    "files",
    "diff",
  ]);
  assert.deepEqual(visiblePanels(120, true, false), [
    "transcript",
    "files",
    "diff",
  ]);
  assert.deepEqual(visiblePanels(99, true), ["transcript"]);
  assert.deepEqual(visiblePanels(120, false), ["transcript"]);
});

test("nextPanel cycles through the visible panels and wraps", () => {
  const all = ["transcript", "agents", "files", "diff"] as const;
  assert.equal(nextPanel("transcript", [...all]), "agents");
  assert.equal(nextPanel("agents", [...all]), "files");
  assert.equal(nextPanel("files", [...all]), "diff");
  assert.equal(nextPanel("diff", [...all]), "transcript");

  // With the agents panel disabled the cycle must skip it entirely.
  const noAgents = ["transcript", "files", "diff"] as const;
  assert.equal(nextPanel("transcript", [...noAgents]), "files");

  const single = ["transcript"] as const;
  assert.equal(nextPanel("transcript", [...single]), "transcript");
  // A panel that is no longer visible (terminal narrowed) resets to the first.
  assert.equal(nextPanel("diff", [...single]), "transcript");
});

test("parseGitStatus keeps the porcelain status column and path", () => {
  assert.deepEqual(parseGitStatus(" M src/a.ts\n?? new file.txt\n"), [
    { status: "M", path: "src/a.ts" },
    { status: "??", path: "new file.txt" },
  ]);
  assert.deepEqual(
    parseGitStatus("MM src/staged+unstaged.ts\nR  old -> new\n?? dir/"),
    [
      { status: "MM", path: "src/staged+unstaged.ts" },
      { status: "R", path: "old -> new" },
      { status: "??", path: "dir/" },
    ],
  );
  assert.deepEqual(parseGitStatus(""), []);
  assert.deepEqual(parseGitStatus("\n  \n"), []);
});

test("filePanelLines: clean/not-a-repo notes vs status rows", () => {
  assert.deepEqual(filePanelLines([], null, 10), ["(clean)"]);
  assert.deepEqual(filePanelLines([], "(not a git worktree)", 10), [
    "(not a git worktree)",
  ]);
  assert.deepEqual(
    filePanelLines([{ status: "M", path: "src/a.ts" }], null, 10),
    ["M  src/a.ts"],
  );
});

test("displayLines bounds the output and normalizes line endings", () => {
  assert.deepEqual(displayLines("a\r\nb\n\n", 10), ["a", "b"]);
  assert.deepEqual(displayLines("a\nb\nc", 2), ["a", "b"]);
  assert.deepEqual(displayLines("", 5), [""]);
});
