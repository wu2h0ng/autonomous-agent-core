/**
 * Unified-diff rendering for approval previews (wired in App.tsx) and edit
 * tool details. Line-level LCS diff; deterministic and pure. Fail-soft at
 * the call site: a preview without the kernel's old/new markers, or with no
 * line change, returns null and the caller renders the raw text.
 */

import { languageForPath } from "./highlight.js";

export type DiffKind = "context" | "add" | "del";

export interface DiffLine {
  kind: DiffKind;
  text: string;
}

const OLD_MARKER = "--- old ---";
const NEW_MARKER = "--- new ---";

/** Classic LCS line diff (context + del + add; no hunk compression). */
export function diffLines(oldText: string, newText: string): DiffLine[] {
  const a = oldText.length === 0 ? [] : oldText.split("\n");
  const b = newText.length === 0 ? [] : newText.split("\n");
  const n = a.length;
  const m = b.length;
  const dp: number[][] = Array.from({ length: n + 1 }, () => new Array<number>(m + 1).fill(0));
  for (let i = n - 1; i >= 0; i -= 1) {
    for (let j = m - 1; j >= 0; j -= 1) {
      dp[i]![j] = a[i] === b[j] ? (dp[i + 1]![j + 1] ?? 0) + 1 : Math.max(dp[i + 1]![j] ?? 0, dp[i]![j + 1] ?? 0);
    }
  }
  const out: DiffLine[] = [];
  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    if (a[i] === b[j]) {
      out.push({ kind: "context", text: a[i] as string });
      i += 1;
      j += 1;
    } else if ((dp[i + 1]![j] ?? 0) >= (dp[i]![j + 1] ?? 0)) {
      out.push({ kind: "del", text: a[i] as string });
      i += 1;
    } else {
      out.push({ kind: "add", text: b[j] as string });
      j += 1;
    }
  }
  while (i < n) out.push({ kind: "del", text: a[i++] as string });
  while (j < m) out.push({ kind: "add", text: b[j++] as string });
  return out;
}

/** Parse the kernel's `edit <path>\n--- old ---\n…\n--- new ---\n…` shape.
 * The pre-marker header (the target path) is kept as a leading context line.
 * Returns null when there is no marker pair or no line change, so callers
 * fall back to the plain preview (never render an empty card). */
export function previewToDiff(preview: string): DiffLine[] | null {
  const lines = preview.split("\n");
  const oldIndex = lines.findIndex((line) => line.trim() === OLD_MARKER);
  const newIndex = lines.findIndex((line) => line.trim() === NEW_MARKER);
  if (oldIndex === -1 || newIndex === -1 || newIndex < oldIndex) return null;
  const header = lines
    .slice(0, oldIndex)
    .filter((line) => line.trim().length > 0)
    .join("\n");
  const oldText = lines.slice(oldIndex + 1, newIndex).join("\n");
  const newText = lines.slice(newIndex + 1).join("\n");
  const body = diffLines(oldText, newText);
  if (!body.some((line) => line.kind !== "context")) return null;
  return header ? [{ kind: "context", text: header }, ...body] : body;
}

/** Parse edit-shaped tool arguments (`old_string`/`new_string`). Returns
 * null for any other argument shape — never guessed. */
function editArgs(argsJson: string): { oldText: string; newText: string } | null {
  let parsed: unknown;
  try {
    parsed = JSON.parse(argsJson);
  } catch {
    return null;
  }
  const record = parsed as Record<string, unknown> | null;
  const oldText = record?.["old_string"];
  const newText = record?.["new_string"];
  if (typeof oldText !== "string" || typeof newText !== "string") return null;
  return { oldText, newText };
}

/** Unified diff lines for an edit-shaped tool call (null when not an edit or
 * nothing changed). */
export function editArgsToDiff(argsJson: string): DiffLine[] | null {
  const parsed = editArgs(argsJson);
  if (!parsed) return null;
  const lines = diffLines(parsed.oldText, parsed.newText);
  return lines.some((line) => line.kind !== "context") ? lines : null;
}

/** Target path of an edit-shaped tool call (for titles + highlighting). */
export function editPathFromArgs(argsJson: string): string | null {
  let parsed: unknown;
  try {
    parsed = JSON.parse(argsJson);
  } catch {
    return null;
  }
  const path = (parsed as Record<string, unknown> | null)?.["path"];
  return typeof path === "string" && path ? path : null;
}

/** Indices where a changed hunk starts (first non-context line after a
 * context run). Used by the `/diff` viewer's hunk jumps. */
export function hunkStarts(lines: readonly DiffLine[]): number[] {
  const starts: number[] = [];
  lines.forEach((line, index) => {
    if (line.kind === "context") return;
    const previous = index > 0 ? lines[index - 1] : undefined;
    if (!previous || previous.kind === "context") starts.push(index);
  });
  return starts;
}

export interface DiffEntry {
  title: string;
  lang?: string;
  lines: DiffLine[];
  /** The line cap trimmed this entry — the viewer says so instead of hiding it. */
  truncated: boolean;
}

export interface DiffEntryOptions {
  maxEntries?: number;
  maxLines?: number;
}

/** Entries for the `/diff` viewer: the pending approval preview first (it is
 * the only diff that still needs a decision), then edit-shaped tool calls
 * newest-first. Bounded: never unbounded scrollback in the overlay. */
export function collectDiffEntries(
  messages: readonly {
    tool?: { capabilityId: string; argsJson: string } | undefined;
  }[],
  pending: { title: string; preview: string } | null,
  options: DiffEntryOptions = {},
): DiffEntry[] {
  const maxEntries = options.maxEntries ?? 20;
  const maxLines = options.maxLines ?? 400;
  const entries: DiffEntry[] = [];
  const add = (title: string, path: string | null, lines: DiffLine[]): void => {
    const lang = path ? languageForPath(path) : undefined;
    const truncated = lines.length > maxLines;
    entries.push({
      title,
      lines: truncated ? lines.slice(0, maxLines) : lines,
      truncated,
      ...(lang ? { lang } : {}),
    });
  };
  if (pending) {
    const lines = previewToDiff(pending.preview);
    if (lines) {
      const header = lines[0]?.kind === "context" ? lines[0].text.replace(/^edit\s+/, "").trim() : null;
      add(pending.title, header, lines);
    }
  }
  for (let i = messages.length - 1; i >= 0 && entries.length < maxEntries; i -= 1) {
    const tool = messages[i]?.tool;
    if (!tool) continue;
    const lines = editArgsToDiff(tool.argsJson);
    if (!lines) continue;
    const path = editPathFromArgs(tool.argsJson);
    add(`${tool.capabilityId} · ${path ?? tool.capabilityId}`, path, lines);
  }
  return entries.slice(0, maxEntries);
}
