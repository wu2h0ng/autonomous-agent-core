/**
 * Rendering-surface tests: markdown renderer and the controller's
 * finalized-cursor + tool-card projection. The finalized cursor counts
 * messages, never physical wrapped rows (M2 P1 lesson, twice).
 */
import assert from "node:assert/strict";
import test from "node:test";
import {
  formatToolDetail,
  parseTodoItems,
  summarizeArgs,
  TODO_CAPABILITY,
  TuiController,
} from "../src/controller.js";

test("markdown: headers, bold and code fences render ANSI, unclosed fence does not throw", async () => {
  // marked-terminal uses chalk, which samples TTY/env at import time; force
  // color before the module graph loads so ANSI styling is asserted for real.
  process.env.FORCE_COLOR = "1";
  const { renderMarkdown } = await import("../src/markdown.js");
  const stripAnsi = (s: string): string => s.replace(/\[[0-9;]*m/g, "");
  const out = renderMarkdown("# Title\n\nsome **bold** text\n\n```ts\nconst x = 1;\n```\n");
  const plain = stripAnsi(out);
  assert.ok(plain.includes("Title"));
  assert.ok(plain.includes("bold"));
  // code fences are syntax-highlighted per token, so assert content on the
  // ANSI-stripped view rather than the raw styled string
  assert.ok(plain.includes("const x = 1;"));
  assert.ok(/\u001b\[/.test(out), "expected ANSI styling");
  const partial = renderMarkdown("```ts\nunclosed(");
  assert.ok(stripAnsi(partial).includes("unclosed("));
});

test("summarizeArgs prefers path/command and truncates", () => {
  assert.equal(summarizeArgs('{"path":"src/a.ts","old_string":"x"}'), "src/a.ts");
  assert.equal(summarizeArgs('{"command":"npm test"}'), "npm test");
  assert.equal(summarizeArgs(`{"path":"${"p".repeat(100)}"}`).length, 73);
  assert.equal(summarizeArgs("not json"), "(unparseable arguments)");
});

test("formatToolDetail pretty-prints arguments and never throws on malformed JSON", () => {
  const detail = formatToolDetail({
    actionId: "a:1",
    capabilityId: "workspace.edit",
    argsSummary: "src/a.ts",
    argsJson: '{"path":"src/a.ts","new_string":"b"}',
    status: "done",
  });
  assert.deepEqual(detail[0], "action   a:1");
  assert.deepEqual(detail[1], "status   done");
  assert.ok(detail.some((line) => line.includes('"path": "src/a.ts"')));
  const raw = formatToolDetail({
    actionId: "a:2",
    capabilityId: "workspace.edit",
    argsSummary: "?",
    argsJson: "not json",
    status: "failed",
  });
  assert.ok(raw.some((line) => line.includes("not json")));
});

test("finalized cursor: messages finalize on push and on resolution", async () => {
  const controller = new TuiController({} as never);
  const internals = controller as never as {
    push: (m: { role: "system"; content: string }) => void;
    finalizeAll: () => void;
  };
  internals.push({ role: "system", content: "one" });
  assert.equal(controller.finalizedIndex, 0);
  internals.push({ role: "system", content: "two" });
  assert.equal(controller.finalizedIndex, 1);
  internals.finalizeAll();
  assert.equal(controller.finalizedIndex, 2);
});

test("tool cards: proposed → pending card; receipt → done/failed by action_id", async () => {
  const controller = new TuiController({} as never);
  const apply = controller as never as {
    applyDurable: (n: number, e: unknown[]) => void;
  };
  apply.applyDurable(1, [
    {
      event_id: "e:1",
      task_id: "task:1",
      event_type: "ACTION_PROPOSED",
      payload_json: JSON.stringify({
        action: {
          action_id: "a:1",
          capability_id: "workspace.edit",
          arguments_json: '{"path":"fixture.txt","old_string":"a","new_string":"b"}',
        },
      }),
      occurred_at: new Date().toISOString(),
      sequence: 1,
    },
  ]);
  assert.equal(controller.messages.length, 1);
  assert.equal(controller.messages[0]?.tool?.status, "pending");
  assert.equal(controller.messages[0]?.tool?.argsSummary, "fixture.txt");

  apply.applyDurable(2, [
    {
      event_id: "e:2",
      task_id: "task:1",
      event_type: "ACTION_RECEIPT_RECORDED",
      payload_json: JSON.stringify({
        receipt: { action_id: "a:1", status: "SUCCEEDED" },
        decision: { action_id: "a:1" },
      }),
      occurred_at: new Date().toISOString(),
      sequence: 2,
    },
  ]);
  assert.equal(controller.messages[0]?.tool?.status, "done");

  // unknown action id: no crash, no card mutation
  apply.applyDurable(3, [
    {
      event_id: "e:3",
      task_id: "task:1",
      event_type: "ACTION_RECEIPT_RECORDED",
      payload_json: JSON.stringify({ receipt: { action_id: "a:unknown", status: "FAILED" } }),
      occurred_at: new Date().toISOString(),
      sequence: 3,
    },
  ]);
  assert.equal(controller.messages[0]?.tool?.status, "done");
});

test("tool receipt: no-error sentinel never renders and non-success statuses stay honest", () => {
  const controller = new TuiController({} as never);
  const apply = controller as never as { applyDurable: (n: number, e: unknown[]) => void };
  const proposed = (seq: number, actionId: string): Record<string, unknown> => ({
    event_id: `e:${seq}`,
    task_id: "task:1",
    event_type: "ACTION_PROPOSED",
    payload_json: JSON.stringify({
      action: { action_id: actionId, capability_id: "workspace.edit", arguments_json: '{"path":"f.txt"}' },
    }),
    occurred_at: new Date().toISOString(),
    sequence: seq,
  });
  const receipt = (
    seq: number,
    actionId: string,
    body: Record<string, unknown>,
  ): Record<string, unknown> => ({
    event_id: `e:${seq}`,
    task_id: "task:1",
    event_type: "ACTION_RECEIPT_RECORDED",
    payload_json: JSON.stringify({ decision: { action_id: actionId }, ...body }),
    occurred_at: new Date().toISOString(),
    sequence: seq,
  });

  apply.applyDurable(1, [proposed(1, "a:1")]);
  apply.applyDurable(2, [
    receipt(2, "a:1", {
      receipt: { action_id: "a:1", status: "SUCCEEDED", error_code: "error:none", output_artifact_ids: ["art:1"] },
      effect: { path: "f.txt", applied_sha256: "a".repeat(64) },
    }),
  ]);
  const done = controller.messages[0]?.tool;
  assert.equal(done?.status, "done");
  assert.match(done?.resultSummary ?? "", /effect f\.txt/);
  assert.match(done?.resultSummary ?? "", /artifacts 1/);
  assert.ok(!(done?.resultSummary ?? "").includes("error:none"), "no-error sentinel must not render");

  apply.applyDurable(3, [proposed(3, "a:2")]);
  apply.applyDurable(4, [
    receipt(4, "a:2", { receipt: { action_id: "a:2", status: "UNKNOWN", error_code: "error:none" } }),
  ]);
  assert.equal(controller.messages[1]?.tool?.status, "pending", "UNKNOWN must not render as success");

  apply.applyDurable(5, [proposed(5, "a:3")]);
  apply.applyDurable(6, [
    receipt(6, "a:3", { receipt: { action_id: "a:3", status: "FAILED", error_code: "error:timeout" } }),
  ]);
  assert.equal(controller.messages[2]?.tool?.status, "failed");
  assert.match(controller.messages[2]?.tool?.resultSummary ?? "", /error error:timeout/);
});

function todoProposedEvent(
  seq: number,
  actionId: string,
  todos: unknown,
): Record<string, unknown> {
  return {
    event_id: `e:${seq}`,
    task_id: "task:1",
    event_type: "ACTION_PROPOSED",
    payload_json: JSON.stringify({
      action: {
        action_id: actionId,
        capability_id: TODO_CAPABILITY,
        arguments_json: JSON.stringify({ todos }),
      },
    }),
    occurred_at: new Date().toISOString(),
    sequence: seq,
  };
}

function todoReceiptEvent(
  seq: number,
  actionId: string,
  status: "SUCCEEDED" | "FAILED",
): Record<string, unknown> {
  return {
    event_id: `e:${seq}`,
    task_id: "task:1",
    event_type: "ACTION_RECEIPT_RECORDED",
    payload_json: JSON.stringify({
      receipt: { action_id: actionId, status },
      decision: { action_id: actionId },
    }),
    occurred_at: new Date().toISOString(),
    sequence: seq,
  };
}

test("todo panel: parseTodoItems defensive + full-replace + failed never overwrites", () => {
  // parseTodoItems: shape violations return null, never guessed
  assert.equal(parseTodoItems("not json"), null);
  assert.equal(parseTodoItems("{}"), null);
  assert.equal(parseTodoItems('{"todos":[{"content":"x","status":"bogus"}]}'), null);
  assert.equal(parseTodoItems('{"todos":[{"content":"x","status":"pending"}]}')?.length, 1);
  // missing id gets a positional fallback
  assert.equal(
    parseTodoItems('{"todos":[{"content":"x","status":"done"}]}')?.[0]?.id,
    "todo-1",
  );

  const controller = new TuiController({} as never);
  const apply = controller as never as {
    applyDurable: (n: number, e: unknown[]) => void;
  };
  // NB: read the getter via an unknown-typed local — asserting directly on
  // the getter narrows it to null and later accesses collapse to never.
  const panel0: unknown = controller.todoPanel;
  assert.equal(panel0, null); // inert without the capability

  apply.applyDurable(1, [
    todoProposedEvent(1, "t:1", [
      { id: "1", content: "read code", status: "done" },
      { id: "2", content: "write tests", status: "in_progress" },
      { id: "3", content: "ship", status: "pending" },
    ]),
    todoReceiptEvent(2, "t:1", "SUCCEEDED"),
  ]);
  const panel1 = controller.todoPanel;
  assert.equal(panel1?.length, 3);
  assert.equal(panel1?.[1]?.status, "in_progress");

  // full-replace: the newest successful call IS the list
  apply.applyDurable(3, [
    todoProposedEvent(3, "t:2", [{ id: "9", content: "only task now", status: "pending" }]),
    todoReceiptEvent(4, "t:2", "SUCCEEDED"),
  ]);
  const panel2 = controller.todoPanel;
  assert.deepEqual(
    panel2?.map((t) => t.content),
    ["only task now"],
  );

  // a failed write never overwrites the visible list
  apply.applyDurable(5, [
    todoProposedEvent(5, "t:3", [{ id: "x", content: "bad write", status: "pending" }]),
    todoReceiptEvent(6, "t:3", "FAILED"),
  ]);
  const panel3 = controller.todoPanel;
  assert.deepEqual(
    panel3?.map((t) => t.content),
    ["only task now"],
  );
});
