/**
 * #18 tests: the home/welcome panel content model, plus a drift guard that
 * keeps it from silently diverging from the Ink baseline it is derived from.
 */
import assert from "node:assert/strict";
import { homedir } from "node:os";
import React from "react";
import test from "node:test";
import { render } from "ink-testing-library";
import { HomeView } from "../src/HomeView.js";
import {
  HOME_FIELD_LABELS,
  HOME_TIP_TITLE,
  homeFacts,
  homeFieldRows,
  homePanel,
  providerValue,
  shouldShowHome,
} from "../src/home.js";
import { DEFAULT_THEME_NAME, THEMES } from "../src/theme.js";

const theme = THEMES[DEFAULT_THEME_NAME] as NonNullable<(typeof THEMES)[string]>;

const WORKSPACE = `${homedir()}/proj/deep/workspace`;
const COLUMNS = 100;

const rowsToText = (rows: ReturnType<typeof homeFieldRows>): string[] =>
  rows.map((row) => row.map((segment) => segment.text).join(""));

/** Whitespace-insensitive, so Ink's padding cannot mask a real text change. */
const squash = (value: string): string => value.replace(/\s+/g, " ").trim();

/** Ink's card adds a box border; strip it so lines compare content-to-content. */
const baselineLines = (frame: string): string[] =>
  frame.split("\n").map((line) => squash(line.replace(/[│╭╮╰╯─]/g, "")));

const facts = (over: Partial<Parameters<typeof homeFacts>[0]> = {}) =>
  homeFacts({
    workspace: WORKSPACE,
    branch: "feature/x",
    version: "0.1.0",
    provider: null,
    model: null,
    columns: COLUMNS,
    ...over,
  });

test("shouldShowHome owns only an empty transcript", () => {
  assert.equal(shouldShowHome(0, 0), true);
  assert.equal(shouldShowHome(1, 0), false);
  assert.equal(shouldShowHome(0, 1), false);
  assert.equal(shouldShowHome(3, 2), false);
});

test("provider value mirrors Ink: configured model, else the exact instruction", () => {
  assert.deepEqual(providerValue(facts()), {
    text: "not configured — /provider set <base-url> <model>",
    dim: true,
  });
  assert.deepEqual(providerValue(facts({ model: "deepseek-chat" })), {
    text: "openai-compatible · deepseek-chat",
    dim: false,
  });
  assert.deepEqual(providerValue(facts({ model: "m", provider: "local" })), {
    text: "local · m",
    dim: false,
  });
});

test("wide panel exposes the five fields with bounded, consistent values", () => {
  const model = facts({ model: "m" });
  const rows = homeFieldRows(model);
  assert.equal(rows.length, HOME_FIELD_LABELS.length);
  assert.deepEqual(
    rows.map((row) => row[0]?.text.trim()),
    [...HOME_FIELD_LABELS],
  );
  // every label column is the same width, so the values line up
  assert.equal(new Set(rows.map((row) => row[0]?.text.length)).size, 1);
  assert.equal(rows[0]?.[1]?.text, "workspace");
  assert.equal(rows[1]?.[1]?.text, "~/proj/deep/workspace");
  assert.equal(rows[2]?.[1]?.text, "feature/x");
  assert.equal(rows[4]?.[1]?.text, "0.1.0");
});

test("git falls back when there is no branch, and a long path stays bounded", () => {
  assert.equal(homeFieldRows(facts({ branch: null }))[2]?.[1]?.text, "not a git repository");
  const long = facts({ workspace: `/${"b".repeat(60)}/${"c".repeat(40)}`, columns: 40 });
  assert.ok((long.path.length ?? 0) <= 40);
});

test("narrow panel is the three-line block Ink renders (no card, no tip title)", () => {
  const panel = homePanel(facts(), true);
  assert.deepEqual(rowsToText(panel.fields), ["workspace workspace"]);
  assert.deepEqual(rowsToText(panel.tips), ["/help · @file · !cmd · /provider"]);
  assert.deepEqual(rowsToText([panel.header]), ["NOEM · v0.1.0"]);
  const all = rowsToText([panel.header, ...panel.fields, ...panel.tips]).join("\n");
  assert.doesNotMatch(all, /Quick start/);
});

// --- drift guard ------------------------------------------------------------

test("every wide row except the mode tip matches the Ink HomeView baseline", () => {
  const model = facts({ model: "deepseek-chat" });
  const view = render(
    <HomeView
      workspace={WORKSPACE}
      branch="feature/x"
      version="0.1.0"
      provider={null}
      model="deepseek-chat"
      theme={theme}
      columns={COLUMNS}
    />,
  );
  const baseline = baselineLines(view.lastFrame() ?? "");
  view.unmount();

  const ours = rowsToText([homePanel(model).header, ...homePanel(model).fields]);
  for (const line of ours) {
    assert.ok(
      baseline.includes(squash(line)),
      `home panel line drifted from the Ink baseline: ${JSON.stringify(line)}`,
    );
  }
  assert.ok(baseline.includes(squash(HOME_TIP_TITLE)));
  assert.ok(
    baseline.includes(squash("· /help commands · @file add context · !cmd shell · /provider model")),
  );
});

test("the mode tip is a MEASURED deviation, and it stays truthful", () => {
  // Ink advertises `shift+tab switches mode`; no such binding exists anywhere in
  // this repo (the string occurs exactly once — inside that very tip). The
  // panel ships the instruction that actually works.
  const view = render(
    <HomeView
      workspace={WORKSPACE}
      branch={null}
      version="0.1.0"
      provider={null}
      model={null}
      theme={theme}
      columns={COLUMNS}
    />,
  );
  const baseline = view.lastFrame() ?? "";
  view.unmount();
  assert.match(baseline, /shift\+tab switches mode/, "baseline wording changed — re-measure");

  const tip = rowsToText(homePanel(facts()).tips).find((line) => line.includes("Describe a task"));
  assert.ok(tip, "the panel must still tell the user how to start");
  assert.doesNotMatch(tip, /shift\+tab/);
  assert.match(tip, /\/mode switches permission mode/);
});
