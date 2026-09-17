/**
 * Parity slice A view helpers: a bounded list window for overlays (command
 * palette, selectors). Pure so the viewport arithmetic is testable without a
 * renderer — a wrong window is exactly the kind of bug that hides trailing
 * commands or the highlighted row.
 */
export interface Window<T> {
  /** The visible slice. */
  items: T[];
  /** Index of the highlighted item *within* `items` (or -1 when empty). */
  index: number;
  /** Items hidden before/after the window (for "... N more" hints). */
  before: number;
  after: number;
}

export function sliceWindow<T>(
  items: readonly T[],
  cursor: number,
  size: number,
): Window<T> {
  const total = items.length;
  if (total === 0 || size <= 0) {
    return { items: [], index: -1, before: 0, after: total };
  }
  const clamped = Math.min(Math.max(cursor, 0), total - 1);
  const half = Math.floor(size / 2);
  let start = clamped - half;
  if (start < 0) start = 0;
  if (start + size > total) start = Math.max(0, total - size);
  const end = Math.min(total, start + size);
  return {
    items: items.slice(start, end),
    index: clamped - start,
    before: start,
    after: total - end,
  };
}

/** Largest number of content rows an overlay box may claim. */
export const OVERLAY_MAX_ROWS = 12;

/**
 * Height in terminal rows for an overlay box holding `contentRows` rows.
 *
 * This has to be explicit. A sibling `<text>` inside a flex column measures
 * zero height in opentui, and a border box with no height measured the same
 * way, so every overlay used to be painted ON TOP of its neighbours (the
 * palette's items landed on the composer's border row). With an explicit height
 * the box claims its rows and the flexible transcript shrinks to match.
 */
export function overlayRows(contentRows: number): number {
  return Math.min(Math.max(contentRows, 0) + 2, OVERLAY_MAX_ROWS);
}
