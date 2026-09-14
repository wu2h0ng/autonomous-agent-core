/**
 * App component tests (ink-testing-library) — covers the key-routing that
 * pure modules cannot: palette select, `@` mention completion, multi-line
 * paste, Ctrl-R search, and the y/n approval path not leaking into the
 * composer. Renders the real <App> against a scripted fake client.
 */
import assert from "node:assert/strict";
import test from "node:test";
import React from "react";
import { render } from "ink-testing-library";
import { App } from "../src/App.js";
import { TuiController } from "../src/controller.js";
import type { SurfaceSessionSnapshot, SurfaceStreamFrame } from "../src/contracts.js";

const SNAPSHOT: SurfaceSessionSnapshot = {
  protocol_version: "1.1",
  session: {
    session_id: "s:1",
    task_id: "task:1",
    run_id: "run:1",
    tenant_id: "tenant:local",
    workspace_id: "workspace:local",
  },
  envelope_id: "env:1",
  expected_outcome_id: "outcome:1",
  status: "ACTIVE",
  event_sequence: 1,
  message_count: 0,
  pending_approval: null,
  permission_mode: "ASK",
  updated_at: "2026-09-13T00:00:00Z",
};

class FakeClient {
  filesList = [{ path: "src/a.ts", size: 10, mtime: "2026-09-13T00:00:00Z" }];
  async openSession() {
    return SNAPSHOT;
  }
  async getSession() {
    return SNAPSHOT;
  }
  async subscribeStream() {
    return { protocol_version: "1.1", runtime_boot_id: "boot:1", stream_id: "stream:1" };
  }
  async beginTurn() {
    return { protocol_version: "1.1", turn_id: "turn:1", stream_id: "stream:1" };
  }
  async *followStream(): AsyncGenerator<SurfaceStreamFrame> {
    // no frames
  }
  async events() {
    return { task_id: "task:1", after_sequence: 0, next_sequence: 0, events: [] };
  }
  async setPermissionMode() {
    return SNAPSHOT;
  }
  async decideApproval() {
    return {
      protocol_version: "1.1",
      snapshot: SNAPSHOT,
      turn_id: "turn:1",
      text: "",
      steps: [],
      stop_reason: "completed",
      total_tokens: 0,
    };
  }
  async correct() {
    return SNAPSHOT;
  }
  async files() {
    return this.filesList;
  }
  async overview() {
    return {
      task_id: "task:1",
      task_status: "ACTIVE",
      run_status: "COMPLETED",
      run_id: "run:1",
      expected_outcome_id: "outcome:1",
      receipt_count: 0,
      session_id: "s:1",
    };
  }
}

const flush = (): Promise<void> => new Promise((resolve) => setTimeout(resolve, 25));

test("palette: `/` lists commands; typing filters; Enter runs the selection", async () => {
  const controller = new TuiController(new FakeClient() as never);
  const submitted: string[] = [];
  controller.submit = async (value: string) => {
    submitted.push(value);
    return true;
  };
  const view = render(<App controller={controller} />);
  try {
    await flush();
    await view.stdin.write("/");
    await flush();
    assert.match(view.lastFrame() ?? "", /\/status/);

    await view.stdin.write("st");
    await flush();
    assert.match(view.lastFrame() ?? "", /\/status/);

    await view.stdin.write("\r");
    await flush();
    assert.deepEqual(submitted, ["/status"]);
  } finally {
    view.unmount();
  }
});

test("@ mention: lists workspace files and Tab completes the path", async () => {
  const controller = new TuiController(new FakeClient() as never);
  await controller.submit("/resume s:1"); // sets task_id so files can be fetched
  const view = render(<App controller={controller} />);
  try {
    await flush();
    await view.stdin.write("@");
    await flush();
    assert.match(view.lastFrame() ?? "", /src\/a\.ts/);

    await view.stdin.write("\t");
    await flush();
    assert.match(view.lastFrame() ?? "", /@src\/a\.ts/);
  } finally {
    view.unmount();
  }
});

test("multi-line paste is preserved (CR/CRLF normalized to a new line)", async () => {
  const controller = new TuiController(new FakeClient() as never);
  const view = render(<App controller={controller} />);
  try {
    await flush();
    await view.stdin.write("a\r\nb");
    await flush();
    const frame = view.lastFrame() ?? "";
    assert.match(frame, /a/);
    assert.match(frame, /b/);
  } finally {
    view.unmount();
  }
});

