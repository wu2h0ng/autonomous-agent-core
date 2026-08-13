import { describe, expect, it, vi } from "vitest";
import { askTransition, initialAskState, upgradeToWork } from "../src/panels/ask";
import { observeEvents } from "../src/panels/observe";
import type { SurfaceEvent } from "../src/surface_client";

function event(sequence: number, event_type: string, payload: object): SurfaceEvent {
  return { sequence, event_type, payload_json: JSON.stringify(payload) };
}

describe("Ask posture", () => {
  it("transitions between phases with zero I/O", () => {
    let state = initialAskState;
    expect(state.phase).toBe("idle");
    state = askTransition(state, "start");
    expect(state.phase).toBe("ask");
    state = askTransition(state, "cancel");
    expect(state.phase).toBe("idle");
  });

  it("upgrade calls openSession exactly once and nothing else", async () => {
    const openSession = vi.fn().mockResolvedValue({
      session: { session_id: "session:1" },
    });
    const client = { openSession } as unknown as import("../src/surface_client").SurfaceClient;

    const state = await upgradeToWork(client, {
      phase: "ask",
      question: "how do I fix the fixture?",
      session_id: null,
    });

    expect(state.phase).toBe("work");
    expect(state.session_id).toBe("session:1");
    expect(openSession).toHaveBeenCalledTimes(1);
    expect(openSession).toHaveBeenCalledWith("how do I fix the fixture?");
  });

  it("rejects upgrades without an active ask or empty question", async () => {
    const client = {} as import("../src/surface_client").SurfaceClient;
    await expect(upgradeToWork(client, initialAskState)).rejects.toThrow(
      "active ask",
    );
    await expect(
      upgradeToWork(client, { phase: "ask", question: "  ", session_id: null }),
    ).rejects.toThrow("non-empty");
  });
});

describe("Observe posture", () => {
  it("projects HelpRequest and risk events read-only", () => {
    const items = observeEvents([
      event(3, "HELP_REQUESTED", { reason: "credential expired" }),
      event(7, "CORRECTION_WRITTEN", { scope: "TASK" }),
      event(9, "SESSION_MESSAGE_RECORDED", {}),
    ]);

    expect(items).toHaveLength(2);
    expect(items[0].kind).toBe("help_request");
    expect(items[0].summary).toBe("credential expired");
    expect(items[1].kind).toBe("risk");
  });
});
