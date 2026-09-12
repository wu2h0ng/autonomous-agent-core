/**
 * Theme registry tests.
 */
import assert from "node:assert/strict";
import test from "node:test";
import {
  DEFAULT_THEME_NAME,
  nextTheme,
  resolveTheme,
  THEMES,
  themeNames,
} from "../src/theme.js";

test("every theme defines every token (no accidental inheritance)", () => {
  const keys = Object.keys(THEMES[DEFAULT_THEME_NAME] as object);
  for (const name of themeNames()) {
    assert.deepEqual(Object.keys(THEMES[name] as object).sort(), [...keys].sort(), name);
  }
});

test("resolveTheme falls back to default for unknown/empty names", () => {
  assert.equal(resolveTheme("nope"), THEMES[DEFAULT_THEME_NAME]);
  assert.equal(resolveTheme(null), THEMES[DEFAULT_THEME_NAME]);
  assert.equal(resolveTheme("ansi"), THEMES["ansi"]);
});

test("nextTheme cycles deterministically", () => {
  const names = themeNames();
  assert.equal(nextTheme("default"), names[1]);
  assert.equal(nextTheme(names[1] as string), names[2]);
  assert.equal(nextTheme(names[names.length - 1] as string), names[0]);
  assert.equal(nextTheme("unknown"), names[0]); // unknown -> first theme
});
