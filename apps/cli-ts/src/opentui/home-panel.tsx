/**
 * #18: the full-screen home / welcome panel.
 *
 * Ink greets the user with `src/HomeView.tsx` before the first turn; the
 * full-screen view rendered an empty transcript instead. The CONTENT lives in
 * `src/home.ts` (shared, renderer-neutral) — this module only paints it.
 *
 * Row note: opentui `<text>` siblings inside a flex column do not reserve a row
 * on their own here, so every row carries an explicit `height: 1` (learned from
 * the chrome fix in the same slice, where the status line and footer collapsed
 * onto their neighbours).
 */
/** @jsxImportSource @opentui/react */
import { createTextAttributes } from "@opentui/core";
import { homeFacts, homePanel, type HomeInput, type HomeRow } from "../home.js";
import type { ThemeColors } from "../theme.js";

export type { HomeInput };

function Row({ segments, theme }: { segments: HomeRow; theme: ThemeColors }) {
  return (
    <text style={{ height: 1 }}>
      {segments.map((segment, index) => (
        <span
          key={index}
          fg={theme[segment.token]}
          attributes={createTextAttributes({
            bold: segment.bold ?? false,
            dim: segment.dim ?? false,
          })}
        >
          {segment.text}
        </span>
      ))}
    </text>
  );
}

export function HomePanel({
  input,
  theme,
  narrow = false,
}: {
  input: HomeInput;
  theme: ThemeColors;
  narrow?: boolean;
}) {
  const panel = homePanel(homeFacts(input), narrow);
  // Ink's narrow variant is a plain three-line block (no card, no heading
  // title) with one trailing blank line — reproduced exactly.
  if (narrow) {
    return (
      <box style={{ flexDirection: "column" }}>
        <Row segments={panel.header} theme={theme} />
        {panel.fields.map((row, index) => (
          <Row key={`field${index}`} segments={row} theme={theme} />
        ))}
        {panel.tips.map((row, index) => (
          <Row key={`tip${index}`} segments={row} theme={theme} />
        ))}
        <text style={{ height: 1 }}> </text>
      </box>
    );
  }
  return (
    <box style={{ flexDirection: "column" }}>
      <box
        borderStyle="rounded"
        border
        borderColor={theme.accent}
        style={{ flexDirection: "column", paddingLeft: 1 }}
      >
        <Row segments={panel.header} theme={theme} />
        <text style={{ height: 1 }}> </text>
        {panel.fields.map((row, index) => (
          <Row key={`field${index}`} segments={row} theme={theme} />
        ))}
      </box>
      <text style={{ height: 1 }}> </text>
      {panel.tips.map((row, index) => (
        <Row key={`tip${index}`} segments={row} theme={theme} />
      ))}
      <text style={{ height: 1 }}> </text>
    </box>
  );
}
