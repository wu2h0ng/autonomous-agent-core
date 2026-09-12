/**
 * Composer input history — pure state so the semantics are unit-tested
 * without a terminal. Mirrors mainstream CLI behaviour (Claude Code / Codex
 * / opencode): ↑ recalls older entries, ↓ walks back to the live draft, and
 * Ctrl-R searches reverse-chronologically.
 */

export class InputHistory {
  private entries: string[] = [];
  /** Cursor into entries; entries.length means "at the live draft". */
  private cursor = 0;
  private draft = "";

  add(text: string): void {
    const trimmed = text.trim();
    if (!trimmed) return;
    if (this.entries[this.entries.length - 1] !== trimmed) this.entries.push(trimmed);
    this.cursor = this.entries.length;
    this.draft = "";
  }

  /** Move one entry older (or stay at the oldest). Returns composer text. */
  prev(current: string): string {
    if (this.entries.length === 0) return current;
    if (this.cursor === this.entries.length) this.draft = current;
    if (this.cursor > 0) this.cursor -= 1;
    return this.entries[this.cursor] ?? current;
  }

  /** Move one entry newer; past the newest returns the saved live draft. */
  next(): string {
    if (this.entries.length === 0) return this.draft;
    if (this.cursor < this.entries.length - 1) {
      this.cursor += 1;
      return this.entries[this.cursor] ?? this.draft;
    }
    this.cursor = this.entries.length;
    return this.draft;
  }

  /** Reverse-chronological substring search, case-insensitive, deduped. */
  search(query: string): string[] {
    const needle = query.trim().toLowerCase();
    const seen = new Set<string>();
    const matches: string[] = [];
    for (let i = this.entries.length - 1; i >= 0; i -= 1) {
      const entry = this.entries[i];
      if (entry === undefined) continue;
      if (needle && !entry.toLowerCase().includes(needle)) continue;
      if (seen.has(entry)) continue;
      seen.add(entry);
      matches.push(entry);
    }
    return matches;
  }

  get size(): number {
    return this.entries.length;
  }

  reset(): void {
    this.entries = [];
    this.cursor = 0;
    this.draft = "";
  }
}
