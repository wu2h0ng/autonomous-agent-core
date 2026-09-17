/**
 * Narrow-terminal degradation policy (gap P1 #21). Pure threshold logic so
 * the thresholds are testable; App applies it to footer hints, palette
 * descriptions and diff layout.
 */
export interface Layout {
  narrow: boolean;
  /** Show command descriptions next to names in the palette. */
  showDescriptions: boolean;
  /** Show the right-hand footer fields (tokens/cost/events). */
  footerFields: boolean;
}

/** Below this width the full-screen sidebar has no room (shared with panels). */
export const SIDEBAR_MIN_WIDTH = 100;

/** Composer box height with a single-line draft (two border rows + three lines). */
export const COMPOSER_MIN_ROWS = 5;

/** Hard cap so a long draft cannot swallow the transcript. */
const COMPOSER_MAX_ROWS = 12;

/**
 * Height for the composer box, in terminal rows.
 *
 * Ink's composer has no fixed height and simply grows with the draft; the
 * full-screen view has a definite-height column, so the growth has to be
 * explicit AND bounded — an unbounded composer would squeeze the transcript to
 * nothing on a short terminal. Below the cap this is Ink's behaviour (one row
 * per draft line plus the two border rows); above it the textarea scrolls.
 */
export function composerRows(draft: string, terminalRows: number): number {
  const lines = draft === "" ? 1 : draft.split("\n").length;
  // Never claim more than a third of the screen.
  const cap = Math.max(COMPOSER_MIN_ROWS, Math.min(COMPOSER_MAX_ROWS, Math.floor(terminalRows / 3)));
  return Math.max(COMPOSER_MIN_ROWS, Math.min(cap, lines + 2));
}

export function layoutFor(width: number): Layout {
  if (width < 60) {
    return { narrow: true, showDescriptions: false, footerFields: false };
  }
  if (width < SIDEBAR_MIN_WIDTH) {
    return { narrow: false, showDescriptions: true, footerFields: false };
  }
  return { narrow: false, showDescriptions: true, footerFields: true };
}
