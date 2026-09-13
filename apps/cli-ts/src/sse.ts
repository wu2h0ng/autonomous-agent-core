/**
 * Minimal SSE frame parser for the surface stream endpoint.
 *
 * Mirrors apps/cli/surface_client.py `_decode_frame_sse`: `event: cursor`
 * carries {next_sequence}; every other event's `data:` payload is one JSON
 * frame. The endpoint is consumed with bounded polling (wait_ms), matching
 * the Python client's request/response shape rather than a hanging socket.
 */
export interface SseMessage {
  event: string | null;
  data: string;
}

export function parseSse(body: string): SseMessage[] {
  const messages: SseMessage[] = [];
  let currentEvent: string | null = null;
  let dataLines: string[] = [];
  for (const line of body.split(/\r?\n/)) {
    if (line.startsWith("event: ")) {
      currentEvent = line.slice(7);
    } else if (line.startsWith("data: ")) {
      dataLines.push(line.slice(6));
    } else if (line === "") {
      if (currentEvent !== null || dataLines.length > 0) {
        messages.push({ event: currentEvent, data: dataLines.join("\n") });
      }
      currentEvent = null;
      dataLines = [];
    }
  }
  return messages;
}
