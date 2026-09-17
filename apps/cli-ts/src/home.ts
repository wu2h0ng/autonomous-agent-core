/**
 * Home-screen content model, shared by the Ink view (the parity baseline) and
 * the full-screen view (#18).
 *
 * Deliberately free of BOTH `ink` and `@opentui/*`: retiring Ink must not strand
 * the content, and the two renderers only differ in how they paint a segment.
 *
 * Text is mirrored from `src/HomeView.tsx` verbatim, with ONE measured
 * deviation: Ink's tip advertises `shift+tab switches mode`, but no such
 * binding exists anywhere in this repo — not in Ink's `useInput`, not in
 * `keys.ts`, not in `viewkeys.ts` (`shift+tab` occurs exactly once in the whole
 * app: inside that tip string). Permission mode is actually set by `/mode`.
 * The full-screen panel therefore ships the true instruction, and the false
 * string is recorded rather than copied.
 */
import { homedir } from "node:os";
import { basename, sep } from "node:path";
import type { ThemeColors } from "./theme.js";

/** Home-relative, single-line path bounded to the terminal width. */
export function shortenPath(workspace: string, columns: number): string {
  const home = homedir();
  const isHome = workspace === home || workspace.startsWith(`${home}${sep}`);
  const value = isHome ? `~${workspace.slice(home.length)}` : workspace;
  const limit = Math.max(20, columns);
  if (value.length <= limit) return value;
  const parts = value.split("/").filter(Boolean);
  const tail = parts.slice(-2).join("/");
  const prefix = value.startsWith("~") ? "~/" : "/";
  const short = `${prefix}…/${tail}`;
  // Always bound the result: a single very long segment must not overflow.
  return short.length <= limit ? short : `…${short.slice(-(limit - 1))}`;
}

/** One coloured run inside a home row. */
export interface HomeSegment {
  text: string;
  token: keyof ThemeColors;
  bold?: boolean;
  dim?: boolean;
}

export type HomeRow = HomeSegment[];

export interface HomeInput {
  workspace: string;
  branch: string | null;
  version: string;
  provider: string | null;
  model: string | null;
  /** Terminal width, used to bound the `path` row (Ink passes `columns - 16`). */
  columns?: number;
}

export interface HomeFacts {
  /** Directory basename — the short name shown next to `workspace`. */
  name: string;
  /** `shortenPath(...)` of the full workspace path. */
  path: string;
  branch: string | null;
  provider: string | null;
  model: string | null;
  version: string;
}

/** Label column width, matching Ink's hand-padded labels. */
const LABEL_WIDTH = 11;

export const HOME_FIELD_LABELS = ["workspace", "path", "git", "provider", "version"] as const;

/** The `provider` value: a configured model, or the exact setup instruction. */
export function providerValue(facts: HomeFacts): { text: string; dim: boolean } {
  if (facts.model) {
    return { text: `${facts.provider ?? "openai-compatible"} · ${facts.model}`, dim: false };
  }
  return { text: "not configured — /provider set <base-url> <model>", dim: true };
}

export function homeFacts(input: HomeInput): HomeFacts {
  const columns = input.columns ?? 100;
  return {
    name: basename(input.workspace) || input.workspace,
    path: shortenPath(input.workspace, columns - 16),
    branch: input.branch,
    provider: input.provider,
    model: input.model,
    version: input.version,
  };
}

const label = (text: string): HomeSegment => ({
  text: text.padEnd(LABEL_WIDTH),
  token: "accent",
});

/** The `workspace / path / git / provider / version` rows. */
export function homeFieldRows(facts: HomeFacts): HomeRow[] {
  const provider = providerValue(facts);
  return [
    [label("workspace"), { text: facts.name, token: "assistant" }],
    [label("path"), { text: facts.path, token: "notice", dim: true }],
    [label("git"), { text: facts.branch ?? "not a git repository", token: "notice", dim: true }],
    [
      label("provider"),
      provider.dim
        ? { text: provider.text, token: "notice", dim: true }
        : { text: provider.text, token: "assistant" },
    ],
    [label("version"), { text: facts.version, token: "notice", dim: true }],
  ];
}

export const HOME_TIP_TITLE = "Quick start";

export function homeTipRows(): HomeRow[] {
  return [
    [{ text: HOME_TIP_TITLE, token: "notice", bold: true }],
    [
      {
        text: "· Describe a task and press Enter (/mode switches permission mode)",
        token: "notice",
        dim: true,
      },
    ],
    [
      {
        text: "· /help commands · @file add context · !cmd shell · /provider model",
        token: "notice",
        dim: true,
      },
    ],
  ];
}

export interface HomePanel {
  header: HomeRow;
  fields: HomeRow[];
  tips: HomeRow[];
}

/**
 * The whole panel for a given width. `narrow` mirrors Ink's compact variant:
 * a three-line text block instead of a bordered card.
 */
export function homePanel(facts: HomeFacts, narrow = false): HomePanel {
  if (narrow) {
    return {
      header: [
        { text: "NOEM", token: "accent", bold: true },
        { text: ` · v${facts.version}`, token: "notice", dim: true },
      ],
      fields: [[{ text: `workspace ${facts.name}`, token: "notice", dim: true }]],
      tips: [[{ text: "/help · @file · !cmd · /provider", token: "notice", dim: true }]],
    };
  }
  return {
    header: [
      { text: "NOEM", token: "accent", bold: true },
      { text: " · governed terminal agent", token: "notice", dim: true },
    ],
    fields: homeFieldRows(facts),
    tips: homeTipRows(),
  };
}

/**
 * Ink's `showHome`: the welcome panel owns an otherwise-empty transcript.
 * Takes the two counts (not the arrays) so the call site cannot accidentally
 * pass a filtered list.
 */
export function shouldShowHome(finalizedCount: number, activeCount: number): boolean {
  return finalizedCount === 0 && activeCount === 0;
}
