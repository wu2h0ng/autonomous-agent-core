/**
 * External-editor bridge (Ctrl-G / $EDITOR) — mainstream long-prompt escape
 * hatch (Claude Code / Goose / Aider). Writes the current composer draft to
 * a temp file, hands it to the configured editor, and reads it back. A
 * missing editor or a failed spawn returns null and the composer is left
 * untouched — never a silent data loss.
 */
import { spawnSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

export interface EditorResult {
  text: string;
  changed: boolean;
}

export interface EditorOptions {
  /** Override the editor command (tests); defaults to $VISUAL then $EDITOR. */
  editor?: string;
}

export function openExternalEditor(
  current: string,
  options: EditorOptions = {},
): EditorResult | null {
  const editor = options.editor ?? process.env.VISUAL ?? process.env.EDITOR ?? "";
  const [command, ...args] = editor.split(/\s+/).filter(Boolean);
  if (!command) return null;

  const dir = mkdtempSync(join(tmpdir(), "agent-os-edit-"));
  const file = join(dir, "prompt.md");
  try {
    writeFileSync(file, current, "utf8");
    const result = spawnSync(command, [...args, file], { stdio: "inherit" });
    if (result.error) return null;
    let text: string;
    try {
      text = readFileSync(file, "utf8");
    } catch {
      return null; // editor removed the temp file — never lose the draft
    }
    const stripped = text.replace(/\n$/, "");
    return { text: stripped, changed: stripped !== current };
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
}
