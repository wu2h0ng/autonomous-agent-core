/**
 * Rendering-surface tests: markdown renderer and the controller's
 * finalized-cursor + tool-card projection. The finalized cursor counts
 * messages, never physical wrapped rows (M2 P1 lesson, twice).
 */
import assert from "node:assert/strict";
import test from "node:test";
import { summarizeArgs, TuiController } from "../src/controller.js";

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
