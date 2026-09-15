/**
 * P2 workspace sampling for the sidebar (read-only, local, bounded, async).
 *
 * This is view-layer inspection of the user's own working tree — no
 * capability/permit/approval path is involved and nothing is written. Commands
 * are timeboxed and fail-soft: a non-git workspace yields a note. Sampling is
 * asynchronous so a large `git diff` cannot block the render loop or the
 * controller tick.
 */
import { execFile } from "node:child_process";
import { displayLines, parseGitStatus, type FileEntry } from "./panels.js";

export interface WorkspaceSample {
  files: FileEntry[];
  diff: string[];
  note: string | null;
}

export const EMPTY_SAMPLE: WorkspaceSample = { files: [], diff: [], note: null };

export async function sampleWorkspace(
  workspace: string,
  diffLines = 500,
): Promise<WorkspaceSample> {
  const status = await git(workspace, ["status", "--porcelain"]);
  if (status === null) {
    return { files: [], diff: [], note: "(not a git worktree)" };
  }
  const diff = await git(workspace, ["diff", "--no-color"]);
  return {
    files: parseGitStatus(status),
    diff: displayLines(diff ?? "", diffLines),
    note: null,
  };
}

function git(workspace: string, args: string[]): Promise<string | null> {
  return new Promise((resolve) => {
    execFile(
      "git",
      ["-C", workspace, ...args],
      {
        encoding: "utf8",
        timeout: 3000,
        maxBuffer: 4 * 1024 * 1024,
      },
      (error, stdout) => resolve(error ? null : stdout),
    );
  });
}
