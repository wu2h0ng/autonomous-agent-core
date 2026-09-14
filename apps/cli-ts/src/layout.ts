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

export function layoutFor(width: number): Layout {
  if (width < 60) {
    return { narrow: true, showDescriptions: false, footerFields: false };
  }
  if (width < 100) {
    return { narrow: false, showDescriptions: true, footerFields: false };
  }
  return { narrow: false, showDescriptions: true, footerFields: true };
}
