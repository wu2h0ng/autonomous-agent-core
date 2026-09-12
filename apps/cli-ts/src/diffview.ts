/**
 * Unified-diff rendering for approval previews (wired in App.tsx) and edit
 * tool details. Line-level LCS diff; deterministic and pure. Fail-soft at
 * the call site: a preview without the kernel's old/new markers, or with no
 * line change, returns null and the caller renders the raw text.
 */

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
