/**
 * Surface protocol 1.2 negotiation for the TS client.
 *
 * Python twin: tests/product/test_surface_protocol_1_2.py. The client must be an
 * ORDERED reader — a MINOR step is additive, so a runtime one minor behind
 * speaks a shape this client still parses. What it must never become is a
 * tolerant reader: the accepted set is the declared, closed enumeration, so a
 * foreign MAJOR, a higher minor and a garbage string all stay out.
 *
 * Why this matters here rather than only in Python: the session listing gained
 * `awaiting_approval` in 1.2 and the agents tree reads it. A client whose
 * response schema silently dropped the field would still be "green" while the
 * approval marker never appeared.
 */
import assert from "node:assert/strict";
import test from "node:test";

import {
  SURFACE_PROTOCOL_MIN_SUPPORTED,
  SURFACE_PROTOCOL_READABLE_VERSIONS,
  SURFACE_PROTOCOL_VERSION,
  SurfaceProtocolVersionSchema,
  SurfaceSessionListResponseSchema,
} from "../src/contracts.js";

function summary(overrides: Record<string, unknown> = {}) {
  return {
    session_id: "session:1",
    task_id: "task:1",
    status: "WAITING_APPROVAL",
    permission_mode: "ASK",
    message_count: 2,
    updated_at: "2026-09-18T00:00:00+00:00",
    ...overrides,
  };
}

test("the client speaks 1.2 over a declared 1.1 floor", () => {
  assert.equal(SURFACE_PROTOCOL_VERSION, "1.2");
  assert.equal(SURFACE_PROTOCOL_MIN_SUPPORTED, "1.1");
  assert.deepEqual([...SURFACE_PROTOCOL_READABLE_VERSIONS], ["1.1", "1.2"]);
});

test("the readable set is closed — no foreign major or undeclared minor", () => {
  for (const version of SURFACE_PROTOCOL_READABLE_VERSIONS) {
    assert.equal(SurfaceProtocolVersionSchema.safeParse(version).success, true, version);
  }
  for (const refused of ["1.0", "1.3", "0.9", "2.0", "1", "", "nonsense"]) {
    assert.equal(SurfaceProtocolVersionSchema.safeParse(refused).success, false, refused);
  }
});

test("a 1.2 listing parses and keeps the additive approval field", () => {
  const parsed = SurfaceSessionListResponseSchema.parse({
    protocol_version: "1.2",
    sessions: [summary({ awaiting_approval: true })],
  });
  assert.equal(parsed.protocol_version, "1.2");
  assert.equal(parsed.sessions[0]?.awaiting_approval, true);
});

test("a 1.1 listing from an older runtime still parses", () => {
  // The runtime negotiated down, so the 1.2-only key is absent entirely.
  const parsed = SurfaceSessionListResponseSchema.parse({
    protocol_version: "1.1",
    sessions: [summary({ status: "ACTIVE" })],
  });
  assert.equal(parsed.protocol_version, "1.1");
  assert.equal(parsed.sessions[0]?.awaiting_approval, false);
});

test("an unnegotiable listing version is rejected, body notwithstanding", () => {
  for (const version of ["1.0", "1.3", "2.0", "nonsense"]) {
    assert.equal(
      SurfaceSessionListResponseSchema.safeParse({
        protocol_version: version,
        sessions: [summary()],
      }).success,
      false,
      version,
    );
  }
});
