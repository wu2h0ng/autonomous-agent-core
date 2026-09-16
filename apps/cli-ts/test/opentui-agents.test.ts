/**
 * P3a agent-tree tests (agents.ts is pure — no renderer/network needed).
 * Bypass-detecting: a builder that ignores links (flat list), drops orphan
 * sessions, or never truncates would fail these.
 */
import assert from "node:assert/strict";
import test from "node:test";
import {
  agentRowLine,
  buildAgentTree,
  clampCursor,
  cursorKey,
  moveCursor,
  repositionCursor,
  resumableSessionId,
} from "../src/opentui/agents.js";

const mandates = [
  { mandate_id: "mandate-b", status: "ACTIVE" },
  { mandate_id: "mandate-a", status: "RATIFIED" },
];
const links = [
  { mandate_id: "mandate-a", task_id: "task-2" },
  { mandate_id: "mandate-a", task_id: "task-1" },
  { mandate_id: "mandate-a", task_id: "task-1" },
  { mandate_id: "mandate-b", task_id: "task-3" },
];
const sessions = [
  { session_id: "s-2", task_id: "task-1", status: "IDLE" },
  { session_id: "s-1", task_id: "task-1", status: "STREAMING" },
  { session_id: "s-9", task_id: "task-orphan", status: "IDLE" },
];

test("buildAgentTree is deterministic, sorted and groups sessions under tasks", () => {
  const { rows, truncated } = buildAgentTree({ mandates, links, sessions });
  assert.equal(truncated, false);
  assert.deepEqual(
    rows.map((r) => [r.depth, r.kind, r.id]),
    [
      [0, "mandate", "mandate-a"],
      [1, "task", "task-1"],
      [2, "session", "s-1"],
      [2, "session", "s-2"],
      [1, "task", "task-2"],
      [0, "mandate", "mandate-b"],
      [1, "task", "task-3"],
      [0, "group", "(unlinked task)"],
      [1, "task", "task-orphan"],
      [2, "session", "s-9"],
    ],
  );
  // A task with no sessions is still shown, explicitly, not silently dropped.
  assert.equal(rows.find((r) => r.id === "task-2")?.status, "-");
  assert.equal(rows.find((r) => r.id === "task-1")?.status, "2 session(s)");
});

test("buildAgentTree survives missing data without throwing", () => {
  assert.deepEqual(buildAgentTree({ mandates: [], links: [], sessions: [] }).rows, []);
  // Sessions but no mandates: they must still be visible under the orphan group.
  const tree = buildAgentTree({ mandates: [], links: [], sessions });
  assert.equal(tree.rows[0]?.id, "(unlinked task)");
  assert.ok(tree.rows.some((r) => r.id === "s-9"));
  // A mandate with no links is still listed.
  const only = buildAgentTree({
    mandates: [{ mandate_id: "m", status: "ACTIVE" }],
    links: [],
    sessions: [],
  });
  assert.deepEqual(only.rows, [{ depth: 0, kind: "mandate", id: "m", status: "ACTIVE" }]);
});

test("buildAgentTree caps the tree and reports truncation", () => {
  const { rows, truncated } = buildAgentTree(
    { mandates, links, sessions },
    3,
  );
  assert.equal(truncated, true);
  assert.equal(rows.length, 3);
});

test("agentRowLine renders depth, marker and status", () => {
  assert.equal(
    agentRowLine({ depth: 0, kind: "mandate", id: "m1", status: "ACTIVE" }),
    "◆ m1  ACTIVE",
  );
  assert.equal(
    agentRowLine({ depth: 2, kind: "session", id: "s1", status: "IDLE" }),
    "    • s1  IDLE",
  );
  assert.equal(
    agentRowLine({ depth: 0, kind: "group", id: "(unlinked task)", status: "" }),
    "≡ (unlinked task)",
  );
});

test("cursor helpers clamp to the tree and only sessions are resumable", () => {
  // Empty tree / out-of-range cursor must never yield an index into nothing.
  assert.equal(clampCursor(5, 0), 0);
  assert.equal(clampCursor(-2, 4), 0);
  assert.equal(clampCursor(9, 4), 3);
  assert.equal(moveCursor(0, -1, 4), 0);
  assert.equal(moveCursor(3, 1, 4), 3);

  const { rows } = buildAgentTree({ mandates, links, sessions });
  const sessionIndex = rows.findIndex((r) => r.kind === "session");
  const taskIndex = rows.findIndex((r) => r.kind === "task");
  const mandateIndex = rows.findIndex((r) => r.kind === "mandate");
  assert.equal(resumableSessionId(rows, sessionIndex), rows[sessionIndex]?.id);
  // A task/mandate row must NOT switch sessions (no accidental resume).
  assert.equal(resumableSessionId(rows, taskIndex), null);
  assert.equal(resumableSessionId(rows, mandateIndex), null);
  assert.equal(resumableSessionId([], 0), null);
});

test("the highlighted row survives a tree refresh (identity, not index)", () => {
  const first = buildAgentTree({ mandates, links, sessions }).rows;
  const target = first.findIndex((r) => r.kind === "session");
  const key = cursorKey(first, target);
  assert.equal(key, "session:s-1");

  // A refresh that inserts a mandate row above shifts every index; the cursor
  // must stay on the same row rather than silently highlight a different one.
  const shiftedRows = [
    ...buildAgentTree({
      mandates: [{ mandate_id: "aaa", status: "ACTIVE" }, ...mandates],
      links: [{ mandate_id: "aaa", task_id: "task-0" }, ...links],
      sessions,
    }).rows,
  ];
  const moved = repositionCursor(shiftedRows, key, target);
  assert.equal(shiftedRows[moved]?.id, "s-1");
  assert.notEqual(moved, target);
  // A vanished row falls back to a clamped index.
  assert.equal(repositionCursor(first, "session:gone", 99), first.length - 1);
});
