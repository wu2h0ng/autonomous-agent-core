import { describe, expect, it } from "vitest";
import { recentDiffs } from "../src/panels/diff";
import { terminalEvents } from "../src/panels/terminal";
import { fetchOverview } from "../src/panels/plan_tasks";
import { closedShellState, CLOSED_INTEGRATIONS } from "../src/panels/closed_shell";
import type { SurfaceEvent } from "../src/surface_client";

function event(sequence: number, event_type: string, payload: object): SurfaceEvent {
  return { sequence, event_type, payload_json: JSON.stringify(payload) };
}

describe("Diff panel", () => {
  it("extracts bounded edit diffs from action events", () => {
    const long = "x".repeat(500);
    const diffs = recentDiffs([
      event(4, "ACTION_PROPOSED", {
        action: {
          capability_id: "workspace.edit",
          action_digest: "d1",
          arguments_json: JSON.stringify({
            path: "fixture.txt",
            old_string: "old",
            new_string: long,
          }),
        },
      }),
      event(9, "PROVIDER_RESPONDED", { unrelated: true }),
    ]);

    expect(diffs).toHaveLength(1);
    expect(diffs[0].path).toBe("fixture.txt");
    expect(diffs[0].old_excerpt).toBe("old");
    expect(diffs[0].new_excerpt).toHaveLength(120);
    expect(diffs[0].truncated).toBe(true);
  });

  it("ignores events without action payloads", () => {
    expect(recentDiffs([event(1, "SESSION_MESSAGE_RECORDED", {})])).toEqual([]);
  });
});

describe("Terminal panel", () => {
  it("renders only governed shell actions read-only", () => {
    const lines = terminalEvents([
      event(5, "ACTION_PROPOSED", {
        action: {
          capability_id: "workspace.shell",
          arguments_json: JSON.stringify({ command: "pytest -q" }),
        },
      }),
      event(6, "ACTION_PROPOSED", {
        action: {
          capability_id: "workspace.edit",
          arguments_json: "{}",
        },
      }),
    ]);

    expect(lines).toHaveLength(1);
    expect(lines[0].summary).toBe("pytest -q");
  });
});

describe("Plan and Tasks panel", () => {
  it("parses the closed overview projection and rejects invalid payloads", async () => {
    const fetchImpl = async () => ({
      ok: true,
      status: 200,
      text: async () =>
        JSON.stringify({
          overview: {
            task_id: "task:1",
            task_status: "COMMITTED",
            run_status: "RUNNING",
            expected_outcome_id: "expected:1",
            receipt_count: 2,
            session_id: "session:1",
          },
        }),
    });
    const overview = await fetchOverview("http://x", "t", "task:1", fetchImpl);
    expect(overview.receipt_count).toBe(2);
    expect(overview.run_status).toBe("RUNNING");

    const bad = async () => ({
      ok: true,
      status: 200,
      text: async () =>
        JSON.stringify({ overview: { task_id: "task:1", receipt_count: "x" } }),
    });
    await expect(fetchOverview("http://x", "t", "task:1", bad)).rejects.toThrow(
      "invalid",
    );
  });
});

describe("Closed shells", () => {
  it("renders Wave 3 pending state with zero connectivity", () => {
    for (const panelId of Object.keys(CLOSED_INTEGRATIONS) as Array<
      keyof typeof CLOSED_INTEGRATIONS
    >) {
      const state = closedShellState(panelId, "ACTIVE");
      expect(state.message).toContain("Wave 3");
      expect(state.session_status).toBe("ACTIVE");
    }
  });
});
