/**
 * Semantic colour tokens + named themes (gap P0 #1 / P1 #22).
 *
 * One token set per theme; the active theme name lives in the controller
 * (operator-only `/theme`), so no `as const`. Colours are concrete Ink names
 * so `Text`'s exactOptionalPropertyTypes typing stays simple.
 */

export interface ThemeColors {
  user: string;
  assistant: string;
  system: string;
  notice: string;
  toolPending: string;
  toolDone: string;
  toolFailed: string;
  approvalBorder: string;
  approvalTitle: string;
  danger: string;
  accent: string;
  border: string;
  paletteSelected: string;
  footer: string;
}

export const THEMES: Record<string, ThemeColors> = {
  default: {
    user: "cyan",
    assistant: "white",
    system: "yellow",
    notice: "gray",
    toolPending: "yellow",
    toolDone: "green",
    toolFailed: "red",
    approvalBorder: "yellow",
    approvalTitle: "yellow",
    danger: "red",
    accent: "cyan",
    border: "gray",
    paletteSelected: "cyan",
    footer: "gray",
  },
  ansi: {
    user: "blueBright",
    assistant: "white",
    system: "yellow",
    notice: "gray",
    toolPending: "yellow",
    toolDone: "green",
    toolFailed: "red",
    approvalBorder: "yellow",
    approvalTitle: "yellow",
    danger: "red",
    accent: "blueBright",
    border: "gray",
    paletteSelected: "blueBright",
    footer: "gray",
  },
  mono: {
    user: "white",
    assistant: "white",
    system: "gray",
    notice: "gray",
    toolPending: "gray",
    toolDone: "white",
    toolFailed: "white",
    approvalBorder: "gray",
    approvalTitle: "white",
    danger: "white",
    accent: "white",
    border: "gray",
    paletteSelected: "white",
    footer: "gray",
  },
};

export const DEFAULT_THEME_NAME = "default";

export function themeNames(): string[] {
  return Object.keys(THEMES);
}

export function resolveTheme(name: string | null | undefined): ThemeColors {
  if (name && Object.prototype.hasOwnProperty.call(THEMES, name)) {
    return THEMES[name] as ThemeColors;
  }
  return THEMES[DEFAULT_THEME_NAME] as ThemeColors;
}

/** Cycle to the next theme (for `/theme next`). */
export function nextTheme(name: string): string {
  const names = themeNames();
  const index = names.indexOf(name);
  return names[(index + 1) % names.length] ?? DEFAULT_THEME_NAME;
}