test("Ctrl-R enters reverse search mode", async () => {
  const controller = new TuiController(new FakeClient() as never);
  const view = render(<App controller={controller} />);
  try {
    await flush();
    await view.stdin.write("\u0012"); // Ctrl-R
    await flush();
    assert.match(view.lastFrame() ?? "", /reverse search/);
  } finally {
    view.unmount();
  }
});

test("selector: /theme opens an overlay; a number key applies the choice", async () => {
  const controller = new TuiController(new FakeClient() as never);
  const view = render(<App controller={controller} />);
  try {
    await flush();
    await view.stdin.write("/theme");
    await flush();
    await view.stdin.write("\r");
    await flush();
    assert.match(view.lastFrame() ?? "", /↑↓ move/);

    await view.stdin.write("2"); // choose items[1] (ansi)
    await flush();
    assert.equal(controller.themeName, "ansi");
    assert.equal(controller.pendingSelector, null);
  } finally {
    view.unmount();
  }
});

test("selector: filtering after moving the cursor still picks the highlighted item", async () => {
  const controller = new TuiController(new FakeClient() as never);
  const view = render(<App controller={controller} />);
  try {
    await flush();
    await view.stdin.write("/theme");
    await flush();
    await view.stdin.write("\r");
    await flush();
    // move the cursor to the last item (default -> ansi -> mono)
    await view.stdin.write("\u001B[B");
    await flush();
    await view.stdin.write("\u001B[B");
    await flush();
    // narrowing to "an" must not leave the cursor past the end (P1 regression)
    await view.stdin.write("an");
    await flush();
    await view.stdin.write("\r");
    await flush();
    assert.equal(controller.themeName, "ansi");
    assert.equal(controller.pendingSelector, null);
  } finally {
    view.unmount();
  }
});

test("vim: Esc to normal swallows navigation keys; i returns to insert", async () => {
  const controller = new TuiController(new FakeClient() as never);
  controller.vimMode = true;
  const view = render(<App controller={controller} />);
  try {
    await flush();
    await view.stdin.write("ab");
    await flush();
    await view.stdin.write("\u001B"); // Esc -> normal mode
    await flush();
    await view.stdin.write("j"); // normal-mode motion, must not insert
    await flush();
    assert.equal((view.lastFrame() ?? "").includes("abj"), false);
    await view.stdin.write("i"); // back to insert
    await flush();
    await view.stdin.write("Z");
    await flush();
    assert.match(view.lastFrame() ?? "", /Z/);
  } finally {
    view.unmount();
  }
});

test("vim: normal mode must not swallow approval y/n", async () => {
  const controller = new TuiController(new FakeClient() as never);
  controller.vimMode = true;
  let approvals = 0;
  controller.approve = async () => {
    approvals += 1;
  };
  (controller as never as { status: string }).status = "awaiting_approval";
  const view = render(<App controller={controller} />);
  try {
    await flush();
    await view.stdin.write("\u001B"); // Esc would enter normal mode if not for the approval guard
    await flush();
    await view.stdin.write("y");
    await flush();
    assert.equal(approvals, 1);
  } finally {
    view.unmount();
  }
});

test("vim: word motion w then x edits at the word boundary", async () => {
  const controller = new TuiController(new FakeClient() as never);
  controller.vimMode = true;
  const view = render(<App controller={controller} />);
  try {
    await flush();
    await view.stdin.write("ab cd");
    await flush();
    await view.stdin.write("\u001B"); // Esc -> normal
    await flush();
    await view.stdin.write("0"); // cursor to line start
    await flush();
    await view.stdin.write("w"); // cursor to start of "cd"
    await flush();
    await view.stdin.write("x"); // delete 'c'
    await flush();
    const frame = view.lastFrame() ?? "";
    assert.match(frame, /ab d/);
    assert.equal(frame.includes("ab cd"), false);
  } finally {
    view.unmount();
  }
});

test("vim: dd deletes the line in normal mode", async () => {
  const controller = new TuiController(new FakeClient() as never);
  controller.vimMode = true;
  const view = render(<App controller={controller} />);
  try {
    await flush();
    await view.stdin.write("remove me");
    await flush();
    await view.stdin.write("\u001B"); // normal
    await flush();
    await view.stdin.write("d");
    await flush();
    await view.stdin.write("d");
    await flush();
    const frame = view.lastFrame() ?? "";
    assert.equal(frame.includes("remove me"), false);
  } finally {
    view.unmount();
  }
});

