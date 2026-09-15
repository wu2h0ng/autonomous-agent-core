/**
 * P2 workspace sampling for the sidebar (read-only, local, bounded).
 *
 * This is view-layer inspection of the user's own working tree — no
 * capability/permit/approval path is involved and nothing is written. All
 * commands are timeboxed and fail-soft: a non-git workspace yields a note
 * instead of throwing.
 */
import { execFileSync } from "node:child_process";
import { displayLines, parseGitStatus, type FileEntry } from "./panels.js";

export interface WorkspaceSample {
  files: FileEntry[];
  diff: string[];
  note: string | null;
}

export function sampleWorkspace(
  workspace: string,
  diffLines = 500,
): WorkspaceSample {
  const status = git(workspace, ["status", "--porcelain"]);
  if (status === null) {
    return { files: [], diff: [], note: "(not a git worktree)" };
  }
  const diff = git(workspace, ["diff", "--no-color"]);
  return {
    files: parseGitStatus(status),
    diff: displayLines(diff ?? "", diffLines),
    note: null,
  };
}

function git(workspace: string, args: string[]): string | null {
  try {
    return execFileSync("git", ["-C", workspace, ...args], {
      encoding: "utf8",
      stdio: ["ignore", "pipe", "ignore"],
      timeout: 3000,
      maxBuffer: 4 * 1024 * 1024,
    });
  } catch {
    return null;
  }
}
