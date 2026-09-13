import { describe, expect, it } from "vitest";
import {
  ALL_PANEL_IDS,
  DEFAULT_TEMPLATE,
  validateTemplate,
  type LayoutTemplate,
} from "../src/panels/layout";

describe("layout template engine", () => {
  it("accepts a valid template with exactly known panel ids", () => {
    const template: LayoutTemplate = {
      id: "layout:focus",
      name: "Focus",
      panels: [
        { panel_id: "agent-thread", x: 0, y: 0, w: 800, h: 600, focused: true },
        { panel_id: "evidence-approval", x: 820, y: 0, w: 400, h: 300, focused: false },
      ],
    };
    expect(validateTemplate(template)).toBeNull();
  });

  it("rejects unknown panel ids", () => {
    const template: LayoutTemplate = {
      id: "layout:bad",
      name: "Bad",
      panels: [
        { panel_id: "not-a-panel", x: 0, y: 0, w: 100, h: 100, focused: false },
      ],
    };
    expect(validateTemplate(template)).toContain("unknown panel");
  });

  it("rejects non-positive or negative sizes", () => {
    const template: LayoutTemplate = {
      id: "layout:neg",
      name: "Neg",
      panels: [
        { panel_id: "agent-thread", x: 0, y: 0, w: -1, h: 100, focused: false },
      ],
    };
    expect(validateTemplate(template)).toContain("size");
  });

  it("rejects overlapping placements", () => {
    const template: LayoutTemplate = {
      id: "layout:overlap",
      name: "Overlap",
      panels: [
        { panel_id: "agent-thread", x: 0, y: 0, w: 500, h: 500, focused: false },
        { panel_id: "files", x: 250, y: 250, w: 500, h: 500, focused: false },
      ],
    };
    expect(validateTemplate(template)).toContain("overlap");
  });

  it("enforces at most one focused panel", () => {
    const template: LayoutTemplate = {
      id: "layout:twofocused",
      name: "Two",
      panels: [
        { panel_id: "agent-thread", x: 0, y: 0, w: 100, h: 100, focused: true },
        { panel_id: "files", x: 200, y: 0, w: 100, h: 100, focused: true },
      ],
    };
    expect(validateTemplate(template)).toContain("focused");
  });

  it("exposes the default template covering the ten closed panel ids", () => {
    expect(validateTemplate(DEFAULT_TEMPLATE)).toBeNull();
    const ids = new Set(DEFAULT_TEMPLATE.panels.map((p) => p.panel_id));
    expect(ids.size).toBe(ALL_PANEL_IDS.length);
    for (const panelId of ALL_PANEL_IDS) {
      expect(ids.has(panelId)).toBe(true);
    }
  });
});
