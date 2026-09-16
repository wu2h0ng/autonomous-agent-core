/**
 * P2 pure panel logic (no renderer import -> unit-testable under Node).
 *
 * The full-screen view adds a right sidebar (files + diff) next to the
 * transcript. Panel visibility, focus cycling, git-status parsing and the
 * CLI flags are pure functions so they can be tested without Bun/@opentui.
 */
import { SIDEBAR_MIN_WIDTH } from "../layout.js";

export type PanelId = "transcript" | "agents" | "files" | "diff";
export interface FileEntry {
  status: string;
  path: string;
}

export interface ViewFlags {
  /** --no-animation: static mode (renderer redraw capped, no animated affordances). */
  noAnimation: boolean;
  /** --no-panels: force the single transcript panel. */
  withPanels: boolean;
  /** --no-agents: hide the read-only agents/task tree panel. */
  withAgents: boolean;
}

export function parseViewFlags(argv: readonly string[]): ViewFlags {
  return {
    noAnimation: argv.includes("--no-animation"),
    withPanels: !argv.includes("--no-panels"),
    withAgents: !argv.includes("--no-agents"),
  };
}

/**
 * Sidebar needs room: reuse the chipset/narrow threshold (>=100 cols), so a
 * narrow terminal degrades to the P1 single-panel view instead of clipping.
 */
export function visiblePanels(
  width: number,
  withPanels: boolean,
  withAgents = true,
): PanelId[] {
  if (withPanels && width >= SIDEBAR_MIN_WIDTH) {
    return withAgents
      ? ["transcript", "agents", "files", "diff"]
      : ["transcript", "files", "diff"];
  }
  return ["transcript"];
}

export function nextPanel(current: PanelId, visible: readonly PanelId[]): PanelId {
  const list = visible.length > 0 ? visible : (["transcript"] as PanelId[]);
  const index = list.indexOf(current);
  return list[(index + 1) % list.length] as PanelId;
}

/** `git status --porcelain` -> entries. Blank lines skipped; status kept verbatim. */
export function parseGitStatus(porcelain: string): FileEntry[] {
  const out: FileEntry[] = [];
  for (const raw of porcelain.split("\n")) {
    if (raw.trim() === "") continue;
    const status = raw.slice(0, 2).trim();
    const path = raw.slice(3).trim();
    if (path !== "") out.push({ status: status === "" ? "?" : status, path });
  }
  return out;
}

/** Split into display lines, bounded so a huge diff cannot stall a frame. */
export function displayLines(text: string, max: number): string[] {
  const lines = text.replace(/\r\n/g, "\n").replace(/\s+$/, "").split("\n");
  return lines.length > max ? lines.slice(0, max) : lines;
}

export function filePanelLines(
  files: readonly FileEntry[],
  note: string | null,
  max = 400,
): string[] {
  if (files.length === 0) return [note ?? "(clean)"];
  return displayLines(
    files.map((f) => `${f.status.padEnd(2)} ${f.path}`).join("\n"),
    max,
  );
}
