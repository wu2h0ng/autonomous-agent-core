/**
 * Minimal SSE parser shared by the surface stream endpoint and the durable
 * task-events endpoint (apps/cli-ts/src/client.ts).
 *
 * Mirrors apps/cli/surface_client.py `_decode_frame_sse`: `event: cursor`
 * carries {next_sequence}; every other event's `data:` payload is one JSON
 * frame. It also mirrors `_decode_sse`'s EOF flush. The endpoints are consumed
 * with bounded polling (wait_ms), matching the Python client's
 * request/response shape rather than a hanging socket.
 */
export interface SseMessage {
  event: string | null;
  data: string;
}

export function parseSse(body: string): SseMessage[] {
  const messages: SseMessage[] = [];
  let currentEvent: string | null = null;
  let dataLines: string[] = [];
  const flush = (): void => {
    if (currentEvent !== null || dataLines.length > 0) {
      messages.push({ event: currentEvent, data: dataLines.join("\n") });
    }
    currentEvent = null;
    dataLines = [];
  };
  for (const line of body.split(/\r?\n/)) {
    if (line.startsWith("event: ")) {
      currentEvent = line.slice(7);
    } else if (line.startsWith("data: ")) {
      dataLines.push(line.slice(6));
    } else if (line === "") {
      flush();
    }
  }
  // EOF flush, mirroring `_decode_sse` in apps/cli/surface_client.py: a frame is
  // normally terminated by a blank line, but a body that ends mid-frame must be
  // decoded all the same. Dropping it left a trailing `cursor` frame unread and
  // stalled next_sequence at after_sequence. A truncated payload still fails
  // closed, because the caller's JSON.parse rejects the emitted data.
  flush();
  return messages;
}
