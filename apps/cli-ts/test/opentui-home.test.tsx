/**
 * #18 tests: the home/welcome panel content model, plus a drift guard that
 * keeps it from silently diverging from the Ink baseline it is derived from.
 *
 * The baseline is a FROZEN snapshot (test/fixtures/ink-home-baseline.ts), not a
 * live Ink render: this file must keep working after Ink is deleted. The live
 * re-measurement lives in test/ink-home-baseline.test.tsx, which is deleted
 * together with Ink.
 */
import assert from "node:assert/strict";
import { homedir } from "node:os";
import test from "node:test";
import {
  HOME_FIELD_LABELS,
  HOME_TIP_TITLE,
  homeFacts,
  homeFieldRows,
  homePanel,
  providerValue,
  shouldShowHome,
} from "../src/home.js";
import {
  INK_HOME_BASELINE,
  INK_HOME_BASELINE_PROVIDER_SET,
  INK_MODE_TIP,
  squash,
} from "./fixtures/ink-home-baseline.js";

const WORKSPACE = `${homedir()}/proj/deep/workspace`;
const COLUMNS = 100;

const rowsToText = (rows: ReturnType<typeof homeFieldRows>): string[] =>
  rows.map((row) => row.map((segment) => segment.text).join(""));

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

// --- drift guard (against the FROZEN baseline; no Ink import) ----------------

test("every wide row matches the frozen Ink HomeView baseline", () => {
  const model = facts({ model: "deepseek-chat" });
  const panel = homePanel(model);
  for (const line of rowsToText([panel.header, ...panel.fields])) {
    assert.ok(
      INK_HOME_BASELINE.includes(squash(line)),
      `home panel line drifted from the Ink baseline: ${JSON.stringify(line)}`,
    );
  }
  assert.ok(INK_HOME_BASELINE.includes(squash(HOME_TIP_TITLE)));
  assert.ok(
    INK_HOME_BASELINE.includes(
      squash("· /help commands · @file add context · !cmd shell · /provider model"),
    ),
  );
});

test("the baseline snapshot is complete enough to catch a dropped row", () => {
  // Bypass-detecting: the guard above is an "is each of ours in the baseline"
  // check, so a baseline that had been emptied would pass vacuously.
  assert.ok(INK_HOME_BASELINE.length >= 9, "the snapshot lost rows");
  for (const label of HOME_FIELD_LABELS) {
    assert.ok(
      INK_HOME_BASELINE.some((line) => line.startsWith(`${label} `)),
      `the baseline is missing the ${label} row`,
    );
  }
});

test("the unconfigured-provider row also matches the frozen baseline", () => {
  // The other recorded variant: no branch, no model. Rows carry the padded
  // label column, so compare squashed on both sides.
  const rows = rowsToText(homeFieldRows(facts({ branch: null, model: null }))).map(squash);
  assert.ok(rows.includes(squash("git not a git repository")));
  assert.ok(rows.includes(squash("provider not configured — /provider set <base-url> <model>")));
});

test("a REAL provider id reaches the row, not the fallback string", () => {
  // Closes the blind spot that let a regression through: the fallback text
  // ("openai-compatible") is ALSO a legitimate provider id, so a fixture that
  // only ever passes `provider: null` cannot distinguish "the id was forwarded"
  // from "the id was dropped". Both variants are asserted, so dropping either
  // one fails.
  const real = rowsToText(
    homeFieldRows(facts({ provider: "anthropic", model: "claude-sonnet" })),
  ).map(squash);
  const row = real.find((line) => line.startsWith("provider "));
  assert.equal(row, squash("provider anthropic · claude-sonnet"));
  assert.ok(
    INK_HOME_BASELINE_PROVIDER_SET.includes(squash("provider anthropic · claude-sonnet")),
    "the frozen Ink baseline must record the real provider id for this case",
  );
  assert.ok(!real.some((line) => line.includes("openai-compatible")));

  // ...and the null case still yields the fallback, so the two are separable.
  const fallback = rowsToText(homeFieldRows(facts({ model: "claude-sonnet" }))).map(squash);
  assert.ok(fallback.some((line) => line === squash("provider openai-compatible · claude-sonnet")));
});

test("the mode tip is a MEASURED deviation, and it stays truthful", () => {
  // Ink advertises `shift+tab switches mode`; no such binding exists anywhere
  // in this repo (the string occurs exactly once — inside that very tip). The
  // panel ships the instruction that actually works. The baseline side of this
  // fact is re-measured against live Ink by test/ink-home-baseline.test.tsx.
  assert.ok(INK_HOME_BASELINE.includes(INK_MODE_TIP), "the recorded Ink tip changed");

  const tip = rowsToText(homePanel(facts()).tips).find((line) => line.includes("Describe a task"));
  assert.ok(tip, "the panel must still tell the user how to start");
  assert.doesNotMatch(tip, /shift\+tab/);
  assert.match(tip, /\/mode switches permission mode/);
});
