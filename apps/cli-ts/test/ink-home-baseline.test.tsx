/**
 * Re-measures the LIVE Ink `HomeView` against the frozen baseline snapshot.
 *
 * This file exists so the snapshot in `test/fixtures/ink-home-baseline.ts`
 * cannot rot while Ink is still around: if Ink's wording or layout changes, this
 * fails and forces a conscious snapshot update instead of silently widening the
 * gap between the two views.
 *
 * DELETE THIS FILE TOGETHER WITH INK. Nothing else imports it, and the snapshot
 * it validates keeps working without it — that separation is the whole point.
 */
import assert from "node:assert/strict";
import test from "node:test";
import React from "react";
import { render } from "ink-testing-library";
import { HomeView } from "../src/HomeView.js";
import { DEFAULT_THEME_NAME, THEMES } from "../src/theme.js";
import {
  BASELINE_INPUTS,
  BASELINE_INPUTS_UNCONFIGURED,
  INK_HOME_BASELINE,
  INK_HOME_BASELINE_UNCONFIGURED,
  INK_MODE_TIP,
  inkFrameLines,
} from "./fixtures/ink-home-baseline.js";

const theme = THEMES[DEFAULT_THEME_NAME] as NonNullable<(typeof THEMES)[string]>;

test("the frozen Ink HomeView snapshot still matches the live Ink render", () => {
  const view = render(
    <HomeView
      workspace={BASELINE_INPUTS.workspace}
      branch={BASELINE_INPUTS.branch}
      version={BASELINE_INPUTS.version}
      provider={null}
      model="deepseek-chat"
      theme={theme}
      columns={BASELINE_INPUTS.columns}
    />,
  );
  const lines = inkFrameLines(view.lastFrame() ?? "");
  view.unmount();
  assert.deepEqual(
    lines,
    [...INK_HOME_BASELINE],
    "Ink HomeView drifted — re-measure and update test/fixtures/ink-home-baseline.ts",
  );
});

test("the frozen unconfigured-provider snapshot still matches the live render", () => {
  const view = render(
    <HomeView
      workspace={BASELINE_INPUTS_UNCONFIGURED.workspace}
      branch={BASELINE_INPUTS_UNCONFIGURED.branch}
      version={BASELINE_INPUTS_UNCONFIGURED.version}
      provider={null}
      model={null}
      theme={theme}
      columns={BASELINE_INPUTS_UNCONFIGURED.columns}
    />,
  );
  const lines = inkFrameLines(view.lastFrame() ?? "");
  view.unmount();
  assert.deepEqual(lines, [...INK_HOME_BASELINE_UNCONFIGURED]);
  // The recorded deviation, re-measured rather than assumed: while Ink exists it
  // must still be the view advertising a keybinding the repo does not implement.
  assert.ok(lines.includes(INK_MODE_TIP));
});
