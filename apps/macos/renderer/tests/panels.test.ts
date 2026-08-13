import { describe, expect, it, vi } from "vitest";
import { readFileSync } from "node:fs";
import { resumeThread } from "../src/panels/agent_thread";
import { decidePendingApproval, pendingApproval } from "../src/panels/evidence_approval";
import { fetchFiles } from "../src/panels/files";
import { SurfaceClient } from "../src/surface_client";

function fixture(name: string): string {
  return readFileSync(
    new URL(`./fixtures/surface_contract/${name}`, import.meta.url),
    "utf-8",
  );
}

const sseBody = fixture("sse_events.txt");

describe("Agent Thread panel", () => {
  it("resumes from the last cursor with strictly increasing events", async () => {
    const client = new SurfaceClient("http://x", "t", async (path, init) => {
      expect(path).toContain("after=2");
      return { ok: true, status: 200, text: async () => sseBody };
    });
    const state = await resumeThread(client, "task:1", 2);

    expect(state.nextSequence).toBe(3);
    expect(state.messages).toHaveLength(1);
    expect(state.messages[0].sequence).toBe(3);
    expect(state.messages[0].kind).toBe("SESSION_MESSAGE_RECORDED");
  });
});

describe("Evidence and Approval panel", () => {
  const valid = JSON.parse(fixture("turn_response_valid.json"));
  const pending = {
    action_digest: "d".repeat(64),
    capability_id: "workspace.edit",
    proposal_id: "call-edit",
    preview: "exact diff preview",
    requested_at: "2026-08-12T00:00:00+00:00",
  };

  it("submits the EXACT pending digest, never a rewritten one", async () => {
    const client = new SurfaceClient("http://x", "t", async (_path, init) => {
      const body = JSON.parse(init?.body ?? "{}") as {
        action_digest: string;
        disposition: string;
      };
      expect(body.action_digest).toBe("d".repeat(64));
      expect(body.disposition).toBe("APPROVE");
      return { ok: true, status: 200, text: async () => JSON.stringify({ turn: valid }) };
    });
    const spy = vi.spyOn(client, "decideApproval");

    const turn = await decidePendingApproval(
      client,
      "session:1",
      pending,
      "APPROVE",
      "reviewed exact edit",
    );

    expect(turn.stop_reason).toBe("completed");
    expect(spy).toHaveBeenCalledWith(
      "session:1",
      "d".repeat(64),
      "APPROVE",
      "reviewed exact edit",
    );
  });

  it("returns null pending approval when none is pending", () => {
    expect(pendingApproval({ ...valid.snapshot, pending_approval: null })).toBeNull();
    expect(pendingApproval({ ...valid.snapshot, pending_approval: pending })).toEqual(
      pending,
    );
  });
});

describe("Files panel", () => {
  it("parses the bounded listing and rejects invalid entries", async () => {
    const fetchImpl = async () => ({
      ok: true,
      status: 200,
      text: async () =>
        JSON.stringify({
          files: [
            { path: "fixture.txt", size: 8, mtime: "2026-08-12T00:00:00+00:00" },
          ],
        }),
    });
    const files = await fetchFiles("http://x", "t", "task:1", fetchImpl);
    expect(files).toEqual([
      { path: "fixture.txt", size: 8, mtime: "2026-08-12T00:00:00+00:00" },
    ]);

    const bad = async () => ({
      ok: true,
      status: 200,
      text: async () =>
        JSON.stringify({ files: [{ path: "x", size: "not-a-number" }] }),
    });
    await expect(fetchFiles("http://x", "t", "task:1", bad)).rejects.toThrow(
      "invalid entry",
    );
  });
});
