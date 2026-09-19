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
  planEnter,
  repositionCursor,
  resumableSessionId,
  stopTargetAtRow,
  type ChildRowInput,
} from "../src/opentui/agents.js";
import { fetchAgentTree } from "../src/opentui/agent-tree-source.js";
import type { SurfaceClient } from "../src/client.js";

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

test("planEnter routes Enter without silent no-ops", () => {
  const { rows } = buildAgentTree({ mandates, links, sessions });
  const sessionIndex = rows.findIndex((r) => r.kind === "session");
  const taskIndex = rows.findIndex((r) => r.kind === "task");

  // agents panel: a session row switches (reuses /resume).
  assert.deepEqual(planEnter("agents", rows, sessionIndex, ""), {
    kind: "resume",
    sessionId: rows[sessionIndex]?.id,
  });
  // agents panel: a task row is not resumable -> composer text still submits.
  assert.deepEqual(planEnter("agents", rows, taskIndex, "  hello  "), {
    kind: "submit",
    text: "hello",
  });
  // agents panel + non-resumable row + empty composer -> nothing happens.
  assert.deepEqual(planEnter("agents", rows, taskIndex, "   "), { kind: "none" });
  // transcript panel: normal submit / empty.
  assert.deepEqual(planEnter("transcript", rows, 0, "hi"), {
    kind: "submit",
    text: "hi",
  });
  assert.deepEqual(planEnter("transcript", [], 0, ""), { kind: "none" });
});

test("session rows mark a pending approval, and only when it is set", () => {
  const tree = buildAgentTree({
    mandates,
    links,
    sessions: [
      { session_id: "s-1", task_id: "task-1", status: "IDLE", hasPendingApproval: true },
      { session_id: "s-2", task_id: "task-1", status: "IDLE" },
    ],
  });
  const blocked = tree.rows.find((r) => r.id === "s-1");
  const clear = tree.rows.find((r) => r.id === "s-2");
  assert.equal(blocked?.pendingApproval, true);
  assert.match(agentRowLine(blocked!), /pending approval/);
  // Bypass-detecting: an unset flag must never be rendered as pending.
  assert.notEqual(clear?.pendingApproval, true);
  assert.doesNotMatch(agentRowLine(clear!), /pending approval/);
});


// --- Form B: live child rows + per-child stop target (G10) ---

function child(over: Partial<ChildRowInput> = {}): ChildRowInput {
  return {
    parent_session_id: "s-1",
    spawn_id: "spawn-1",
    child_session_id: "c-1",
    agent_type: "explorer",
    status: "stopped",
    steps: 0,
    tokens: 0,
    stop_reason: null,
    in_flight: false,
    ...over,
  };
}

test("child rows nest under their parent session, sorted by spawn id", () => {
  const children = [
    child({ spawn_id: "spawn-b", child_session_id: "c-b", in_flight: true }),
    child({ spawn_id: "spawn-a", child_session_id: "c-a", status: "completed", steps: 3, tokens: 120, stop_reason: "completed" }),
  ];
  const { rows } = buildAgentTree({ mandates, links, sessions, children });
  // task-1 holds sessions s-1 and s-2 (sorted); only s-1 has children.
  const s1 = rows.findIndex((r) => r.kind === "session" && r.id === "s-1");
  assert.notEqual(s1, -1);
  // children are depth+2 immediately under s-1, spawn-sorted (a before b)
  assert.deepEqual(
    rows.slice(s1 + 1, s1 + 3).map((r) => [r.kind, r.id, r.depth]),
    [
      ["child", "c-a", 3],
      ["child", "c-b", 3],
    ],
  );
  const done = rows[s1 + 1];
  const live = rows[s1 + 2];
  assert.ok(done && live);
  assert.equal(done.status, "completed");
  assert.equal(done.inFlight, false);
  assert.equal(live.status, "running", "in-flight child is labelled running, not its conservative roll-up status");
  assert.equal(live.inFlight, true);
  assert.equal(live.parentSessionId, "s-1");
});

test("child rows belonging to an absent parent session are not rendered", () => {
  const children = [child({ parent_session_id: "s-nope", child_session_id: "c-x" })];
  const { rows } = buildAgentTree({ mandates, links, sessions, children });
  assert.equal(rows.some((r) => r.id === "c-x"), false);
});

