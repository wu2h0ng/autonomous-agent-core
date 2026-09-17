/**
 * Syntax highlighting for code/diff rendering (gap P0 #5). Reuses the
 * cli-highlight engine already pulled in by marked-terminal (declared as a
 * direct dependency). Fail-soft: any parse/language error returns the input
 * verbatim, so rendering never breaks on odd content.
 */
import { highlight } from "cli-highlight";

export const EXTENSION_LANGUAGE: Record<string, string> = {
  ts: "typescript",
  tsx: "typescript",
  js: "javascript",
  jsx: "javascript",
  mjs: "javascript",
  cjs: "javascript",
  json: "json",
  py: "python",
  rb: "ruby",
  go: "go",
  rs: "rust",
  java: "java",
  c: "c",
  h: "c",
  cpp: "cpp",
  css: "css",
  scss: "scss",
  html: "xml",
  xml: "xml",
  md: "markdown",
  sh: "bash",
  bash: "bash",
  zsh: "bash",
  sql: "sql",
  yml: "yaml",
  yaml: "yaml",
  toml: "ini",
};

export function languageForPath(path: string): string | undefined {
  const dot = path.lastIndexOf(".");
  if (dot === -1) return undefined;
  return EXTENSION_LANGUAGE[path.slice(dot + 1).toLowerCase()];
}

export function highlightCode(code: string, language?: string): string {
  if (!language) return code;
  try {
    return highlight(code, { language, ignoreIllegals: true }).replace(/\n$/, "");
  } catch {
    return code;
  }
}
