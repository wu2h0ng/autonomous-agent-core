/**
 * Home screen + always-on header. Mainstream terminals greet the user with a
 * branded landing panel (workspace, git, provider) and quick-start tips before
 * the first turn; this keeps the first-run experience from being a blank log.
 */
import React from "react";
import { basename } from "node:path";
import { Box, Text } from "ink";
import type { ThemeColors } from "./theme.js";

export interface HeaderProps {
  workspace: string;
  branch: string | null;
  mode: string;
  version: string;
  theme: ThemeColors;
}

export function Header({ workspace, branch, mode, version, theme }: HeaderProps) {
  const name = basename(workspace) || workspace;
  return (
    <Box justifyContent="space-between" marginBottom={1}>
      <Text>
        <Text bold color={theme.accent}>
          ◆ agent-os
        </Text>
        <Text dimColor> v{version}</Text>
      </Text>
      <Text dimColor wrap="truncate-end">
        {name}
        {branch ? ` · ${branch}` : ""} · {mode}
      </Text>
    </Box>
  );
}

export interface HomeViewProps {
  workspace: string;
  branch: string | null;
  version: string;
  provider: string | null;
  model: string | null;
  theme: ThemeColors;
  narrow?: boolean;
}

export function HomeView({
  workspace,
  branch,
  version,
  provider,
  model,
  theme,
  narrow = false,
}: HomeViewProps) {
  const name = basename(workspace) || workspace;
  if (narrow) {
    return (
      <Box flexDirection="column" marginBottom={1}>
        <Text>
          <Text bold color={theme.accent}>
            AGENT OS
          </Text>
          <Text dimColor> · v{version}</Text>
        </Text>
        <Text dimColor>workspace {name}</Text>
        <Text dimColor>/help · @file · !cmd · /provider</Text>
      </Box>
    );
  }
  return (
    <Box flexDirection="column" marginBottom={1}>
      <Box
        flexDirection="column"
        borderStyle="round"
        borderColor={theme.accent}
        paddingX={2}
        paddingY={1}
      >
        <Text>
          <Text bold color={theme.accent}>
            AGENT OS
          </Text>
          <Text dimColor> · governed terminal agent</Text>
        </Text>
        <Box marginTop={1} flexDirection="column">
          <Text>
            <Text color={theme.accent}>workspace  </Text>
            {name}
          </Text>
          <Text>
            <Text color={theme.accent}>path       </Text>
            <Text dimColor>{workspace}</Text>
          </Text>
          <Text>
            <Text color={theme.accent}>git        </Text>
            <Text dimColor>{branch ?? "not a git repository"}</Text>
          </Text>
          <Text>
            <Text color={theme.accent}>provider   </Text>
            {model ? (
              <Text>{`${provider ?? "openai-compatible"} · ${model}`}</Text>
            ) : (
              <Text dimColor>not configured — /provider set &lt;base-url&gt; &lt;model&gt;</Text>
            )}
          </Text>
          <Text>
            <Text color={theme.accent}>version    </Text>
            <Text dimColor>{version}</Text>
          </Text>
        </Box>
      </Box>
      <Box flexDirection="column" marginTop={1}>
        <Text bold color={theme.notice}>
          Quick start
        </Text>
        <Text dimColor>· Describe a task and press Enter (shift+tab switches mode)</Text>
        <Text dimColor>· /help commands · @file add context · !cmd shell · /provider model</Text>
      </Box>
    </Box>
  );
}
