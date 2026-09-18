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

  it("flushes a final cursor frame that has no trailing newline", () => {
    // Mirrors apps/cli/surface_client.py `_decode_sse` and apps/cli-ts/src/sse.ts:
    // a frame is normally terminated by a blank line, but a body that ends
    // mid-frame must still be decoded. Dropping it left next_sequence at
    // after_sequence while the event frame was returned, so a poller would
    // re-request the same cursor forever.
    const body =
      "id: 3\n" +
      "event: SESSION_MESSAGE_RECORDED\n" +
      'data: {"schema_version":"1.0","event_id":"event:3","task_id":"task:1","sequence":3,' +
      '"event_type":"SESSION_MESSAGE_RECORDED","correlation_id":"run:1","payload_json":"{}",' +
      '"occurred_at":"2026-08-12T00:00:00+00:00"}\n' +
      "\n" +
      'event: cursor\ndata: {"next_sequence": 3}';
    expect(body.endsWith("\n")).toBe(false);

    const batch = parseSse("task:1", 2, body);

    expect(batch.next_sequence).toBe(3);
    expect(batch.events).toHaveLength(1);
    expect(batch.events[0].sequence).toBe(3);
  });

  it("still rejects a truncated final frame instead of guessing", () => {
    const body = 'event: cursor\ndata: {"next_sequence": 3';

    expect(() => parseSse("task:1", 2, body)).toThrow(SyntaxError);
  });

  it("rejects a durable batch whose cursor disagrees with its events", () => {
    // Corpus shape 11_cursor_then_event_midframe: the cursor claims 5 while the
    // batch only carries event 2. Python raises ValidationError
    // (SurfaceEventBatch); agent_thread resumes from next_sequence, so accepting
    // it would re-request a window that never existed.
    const body =
      'event: cursor\ndata: {"next_sequence": 5}\n\n' +
      "id: 2\nevent: SESSION_MESSAGE_RECORDED\n" +
      'data: {"task_id":"task:1","sequence":2,"event_type":"SESSION_MESSAGE_RECORDED","payload_json":"{}"}\n\n';

    expect(() => parseSse("task:1", 0, body)).toThrow(SurfaceProtocolMismatch);
    expect(() => parseSse("task:1", 0, body)).toThrow(
      "surface next_sequence must equal the last event sequence or after_sequence",
    );
  });

  it("rejects a cursor-only frame that would advance with no events", () => {
    // Corpus shape 04_cursor_half_frame (no trailing newline): cursor 7, no
    // events, after 0 — Python raises ValidationError on the batch.
    const body = 'event: cursor\ndata: {"next_sequence": 7}';

    expect(() => parseSse("task:1", 0, body)).toThrow(SurfaceProtocolMismatch);
    expect(() => parseSse("task:1", 0, body)).toThrow(
      "surface next_sequence must equal the last event sequence or after_sequence",
    );
  });

  it("rejects events that do not strictly increase above after_sequence", () => {
    const body =
      "id: 2\nevent: SESSION_MESSAGE_RECORDED\n" +
      'data: {"task_id":"task:1","sequence":2,"event_type":"SESSION_MESSAGE_RECORDED","payload_json":"{}"}\n\n' +
      'event: cursor\ndata: {"next_sequence": 2}\n\n';

    expect(() => parseSse("task:1", 2, body)).toThrow(SurfaceProtocolMismatch);
    expect(() => parseSse("task:1", 2, body)).toThrow(
      "surface event sequences must strictly increase above after_sequence",
    );
  });

  it("surfaces the cursor check through events() and keeps valid batches working", async () => {
    const contradictory = 'event: cursor\ndata: {"next_sequence": 9}\n\n';
    const bad = new SurfaceClient("http://127.0.0.1:1", "test-token", async () => ({
      ok: true,
      status: 200,
      text: async () => contradictory,
    }));
    await expect(bad.events("task:1", 0, 0)).rejects.toBeInstanceOf(
      SurfaceProtocolMismatch,
    );

    const good = new SurfaceClient("http://127.0.0.1:1", "test-token", async () => ({
      ok: true,
      status: 200,
      text: async () => fixture("sse_events.txt"),
    }));
    const batch = await good.events("task:1", 2, 0);
    expect(batch.next_sequence).toBe(3);
    expect(batch.events.map((event) => event.sequence)).toEqual([3]);
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
