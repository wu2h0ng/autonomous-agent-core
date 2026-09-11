import { describe, expect, it } from "vitest";
import {
  SurfaceClient,
  SurfaceProtocolMismatch,
} from "../src/surface_client";
import {
  conflictBadgeForPath,
  conflictPath,
} from "../src/panels/files";

function conflictClient(
  responses: Array<{ status: number; body: string }>,
): { client: SurfaceClient; requests: Array<{ method: string; path: string }> } {
  const requests: Array<{ method: string; path: string }> = [];
  const queue = [...responses];
  const fetchImpl = async (
    path: string,
    init?: { method?: string; headers?: Record<string, string> },
  ) => {
    requests.push({ method: init?.method ?? "GET", path });
    const next = queue.shift() ?? { status: 500, body: "{}" };
    return {
      ok: next.status >= 200 && next.status < 300,
      status: next.status,
      text: async () => next.body,
    };
  };
  return {
    client: new SurfaceClient("http://local", "token", fetchImpl),
    requests,
  };
}

const validConflict = {
  protocol_version: "1.1",
  action_id: "action:edit",
  lease_id: "lease:1",
  disposition: "CONFLICT",
  reason: "write conflict",
  write_scope_uris: ["file:///ws/a.txt"],
  relevant_event_ids: ["ev:1"],
  suggested_action: "REVIEW_DIFF",
};

describe("SurfaceClient.conflict", () => {
  it("returns null on 404", async () => {
    const { client } = conflictClient([
      { status: 404, body: '{"error":"surface_conflict_not_found"}' },
    ]);
    const result = await client.conflict("session-1");
    expect(result).toBeNull();
  });

  it("parses a valid conflict projection", async () => {
    const { client } = conflictClient([
      { status: 200, body: JSON.stringify({ conflict: validConflict }) },
    ]);
    const result = await client.conflict("session-1");
    expect(result).not.toBeNull();
    expect(result!.disposition).toBe("CONFLICT");
    expect(result!.suggested_action).toBe("REVIEW_DIFF");
    expect(result!.write_scope_uris).toEqual(["file:///ws/a.txt"]);
    expect(result!.relevant_event_ids).toEqual(["ev:1"]);
  });

  it("rejects an invalid disposition", async () => {
    const bad = { ...validConflict, disposition: "CONTINUE" };
    const { client } = conflictClient([
      { status: 200, body: JSON.stringify({ conflict: bad }) },
    ]);
    await expect(client.conflict("session-1")).rejects.toBeInstanceOf(
      SurfaceProtocolMismatch,
    );
  });
});

describe("files conflict badge", () => {
  it("derives the relative path from a workspace scope uri", () => {
    expect(conflictPath(["file:///ws/a.txt"])).toBe("a.txt");
    expect(conflictPath(["file:///ws/dir/b.txt"])).toBe("dir/b.txt");
  });

  it("returns a badge only for the matching path", () => {
    const badge = conflictBadgeForPath(
      ["file:///ws/a.txt"],
      "CONFLICT",
      "REVIEW_DIFF",
      "write conflict",
      "a.txt",
    );
    expect(badge).not.toBeNull();
    expect(badge!.disposition).toBe("CONFLICT");
    expect(badge!.suggestedAction).toBe("REVIEW_DIFF");
  });

  it("returns null for a non-matching path", () => {
    const badge = conflictBadgeForPath(
      ["file:///ws/a.txt"],
      "CONFLICT",
      "REVIEW_DIFF",
      "write conflict",
      "b.txt",
    );
    expect(badge).toBeNull();
  });
});
