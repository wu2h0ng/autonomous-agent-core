/**
 * FROZEN Ink `HomeView` baseline — the parity target for the full-screen home
 * panel (#18), captured from the Ink renderer and recorded here as data.
 *
 * Why frozen rather than rendered live: `test/opentui-home.test.tsx` used to
 * render Ink's `HomeView` at test time to compare against, which made Ink a
 * test-time dependency of the SURVIVING view. Retiring Ink would have destroyed
 * the parity baseline with it. The snapshot now lives here (no Ink import), and
 * `test/ink-home-baseline.test.tsx` re-measures the live Ink output against it
 * for as long as Ink still exists — so drift is still caught today, and the
 * guarantee survives the deletion.
 *
 * Capture inputs are part of the fixture: a snapshot without its inputs is not
 * reproducible. Normalisation: the box border and padding are stripped, then
 * whitespace is squashed, then empty rows are dropped.
 */
import { homedir } from "node:os";

/** Inputs the snapshot below was captured with. Also used by the recorder. */
export const BASELINE_INPUTS = {
  workspace: `${homedir()}/proj/deep/workspace`,
  branch: "feature/x",
  version: "0.1.0",
  columns: 100,
} as const;

/** Inputs for the unconfigured-provider / no-branch variant. */
export const BASELINE_INPUTS_UNCONFIGURED = {
  workspace: `${homedir()}/proj/deep/workspace`,
  branch: null,
  version: "0.1.0",
  columns: 100,
} as const;

/**
 * Ink `HomeView` content lines with a configured model (model="deepseek-chat",
 * provider=null). Border rows are already removed.
 */
export const INK_HOME_BASELINE: readonly string[] = [
  "NOEM · governed terminal agent",
  "workspace workspace",
  "path ~/proj/deep/workspace",
  "git feature/x",
  "provider openai-compatible · deepseek-chat",
  "version 0.1.0",
  "Quick start",
  "· Describe a task and press Enter (shift+tab switches mode)",
  "· /help commands · @file add context · !cmd shell · /provider model",
];

/** The same panel with no branch and no configured model. */
export const INK_HOME_BASELINE_UNCONFIGURED: readonly string[] = [
  "NOEM · governed terminal agent",
  "workspace workspace",
  "path ~/proj/deep/workspace",
  "git not a git repository",
  "provider not configured — /provider set <base-url> <model>",
  "version 0.1.0",
  "Quick start",
  "· Describe a task and press Enter (shift+tab switches mode)",
  "· /help commands · @file add context · !cmd shell · /provider model",
];

/**
 * The mode tip Ink advertises. Kept as a named constant because it is a
 * RECORDED DEVIATION, not an aspiration: no `shift+tab` binding exists anywhere
 * in this repo (the string occurs exactly once — inside that very tip), so the
 * full-screen panel ships `/mode switches permission mode` instead.
 */
export const INK_MODE_TIP = "· Describe a task and press Enter (shift+tab switches mode)";

/** Whitespace-insensitive, so Ink's padding cannot mask a real text change. */
export const squash = (value: string): string => value.replace(/\s+/g, " ").trim();

/** Normalise an Ink frame: strip the box border, squash, drop empty rows. */
export const inkFrameLines = (frame: string): string[] =>
  frame
    .split("\n")
    .map((line) => squash(line.replace(/[│╭╮╰╯─]/g, "")))
    .filter((line) => line !== "");
