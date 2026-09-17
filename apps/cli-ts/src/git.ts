/** Renderer-neutral workspace facts, shared by both CLI entries. */
import { execFileSync } from "node:child_process";

/**
 * Current git branch of `workspace`, or null when it is not a repository (or is
 * on a detached HEAD). Never throws: a missing/absent git must not stop the TUI.
 */
export function gitBranch(workspace: string): string | null {
  try {
    const out = execFileSync(
      "git",
      ["-C", workspace, "rev-parse", "--abbrev-ref", "HEAD"],
      { encoding: "utf8", stdio: ["ignore", "pipe", "ignore"] },
    );
    const branch = out.trim();
    return branch && branch !== "HEAD" ? branch : null;
  } catch {
    return null;
  }
}
