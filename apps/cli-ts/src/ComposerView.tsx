/**
 * Multi-line composer renderer. Pure presentation: App owns all key
 * routing (see App.tsx), so this component never touches stdin and cannot
 * double-handle a key with the global handler.
 */
import React from "react";
import { Box, Text } from "ink";
import { cursorLineCol, type ComposerState } from "./composer.js";
import type { ThemeColors } from "./theme.js";

function cursorGlyph(line: string, column: number): string {
  const codePoint = line.codePointAt(column);
  return codePoint === undefined ? " " : String.fromCodePoint(codePoint);
}

export function Composer({
  state,
  placeholder,
  theme,
  modeLabel,
}: {
  state: ComposerState;
  placeholder?: string;
  theme: ThemeColors;
  modeLabel?: string | undefined;
}) {
  const label = modeLabel ? <Text color={theme.notice}>{modeLabel} </Text> : null;
  if (state.value.length === 0) {
    return (
      <Text>
        {label}
        <Text color={theme.toolDone}>{"› "}</Text>
        <Text inverse> </Text>
        {placeholder ? <Text dimColor>{` ${placeholder}`}</Text> : null}
      </Text>
    );
  }
  const lines = state.value.split("\n");
  const { line: cursorLine, column } = cursorLineCol(state);
  return (
    <Box flexDirection="column">
      {lines.map((line, index) => {
        const prefix = index === 0 ? "› " : "  ";
        const lead = index === 0 ? label : null;
        if (index !== cursorLine) {
          return (
            <Text key={index}>
              {lead}
              {prefix}
              {line.length > 0 ? line : " "}
            </Text>
          );
        }
        const before = line.slice(0, column);
        const glyph = cursorGlyph(line, column);
        const after = line.slice(column + glyph.length);
        return (
          <Text key={index}>
            {lead}
            {prefix}
            {before}
            <Text inverse>{glyph}</Text>
            {after}
          </Text>
        );
      })}
    </Box>
  );
}