test("ctrl-p recalls input history", async () => {
  const controller = new TuiController(new FakeClient() as never);
  const view = render(<App controller={controller} initialHistory={["previous prompt"]} />);
  try {
    await flush();
    await view.stdin.write("\u0010"); // Ctrl-P
    await flush();
    assert.match(view.lastFrame() ?? "", /previous prompt/);
  } finally {
    view.unmount();
  }
});

test("approval: y approves and never leaks into the composer", async () => {
  const controller = new TuiController(new FakeClient() as never);
  let approvals = 0;
  controller.approve = async () => {
    approvals += 1;
  };
  const submitted: string[] = [];
  controller.submit = async (value: string) => {
    submitted.push(value);
    return true;
  };
  (controller as never as { status: string }).status = "awaiting_approval";
  const view = render(<App controller={controller} />);
  try {
    await flush();
    await view.stdin.write("y");
    await flush();
    assert.equal(approvals, 1);

    await view.stdin.write("\r");
    await flush();
    assert.deepEqual(submitted, [], "the 'y' keystroke must not become a submitted prompt");
  } finally {
    view.unmount();
  }
});

test("home screen and header render before the first turn", () => {
  const controller = new TuiController(new FakeClient() as never);
  const view = render(
    <App
      controller={controller}
      workspace="/tmp/demo-workspace"
      provider="openai-compatible"
      model="deepseek-chat"
    />,
  );
  const frame = view.lastFrame() ?? "";
  assert.match(frame, /agent-os/);
  assert.match(frame, /AGENT OS/);
  assert.match(frame, /Quick start/);
  assert.match(frame, /deepseek-chat/);
  assert.match(frame, /demo-workspace/);
  view.unmount();
});

test("home panel disappears after the first message", async () => {
  const controller = new TuiController(new FakeClient() as never);
  const view = render(<App controller={controller} workspace="/tmp/demo-workspace" />);
  try {
    await flush();
    assert.match(view.lastFrame() ?? "", /Quick start/);
    await controller.submit("/status"); // pushes a message without a live turn
    await flush();
    assert.doesNotMatch(view.lastFrame() ?? "", /Quick start/);
  } finally {
    view.unmount();
  }
});

test("backspace deletes the previous character (macOS sends \\x7f)", async () => {
  const controller = new TuiController(new FakeClient() as never);
  const view = render(<App controller={controller} />);
  try {
    await flush();
    await view.stdin.write("abc");
    await flush();
    assert.match(view.lastFrame() ?? "", /abc/);
    await view.stdin.write("\u007F"); // Backspace key on macOS terminals
    await flush();
    const frame = view.lastFrame() ?? "";
    assert.match(frame, /ab/);
    assert.doesNotMatch(frame, /abc/);
  } finally {
    view.unmount();
  }
});

test("ctrl-o opens the tool-call viewer with the selected call expanded; esc closes", async () => {
  const controller = new TuiController(new FakeClient() as never);
  const push = (controller as never as { push: (message: unknown) => void }).push.bind(controller);
  push({
    role: "system",
    content: "",
    tool: {
      actionId: "a:1",
      capabilityId: "workspace.edit",
      argsSummary: "f.txt",
      argsJson: JSON.stringify({ path: "f.txt", old_string: "a", new_string: "b" }),
      status: "done",
      riskTier: 3,
      durationMs: 1200,
    },
  });
  const view = render(<App controller={controller} />);
  try {
    await flush();
    await view.stdin.write("\u000f"); // Ctrl-O
    await flush();
    const frame = view.lastFrame() ?? "";
    assert.match(frame, /tool calls 1/);
    assert.match(frame, /tier     3/);
    assert.match(frame, /duration 1.2s/);

    await view.stdin.write("\u001b"); // Esc
    await flush();
    assert.equal((view.lastFrame() ?? "").includes("tool calls 1"), false);
  } finally {
    view.unmount();
  }
});

test("ctrl-d deletes forward at the cursor", async () => {
  const controller = new TuiController(new FakeClient() as never);
  const view = render(<App controller={controller} />);
  try {
    await flush();
    await view.stdin.write("ab");
    await flush();
    await view.stdin.write("\u001B[D"); // Left arrow -> cursor before 'b'
    await flush();
    await view.stdin.write("\u0004"); // Ctrl-D -> delete forward
    await flush();
    const frame = view.lastFrame() ?? "";
    assert.match(frame, /› a/);
    assert.doesNotMatch(frame, /› ab/);
  } finally {
    view.unmount();
  }
});

