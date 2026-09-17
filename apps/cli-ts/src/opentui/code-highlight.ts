/**
 * Syntax highlighting for fenced code blocks in the opentui transcript (#16).
 *
 * Measured root cause (not the original hypothesis). opentui *does* give code
 * blocks a TreeSitterClient — `CodeRenderable` falls back to
 * `getTreeSitterClient()` — and that client works. What it does not have is a
 * grammar for most languages: the bundled default parser set is
 * `{javascript, typescript, markdown, markdown_inline, zig}`. A ```python
 * fence therefore resolves to a filetype with no parser and the client answers
 * `"No parser available for filetype python"`, so every token is painted with
 * the default foreground. Registering more SyntaxStyle scopes cannot fix that;
 * there are no highlights to style.
 *
 * Rather than vendor one tree-sitter wasm per language, this module reuses the
 * highlighter the Ink path already uses — cli-highlight -> highlight.js, whose
 * full 191-language set is already on disk — and feeds its token ranges back
 * into opentui through the *supported* `CodeRenderable.onHighlight` hook:
 *
 *   - `onHighlight` is called whenever the renderable has a non-empty filetype,
 *     even when the tree-sitter result is empty (`highlights.length >= 0`).
 *   - returning a non-empty range list routes rendering through
 *     `treeSitterToTextChunks`, which resolves each range's group name against
 *     the active SyntaxStyle (falling back from `a.b` to `a`).
 *
 * So a range triple `[start, end, scope]` is the whole contract; the scope
 * vocabulary below is what gets registered on the SyntaxStyle.
 */
import hljs from "highlight.js";
import type { CodeRenderable, MarkdownOptions, SimpleHighlight } from "@opentui/core";
import type { ThemeColors } from "../theme.js";
import { EXTENSION_LANGUAGE } from "../highlight.js";

/**
 * highlight.js token class -> theme token, for fenced blocks we highlight
 * ourselves. Scopes absent from this table (e.g. `emphasis`, `strong`) stay
 * unmapped on purpose: they fall through to the `default` style.
 *
 * Note the theme only carries six distinct hues (cyan `accent`/`user`,
 * white `assistant`, yellow `system`/`toolPending`, green `toolDone`, gray
 * `notice`/`border`/`footer`, red `toolFailed`/`danger`), so related token
 * families intentionally share one.
 */
export const HL_SCOPE_TOKEN: Readonly<Record<string, keyof ThemeColors>> = {
  // control flow / operators
  keyword: "accent",
  operator: "accent",
  subst: "accent",
  "template-tag": "accent",
  // declarations we scan for first
  title: "toolPending",
  function: "toolPending",
  section: "toolPending",
  name: "toolPending",
  tag: "toolPending",
  "selector-tag": "toolPending",
  built_in: "toolPending",
  type: "toolPending",
  // literals that read as "data"
  string: "toolDone",
  regexp: "toolDone",
  addition: "toolDone",
  code: "toolDone",
  link: "toolDone",
  number: "system",
  literal: "system",
  symbol: "system",
  bullet: "system",
  variable: "system",
  params: "system",
  attr: "system",
  "template-variable": "system",
  // prose-ish residue
  comment: "notice",
  quote: "notice",
  meta: "notice",
  deletion: "toolFailed",
};

/** Scopes that also render dim, so they recede behind real code. */
export const DIM_SCOPES: readonly string[] = ["comment", "quote", "meta"];

/**
 * Tree-sitter capture names (Neovim convention, e.g. `keyword.return`,
 * `function.method`). Registered so the languages whose grammar *is* bundled
 * (js/ts/markdown/zig) keep rendering in theme colours too — the resolver
 * falls back from `keyword.return` to `keyword`.
 */
export const TS_SCOPE_TOKEN: Readonly<Record<string, keyof ThemeColors>> = {
  keyword: "accent",
  operator: "accent",
  string: "toolDone",
  comment: "notice",
  function: "toolPending",
  title: "toolPending",
  type: "toolPending",
  constant: "system",
  number: "system",
  variable: "system",
};

/** The `default` scope: unstyled code text (also the block's baseline colour). */
const DEFAULT_SCOPE = "default";

export interface ScopeStyle {
  fg: string;
  dim?: boolean;
}

/**
 * The full scope table for a resolved (hex) theme: every scope the highlighter
 * can emit, plus `default`. Pure, so a theme swap is provably visible.
 */
