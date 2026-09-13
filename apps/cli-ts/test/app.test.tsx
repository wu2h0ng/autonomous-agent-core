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
    assert.equal((view.lastFrame() ?? "").includes("j"), false);
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