test("approval: comment mode never decides on y/n inside the comment; Enter sends it whole", async () => {
  const controller = new TuiController(new FakeClient() as never);
  const decisions: string[] = [];
  controller.approve = async (comment?: string) => {
    decisions.push(`APPROVE:${comment ?? ""}`);
  };
  controller.reject = async (comment?: string) => {
    decisions.push(`REJECT:${comment ?? ""}`);
  };
  (controller as never as { status: string }).status = "awaiting_approval";
  const view = render(<App controller={controller} />);
  try {
    await flush();
    await view.stdin.write("c");
    await flush();
    assert.match(view.lastFrame() ?? "", /approval comment/);

    // A comment full of decision letters must never decide anything — type it
    // one key at a time, exactly like a human (a multi-char write is a paste
    // and takes a different code path).
    const comment = "no, use the read-only path";
    for (const character of comment) {
      await view.stdin.write(character);
    }
    await flush();
    assert.deepEqual(decisions, []);
    assert.match(view.lastFrame() ?? "", /use the read-only path/);

    // Enter sends the whole comment as the durable reason.
    await view.stdin.write("\r");
    await flush();
    assert.deepEqual(decisions, [`APPROVE:${comment}`]);
  } finally {
    view.unmount();
  }
});

test("approval: empty comment + Enter does not approve", async () => {
  const controller = new TuiController(new FakeClient() as never);
  const decisions: string[] = [];
  controller.approve = async (comment?: string) => {
    decisions.push(comment ?? "");
  };
  (controller as never as { status: string }).status = "awaiting_approval";
  const view = render(<App controller={controller} />);
  try {
    await flush();
    await view.stdin.write("c");
    await flush();
    await view.stdin.write("\r");
    await flush();
    assert.deepEqual(decisions, [], "a bare Enter must not approve without a comment");
    assert.match(view.lastFrame() ?? "", /approval comment/);
  } finally {
    view.unmount();
  }
});

test("approval card renders the durable identity line (tier · node · requested)", async () => {
  const controller = new TuiController(new FakeClient() as never);
  const internals = controller as never as { status: string; snapshot: unknown };
  internals.status = "awaiting_approval";
  internals.snapshot = {
    ...SNAPSHOT,
    status: "WAITING_APPROVAL",
    pending_approval: {
      action_digest: "d".repeat(64),
      capability_id: "workspace.edit",
      proposal_id: "p:1",
      preview: "edit f.txt",
      requested_at: "2026-09-14T00:00:00Z",
    },
  };
  controller.pendingApproval = {
    capabilityId: "workspace.edit",
    riskTier: 3,
    nodeId: "node:1",
    requestedAt: "2026-09-14T00:00:00Z",
    actionDigest: "d".repeat(64),
  };
  const view = render(<App controller={controller} />);
  try {
    await flush();
    const frame = view.lastFrame() ?? "";
    // the card line comes from the durable payload only — nothing is invented
    assert.match(frame, /risk tier 3 · node node:1 · requested 2026-09-14T00:00:00Z/);
    assert.match(frame, new RegExp(`digest ${"d".repeat(16)}`));
  } finally {
    view.unmount();
  }
});

test("approval card omits the identity line entirely when nothing was captured", async () => {
  const controller = new TuiController(new FakeClient() as never);
  const internals = controller as never as { status: string; snapshot: unknown };
  internals.status = "awaiting_approval";
  internals.snapshot = {
    ...SNAPSHOT,
    status: "WAITING_APPROVAL",
    pending_approval: {
      action_digest: "d".repeat(64),
      capability_id: "workspace.edit",
      proposal_id: "p:1",
      preview: "edit f.txt",
      requested_at: "2026-09-14T00:00:00Z",
    },
  };
  const view = render(<App controller={controller} />);
  try {
    await flush();
    const frame = view.lastFrame() ?? "";
    assert.match(frame, /approval required/);
    assert.equal(frame.includes("risk tier"), false, "no tier line without durable data");
    assert.equal(frame.includes("requested "), false);
  } finally {
    view.unmount();
  }
});
