/**
 * `@file` mention detection + completion (mainstream: Claude/Gemini/opencode
 * `@path` injection). Pure: App supplies the workspace file list fetched over
 * the read-only surface endpoint; this module only parses and ranks.
 */

export interface MentionToken {
  /** Index of the '@'. */
  start: number;
  /** Exclusive end of the current token (the cursor). */
  end: number;
  /** Text typed after '@' up to the cursor. */
  query: string;
}

/** Returns the active @token ending at `cursor`, or null. */
export function activeMention(text: string, cursor: number): MentionToken | null {
  let i = cursor - 1;
  while (i >= 0) {
    const char = text[i] as string;
    if (char === "@") {
      const prev = i === 0 ? "" : (text[i - 1] as string);
      if (i === 0 || /\s/.test(prev)) {
        return { start: i, end: cursor, query: text.slice(i + 1, cursor) };
      }
      return null;
    }
    if (/\s/.test(char)) return null;
    i -= 1;
  }
  return null;
}

/** Rank candidates: earliest substring match wins, then shortest path. */
export function filterMentions(paths: readonly string[], query: string, limit = 8): string[] {
  const needle = query.toLowerCase();
  if (!needle) {
    return [...paths].sort((a, b) => a.length - b.length).slice(0, limit);
  }
  return paths
    .map((path) => ({ path, index: path.toLowerCase().indexOf(needle) }))
    .filter((candidate) => candidate.index >= 0)
    .sort((a, b) => a.index - b.index || a.path.length - b.path.length)
    .slice(0, limit)
    .map((candidate) => candidate.path);
}

/** Replace the active @token with `replacement` and return the new state. */
export function applyMention(
  text: string,
  cursor: number,
  replacement: string,
): { value: string; cursor: number } {
  const token = activeMention(text, cursor);
  if (!token) return { value: text, cursor };
  const inserted = `@${replacement} `;
  return {
    value: text.slice(0, token.start) + inserted + text.slice(token.end),
    cursor: token.start + inserted.length,
  };
}
