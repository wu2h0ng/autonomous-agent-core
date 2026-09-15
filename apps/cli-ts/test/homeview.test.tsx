/** Home/status polish: single-line, width-bounded, boundary-safe paths. */
import assert from "node:assert/strict";
import { homedir } from "node:os";
import { join } from "node:path";
import React from "react";
import test from "node:test";
import { render } from "ink-testing-library";
import { DEFAULT_THEME_NAME, THEMES } from "../src/theme.js";
import { shortenPath, StatusBar, HomeView } from "../src/HomeView.js";

const theme = THEMES[DEFAULT_THEME_NAME] as NonNullable<
  (typeof THEMES)[string]
>;

test("shortenPath: home-relative, bounded, boundary-safe", () => {
  const home = homedir();
  const under = join(home, "a", "b");
  assert.equal(shortenPath(under, 80), "~/a/b");

  // A sibling whose name merely starts with the home string must not match.
  const sibling = `${home}evil/secret/deep`;
  assert.ok(!shortenPath(sibling, 200).startsWith("~"));

  // Two very long tail segments must still respect the width limit.
  const long = `/${"b".repeat(60)}/${"c".repeat(40)}`;
  assert.ok(shortenPath(long, 20).length <= 20);

  // Non-home short paths pass through unchanged.
  assert.equal(shortenPath("/tmp/demo-workspace", 80), "/tmp/demo-workspace");
});

test("StatusBar renders one compact line when narrow", () => {
  const view = render(
    <StatusBar
      workspace="/x/os-sandbox"
      branch="feature/long-branch-name"
      version="0.1.0"
      theme={theme}
      narrow
    />,
  );
  const frame = view.lastFrame() ?? "";
  assert.match(frame, /noem/);
  assert.match(frame, /os-sandbox/);
  assert.doesNotMatch(frame, /feature\/long-branch-name/);
  assert.equal(frame.trimEnd().split("\n").length, 1);
  view.unmount();
});

test("HomeView wide shows a single bounded path line", () => {
  const view = render(
    <HomeView
      workspace={homedir() + "/proj/deep/workspace"}
      branch={null}
      version="0.1.0"
      provider={null}
      model={null}
      theme={theme}
      columns={100}
    />,
  );
  const frame = view.lastFrame() ?? "";
  assert.match(frame, /path\s+~\/proj\/deep\/workspace/);
  view.unmount();
});
