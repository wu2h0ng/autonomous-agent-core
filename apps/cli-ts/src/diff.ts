/**
 * Approval-preview colorizer. The kernel's frozen `_action_preview` for
 * workspace.edit emits `edit <path>\n--- old ---\n…\n--- new ---\n…`
 * (agent_loop.py). This parser is marker-driven and fails soft: any shape
 * deviation renders the whole preview as plain text, never guessed colors.
 */

export interface PreviewSegment {
  text: string;
  tone: "old" | "new" | "plain";
}

const OLD_MARKER = "--- old ---";
const NEW_MARKER = "--- new ---";

export function segmentPreview(preview: string): PreviewSegment[] {
  const lines = preview.split("\n");
  const segments: PreviewSegment[] = [];
  let tone: PreviewSegment["tone"] = "plain";
  let buffer: string[] = [];

  const flush = (): void => {
    if (buffer.length === 0) return;
    segments.push({ text: buffer.join("\n"), tone });
    buffer = [];
  };

  let sawOld = false;
  let sawNew = false;
  for (const line of lines) {
    if (line.trim() === OLD_MARKER && !sawOld) {
      flush();
      tone = "old";
      sawOld = true;
      continue;
    }
    if (line.trim() === NEW_MARKER && sawOld && !sawNew) {
      flush();
      tone = "new";
      sawNew = true;
      continue;
    }
    buffer.push(line);
  }
  flush();

  // Fail soft: a lone old-marker without a new-marker is not a diff.
  if (!sawOld || !sawNew) {
    return [{ text: preview, tone: "plain" }];
  }
  return segments;
}
