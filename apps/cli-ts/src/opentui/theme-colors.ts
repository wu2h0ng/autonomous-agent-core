/**
 * Bridge the repo theme tokens (Ink colour NAMES, src/theme.ts) to concrete hex
 * colours for opentui, which parses hex reliably. Pure + tested so a theme
 * change is provably visible in the rendered frame (see scripts/frame_reader.py).
 */
import { resolveTheme, type ThemeColors } from "../theme.js";

/** Ink colour name -> hex. Only the names used by src/theme.ts. */
export const INK_HEX: Record<string, string> = {
  white: "#ffffff",
  black: "#000000",
  gray: "#808080",
  grey: "#808080",
  red: "#cd3131",
  green: "#0dbc79",
  yellow: "#e5e510",
  blue: "#2472c8",
  cyan: "#11a8cd",
  blueBright: "#3b8eea",
};

export function hexFor(name: string): string {
  return INK_HEX[name] ?? name;
}

/** The active theme with every token resolved to a hex colour. */
export function viewTheme(name: string | null | undefined): ThemeColors {
  const theme = resolveTheme(name);
  const out: Record<string, string> = {};
  for (const [key, value] of Object.entries(theme)) {
    out[key] = hexFor(value);
  }
  return out as unknown as ThemeColors;
}