export function highlightStyleTable(theme: ThemeColors): Record<string, ScopeStyle> {
  const table: Record<string, ScopeStyle> = { [DEFAULT_SCOPE]: { fg: theme.assistant } };
  for (const [scope, token] of Object.entries(HL_SCOPE_TOKEN)) {
    table[scope] = DIM_SCOPES.includes(scope)
      ? { fg: theme[token], dim: true }
      : { fg: theme[token] };
  }
  for (const [scope, token] of Object.entries(TS_SCOPE_TOKEN)) {
    table[scope] ??= { fg: theme[token] };
  }
  return table;
}

/**
 * Fence info string -> a highlight.js language id we can actually highlight.
 * ` ```py `, ` ```ts `, ` ```TypeScript ` all resolve; unknown info strings
 * return `undefined` so the block keeps whatever tree-sitter produced.
 *
 * The repo's extension map is consulted first so common fence aliases
 * (`py`, `ts`, `sh`, `yml`) resolve to canonical names — that keeps the
 * filetype we hand the renderable stable if a tree-sitter grammar is ever
 * registered for one of them.
 */
export function fenceLanguage(infoString: string | null | undefined): string | undefined {
  if (typeof infoString !== "string") return undefined;
  const first = infoString.trim().split(/\s+/)[0];
  if (first === undefined || first === "") return undefined;
  const token = first.replace(/^\./, "").toLowerCase();
  const canonical = EXTENSION_LANGUAGE[token] ?? token;
  if (hljs.getLanguage(canonical) !== undefined) return canonical;
  if (hljs.getLanguage(token) !== undefined) return token;
  return undefined;
}

/** highlight.js token tree: `{kind, children}` nodes with raw text leaves. */
type TokenNode = { kind?: string; children?: TokenNode[] } | string;

/**
 * Highlight `content` into `SimpleHighlight` triples. Fail-soft: an unknown
 * language, a parse failure or an unexpected result shape all yield `[]`, which
 * the caller reads as "leave the block to tree-sitter".
 */
export function codeHighlightRanges(
  content: string,
  language: string | undefined,
): SimpleHighlight[] {
  if (language === undefined || hljs.getLanguage(language) === undefined) return [];
  try {
    const result = hljs.highlight(content, { language, ignoreIllegals: true });
    // `emitter` is not in highlight.js' public typings but is the tree the
    // library's own toJson/HTML renderer consumes.
    const root = (result as unknown as { emitter?: { root?: TokenNode } }).emitter?.root;
    if (root === undefined) return [];
    const ranges: SimpleHighlight[] = [];
    let offset = 0;
    const walk = (node: TokenNode, kind: string | undefined): void => {
      if (typeof node === "string") {
        if (kind !== undefined && node.length > 0) {
          ranges.push([offset, offset + node.length, kind]);
        }
        offset += node.length;
        return;
      }
      const inner = node.kind ?? kind;
      for (const child of node.children ?? []) walk(child, inner);
    };
    walk(root, undefined);
    return ranges;
  } catch {
    return [];
  }
}

/**
 * `renderNode` for `<markdown>`: attach our ranges to every fenced code block.
 *
 * Contract notes (measured against @opentui/core 0.5.11):
 *   - `defaultRender()` must be returned verbatim when it is called — the
 *     markdown renderable destroys a default renderable it does not get back,
 *     which would drop the code block entirely.
 *   - a non-empty `filetype` is what makes `CodeRenderable` run its highlight
 *     pass at all (`startHighlight` bails out when filetype is empty), so we
 *     set one even though tree-sitter has no grammar for most languages.
 *   - `onHighlight` is called even for an empty tree-sitter result, and
 *     returning tree-sitter's own list keeps the bundled grammars in charge.
 */
export function codeBlockRenderNode(): NonNullable<MarkdownOptions["renderNode"]> {
  return (token, context) => {
    if (token.type !== "code") return undefined;
    const renderable = context.defaultRender();
    if (renderable === null) return renderable;
    const language = fenceLanguage(token.lang);
    if (language !== undefined) {
      const code = renderable as CodeRenderable;
      code.filetype = language;
      code.onHighlight = (highlights) => {
        const ours = codeHighlightRanges(token.text, language);
        return ours.length > 0 ? ours : highlights;
      };
    }
    return renderable;
  };
}
