/**
 * Composer input history — pure state so the semantics are unit-tested
 * without a terminal. Mirrors mainstream CLI behaviour (Claude Code / Codex
 * / opencode): ↑ recalls older entries, ↓ walks back to the live draft, and
 * Ctrl-R searches reverse-chronologically. May be seeded from persisted
 * local state and exported for persistence.
 */

export class InputHistory {
  private items: string[] = [];
  /** Cursor into items; items.length means "at the live draft". */
  private cursor = 0;
  private draft = "";

  constructor(initial: readonly string[] = []) {
    for (const entry of initial) this.add(entry);
  }

  add(text: string): void {
    const trimmed = text.trim();
    if (!trimmed) return;
    if (this.items[this.items.length - 1] !== trimmed) this.items.push(trimmed);
    this.cursor = this.items.length;
    this.draft = "";
  }

  /** Move one entry older (or stay at the oldest). Returns composer text. */
  prev(current: string): string {
    if (this.items.length === 0) return current;
    if (this.cursor === this.items.length) this.draft = current;
    if (this.cursor > 0) this.cursor -= 1;
    return this.items[this.cursor] ?? current;
  }

  /** Move one entry newer; past the newest returns the saved live draft. */
  next(): string {
    if (this.items.length === 0) return this.draft;
    if (this.cursor < this.items.length - 1) {
      this.cursor += 1;
      return this.items[this.cursor] ?? this.draft;
    }
    this.cursor = this.items.length;
    return this.draft;
  }

  /** Reverse-chronological substring search, case-insensitive, deduped. */
  search(query: string): string[] {
    const needle = query.trim().toLowerCase();
    const seen = new Set<string>();
    const matches: string[] = [];
    for (let i = this.items.length - 1; i >= 0; i -= 1) {
      const entry = this.items[i];
      if (entry === undefined) continue;
      if (needle && !entry.toLowerCase().includes(needle)) continue;
      if (seen.has(entry)) continue;
      seen.add(entry);
      matches.push(entry);
    }
    return matches;
  }

  /** Chronological snapshot for persistence. */
  all(): string[] {
    return [...this.items];
  }

  get size(): number {
    return this.items.length;
  }

  reset(): void {
    this.items = [];
    this.cursor = 0;
    this.draft = "";
  }
}
