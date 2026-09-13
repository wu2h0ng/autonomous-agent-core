/**
 * Command registry tests (single source of truth for slash commands).
 * The palette and /help must never drift apart; filtering is prefix-first.
 */
import assert from "node:assert/strict";
import test from "node:test";
import { COMMANDS, filterCommands, helpLines } from "../src/commands.js";

test("registry: every command is unique and well-formed", () => {
  const names = COMMANDS.map((c) => c.name);
  assert.equal(new Set(names).size, names.length);
  for (const command of COMMANDS) {
    assert.match(command.name, /^\/[a-z]+$/);
    assert.ok(command.description.length > 0);
  }
});

test("filter: empty and bare slash show everything", () => {
  assert.equal(filterCommands("").length, COMMANDS.length);
  assert.equal(filterCommands("/").length, COMMANDS.length);
});

test("filter: prefix match on the command name, case-insensitive", () => {
  const names = filterCommands("/st").map((c) => c.name);
  assert.ok(names.includes("/status"));
  assert.ok(!names.includes("/cost"));
  assert.deepEqual(
    filterCommands("/MO").map((c) => c.name),
    ["/mode"],
  );
});

test("filter: falls back to description match when no name matches", () => {
  const names = filterCommands("/pricing").map((c) => c.name);
  assert.deepEqual(names, ["/cost"]); // "no pricing source" in the description
});

test("filter: command with args closes the palette (space ends the query)", () => {
  // a query containing a space is no longer a palette query
  assert.deepEqual(filterCommands("/mode ASK"), []);
});

test("helpLines: derived from the same registry (no drift)", () => {
  const lines = helpLines();
  assert.equal(lines.length, COMMANDS.length);
  for (const command of COMMANDS) {
    assert.ok(lines.some((line) => line.startsWith(command.name)));
  }
});
