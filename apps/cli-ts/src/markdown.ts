/**
 * Markdown → ANSI rendering for finalized assistant messages.
 *
 * Deps: marked + marked-terminal (the de-facto mainstream CLI markdown
 * stack, MIT). In-flight streaming text renders raw; markdown applies only
 * once a message is finalized, so partial constructs (unclosed fences)
 * never flicker through the renderer.
 */
import { marked } from "marked";
import { markedTerminal } from "marked-terminal";

let configured = false;

function ensureConfigured(): void {
  if (configured) return;
  marked.use(
    markedTerminal({
      reflowText: false,
      showSectionPrefix: false,
      tab: 2,
    }) as never,
  );
  configured = true;
}

export function renderMarkdown(text: string): string {
  ensureConfigured();
  const rendered = marked.parse(text, { async: false }) as string;
  return rendered.replace(/\n+$/, "");
}
