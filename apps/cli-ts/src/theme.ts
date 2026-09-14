/**
 * Semantic colour tokens + named themes (gap P0 #1 / P1 #22).
 *
 * A token value is a concrete Ink colour name **or `undefined`, meaning
 * "leave the terminal's own colour alone"**. `inherit` is entirely
 * undefined: it never fights the operator's terminal theme and relies on
 * markers (✓/⧗/✗, +/-) plus bold/dim for structure. Every other theme can
 * blank individual tokens the same way.
 *
 * Diff, thinking and tool-status tokens are explicit so the approval card,
 * the diff viewer and the tool cards never share a colour by accident.
 */

export interface ThemeColors {
  user: string | undefined;
  assistant: string | undefined;
  system: string | undefined;
  notice: string | undefined;
  toolPending: string | undefined;
  toolDone: string | undefined;
  toolFailed: string | undefined;
  approvalBorder: string | undefined;
  approvalTitle: string | undefined;
  danger: string | undefined;
  accent: string | undefined;
  border: string | undefined;
  paletteSelected: string | undefined;
  footer: string | undefined;
  diffAdd: string | undefined;
  diffDel: string | undefined;
  diffContext: string | undefined;
  thinking: string | undefined;
}

export const THEMES: Record<string, ThemeColors> = {
  default: {
    user: "cyan",
    assistant: undefined,
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
    diffAdd: "green",
    diffDel: "red",
    diffContext: "gray",
    thinking: "magenta",
  },
  ansi: {
    user: "blueBright",
    assistant: undefined,
    system: "yellow",
    notice: "gray",
    toolPending: "yellow",
    toolDone: "greenBright",
    toolFailed: "redBright",
    approvalBorder: "yellow",
    approvalTitle: "yellow",
    danger: "redBright",
    accent: "blueBright",
    border: "gray",
    paletteSelected: "blueBright",
    footer: "gray",
    diffAdd: "greenBright",
    diffDel: "redBright",
    diffContext: "gray",
    thinking: "magentaBright",
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
    diffAdd: "white",
    diffDel: "white",
    diffContext: "gray",
    thinking: "gray",
  },
  /** Terminal-native: no colour codes at all (opencode `none` / Crush
   * `transparent`). Structure comes from markers and emphasis only. */
  inherit: {
    user: undefined,
    assistant: undefined,
    system: undefined,
    notice: undefined,
    toolPending: undefined,
    toolDone: undefined,
    toolFailed: undefined,
    approvalBorder: undefined,
    approvalTitle: undefined,
    danger: undefined,
    accent: undefined,
    border: undefined,
    paletteSelected: undefined,
    footer: undefined,
    diffAdd: undefined,
    diffDel: undefined,
    diffContext: undefined,
    thinking: undefined,
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

/** Ink props for a token: `{color}` when set, `{}` when the token means
 * "terminal default" — so `exactOptionalPropertyTypes` never sees an
 * explicit `color: undefined`. */
export function paint(color: string | undefined): { color?: string } {
  return color ? { color } : {};
}