test("stopTargetAtRow only targets an in-flight child row", () => {
  const children = [
    child({ spawn_id: "spawn-a", child_session_id: "c-done", status: "completed", stop_reason: "completed" }),
    child({ spawn_id: "spawn-b", child_session_id: "c-live", in_flight: true }),
  ];
  const { rows } = buildAgentTree({ mandates, links, sessions, children });
  const cDone = rows.findIndex((r) => r.id === "c-done");
  const cLive = rows.findIndex((r) => r.id === "c-live");
  const sRow = rows.findIndex((r) => r.kind === "session");
  assert.equal(stopTargetAtRow(rows, cDone), null, "terminal child is not stoppable");
  assert.deepEqual(stopTargetAtRow(rows, cLive), {
    parentSessionId: "s-1",
    childSessionId: "c-live",
  });
  assert.equal(stopTargetAtRow(rows, sRow), null, "a session row is never a child-stop target");
  assert.equal(stopTargetAtRow(rows, 999), null, "out-of-range cursor is null");
});

test("agentRowLine renders live marker, counters and stop reason", () => {
  const live = agentRowLine({
    depth: 3, kind: "child", id: "c-live", status: "running", parentSessionId: "s-1", inFlight: true, steps: 2, tokens: 40,
  });
  assert.match(live, /◦ c-live/);
  assert.match(live, /!running/);
  assert.match(live, /2 step\(s\) · 40 tok/);
  const stopped = agentRowLine({
    depth: 3, kind: "child", id: "c-stopped", status: "stopped", parentSessionId: "s-1", inFlight: false, steps: 0, tokens: 0, stopReason: "stopped_by_operator",
  });
  assert.match(stopped, /stopped_by_operator/);
  assert.doesNotMatch(stopped, /!running/);
});

test("cursorKey distinguishes a child from a same-id session row", () => {
  const { rows } = buildAgentTree({
    mandates,
    links,
    sessions,
    children: [child({ child_session_id: "dup-id" })],
  });
  const childKey = cursorKey(rows, rows.findIndex((r) => r.id === "dup-id"));
  assert.equal(childKey, "child:dup-id");
});


// --- fetchAgentTree joins the live child roll-up into the tree ---

function treeClient(rollup: unknown, opts: { failChild?: boolean } = {}) {
  return {
    getReadOnly: async (path: string) => {
      if (path === "/v1/mandates") {
        return { mandates: [{ mandate: { mandate_id: "m-1", status: "ACTIVE" } }] };
      }
      if (path.endsWith("/task-links")) {
        return { task_links: [{ mandate_id: "m-1", task_id: "task-1" }] };
      }
      return {};
    },
    listSessions: async () => [
      { session_id: "s-1", task_id: "task-1", status: "STREAMING", awaiting_approval: false },
    ],
    childAgents: async () => {
      if (opts.failChild) throw new Error("rollup unavailable");
      return rollup;
    },
  } as unknown as SurfaceClient;
}

test("fetchAgentTree marks an in_flight child running even though its roll-up status is stopped", async () => {
  const rollup = {
    protocol_version: "1.2",
    session_id: "s-1",
    turns: [
      {
        parent_session_id: "s-1",
        parent_turn_id: "turn-1",
        children: [
          {
            spawn_id: "sp-1",
            child_session_id: "c-1",
            child_task_id: "ct-1",
            agent_type: "explorer",
            description: "",
            status: "stopped", // conservative attribution status for an unfinished child
            steps: 0,
            tokens: 0,
            stop_reason: null,
          },
        ],
      },
    ],
    in_flight: [{ spawn_id: "sp-1", child_session_id: "c-1", parent_turn_id: "turn-1" }],
    orphaned: [],
    buried: [],
  };
  const tree = await fetchAgentTree(treeClient(rollup));
  const child = tree.rows.find((r) => r.id === "c-1");
  assert.ok(child, "the live child is rendered under its parent session");
  assert.equal(child?.kind, "child");
  assert.equal(child?.inFlight, true);
  assert.equal(child?.status, "running");
  assert.equal(child?.parentSessionId, "s-1");
});

test("fetchAgentTree degrades to a note when a child roll-up fails", async () => {
  const tree = await fetchAgentTree(treeClient(null, { failChild: true }));
  assert.equal(tree.rows.some((r) => r.kind === "child"), false);
  assert.match(tree.note ?? "", /child roll-up unavailable/);
});
