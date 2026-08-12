import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import {
  SurfaceClient,
  SurfaceClientAuthenticationError,
  SurfaceHttpError,
  SurfaceProtocolMismatch,
  parseSse,
} from "../src/surface_client";

function fixture(name: string): string {
  return readFileSync(
    new URL(`./fixtures/surface_contract/${name}`, import.meta.url),
    "utf-8",
  );
}

function jsonClient(
  responses: Array<{ status: number; body: string }>,
): {
  client: SurfaceClient;
  requests: Array<{ method: string; path: string; body?: string }>;
} {
  const requests: Array<{ method: string; path: string; body?: string }> = [];
  const queue = [...responses];
  const fetchImpl = async (
    path: string,
    init?: { method?: string; headers?: Record<string, string>; body?: string },
  ) => {
    requests.push({
      method: init?.method ?? "GET",
      path,
      body: init?.body,
    });
    const next = queue.shift() ?? { status: 500, body: "{}" };
    return {
      ok: next.status >= 200 && next.status < 300,
      status: next.status,
      text: async () => next.body,
    };
  };
  return {
    client: new SurfaceClient("http://127.0.0.1:18787", "test-token", fetchImpl),
    requests,
  };
}

function openSnapshotResponse(): string {
  const valid = JSON.parse(fixture("turn_response_valid.json"));
  return JSON.stringify({ snapshot: valid.snapshot });
}

describe("surface client conformance (shared fixtures with Python client)", () => {
  it("parses a valid turn response to identical semantics", async () => {
    const valid = JSON.parse(fixture("turn_response_valid.json"));
    const { client } = jsonClient([
      { status: 200, body: openSnapshotResponse() },
      { status: 200, body: JSON.stringify({ turn: valid }) },
    ]);
    const snapshot = await client.openSession("inspect the workspace");
    const turn = await client.runTurn(snapshot.session.session_id, "inspect more");

    expect(turn.text).toBe("completed reply");
    expect(turn.stop_reason).toBe("completed");
    expect(turn.snapshot.status).toBe("ACTIVE");
    expect(turn.snapshot.event_sequence).toBe(1);
  });

  it("rejects a protocol mismatch exactly like the Python client", async () => {
    const mismatched = JSON.parse(
      fixture("turn_response_protocol_mismatch.json"),
    );
    const { client } = jsonClient([
      { status: 200, body: openSnapshotResponse() },
      { status: 200, body: JSON.stringify({ turn: mismatched }) },
    ]);
    const snapshot = await client.openSession("inspect");
    await expect(
      client.runTurn(snapshot.session.session_id, "inspect more"),
    ).rejects.toBeInstanceOf(SurfaceProtocolMismatch);
  });

  it("maps 401 to a closed authentication error without token leakage", async () => {
    const { client } = jsonClient([
      { status: 401, body: JSON.stringify({ error: "local_authentication_failed" }) },
    ]);
    await expect(client.getSession("session:1")).rejects.toBeInstanceOf(
      SurfaceClientAuthenticationError,
    );
  });

  it("maps a 409 to SurfaceHttpError with status code", async () => {
    const { client } = jsonClient([
      { status: 409, body: JSON.stringify({ error: "SurfaceSequenceConflict", message: "stale sequence" }) },
    ]);
    await expect(client.getSession("session:1")).rejects.toMatchObject({
      statusCode: 409,
    } as SurfaceHttpError);
  });

  it("parses the shared SSE fixture to a resumable batch", () => {
    const batch = parseSse("task:1", 2, fixture("sse_events.txt"));

    expect(batch.task_id).toBe("task:1");
    expect(batch.after_sequence).toBe(2);
    expect(batch.next_sequence).toBe(3);
    expect(batch.events).toHaveLength(1);
    expect(batch.events[0].sequence).toBe(3);
    expect(batch.events[0].event_type).toBe("SESSION_MESSAGE_RECORDED");
  });

  it("tracks the session sequence across open and turn", async () => {
    const valid = JSON.parse(fixture("turn_response_valid.json"));
    const { client, requests } = jsonClient([
      { status: 200, body: openSnapshotResponse() },
      { status: 200, body: JSON.stringify({ turn: valid }) },
    ]);
    const snapshot = await client.openSession("inspect");
    await client.runTurn(snapshot.session.session_id, "next");

    const turnRequest = requests.find((r) => r.path.includes("/turns"));
    expect(turnRequest).toBeDefined();
    const body = JSON.parse(turnRequest!.body!) as {
      expected_event_sequence: number;
    };
    expect(body.expected_event_sequence).toBe(1);
  });
});
