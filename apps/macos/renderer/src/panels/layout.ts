// Layout template engine (Wave 2b): a layout is a closed, validated data
// structure; templates are renderer-local (no durable layout store in 2b).

export const ALL_PANEL_IDS = [
  "agent-thread",
  "plan-tasks",
  "files",
  "diff",
  "terminal",
  "chrome-live",
  "embedded-web",
  "gmail",
  "calendar",
  "evidence-approval",
] as const;

export type PanelId = (typeof ALL_PANEL_IDS)[number];

export interface PanelPlacement {
  panel_id: string;
  x: number;
  y: number;
  w: number;
  h: number;
  focused: boolean;
}

export interface LayoutTemplate {
  id: string;
  name: string;
  panels: PanelPlacement[];
}

function overlaps(a: PanelPlacement, b: PanelPlacement): boolean {
  return (
    a.x < b.x + b.w &&
    b.x < a.x + a.w &&
    a.y < b.y + b.h &&
    b.y < a.y + a.h
  );
}

/** Returns an error message, or null when the template is valid. */
export function validateTemplate(template: LayoutTemplate): string | null {
  if (!template.id.trim() || !template.name.trim()) {
    return "layout id and name must be non-empty";
  }
  if (template.panels.length === 0) {
    return "layout must contain at least one panel";
  }
  let focusedCount = 0;
  const seen = new Set<string>();
  for (const placement of template.panels) {
    if (!ALL_PANEL_IDS.includes(placement.panel_id as PanelId)) {
      return `unknown panel id: ${placement.panel_id}`;
    }
    if (seen.has(placement.panel_id)) {
      return `duplicate panel id: ${placement.panel_id}`;
    }
    seen.add(placement.panel_id);
    if (placement.w <= 0 || placement.h <= 0) {
      return `panel ${placement.panel_id} has a non-positive size`;
    }
    if (placement.focused) {
      focusedCount += 1;
    }
  }
  if (focusedCount > 1) {
    return "at most one panel may be focused";
  }
  for (let i = 0; i < template.panels.length; i += 1) {
    for (let j = i + 1; j < template.panels.length; j += 1) {
      if (overlaps(template.panels[i], template.panels[j])) {
        return `panels overlap: ${template.panels[i].panel_id} / ${template.panels[j].panel_id}`;
      }
    }
  }
  return null;
}

export const FOCUS_TEMPLATE: LayoutTemplate = {
  id: "layout:focus",
  name: "Focus",
  panels: [
    { panel_id: "agent-thread", x: 0, y: 0, w: 900, h: 640, focused: true },
    { panel_id: "evidence-approval", x: 920, y: 0, w: 500, h: 320, focused: false },
    { panel_id: "diff", x: 920, y: 340, w: 500, h: 300, focused: false },
  ],
};

export const DEFAULT_TEMPLATE: LayoutTemplate = {
  id: "layout:default",
  name: "Default",
  panels: [
    { panel_id: "agent-thread", x: 0, y: 0, w: 700, h: 700, focused: true },
    { panel_id: "evidence-approval", x: 720, y: 0, w: 480, h: 340, focused: false },
    { panel_id: "files", x: 720, y: 360, w: 480, h: 340, focused: false },
    { panel_id: "plan-tasks", x: 0, y: 720, w: 380, h: 280, focused: false },
    { panel_id: "diff", x: 400, y: 720, w: 380, h: 280, focused: false },
    { panel_id: "terminal", x: 800, y: 720, w: 400, h: 280, focused: false },
    { panel_id: "chrome-live", x: 0, y: 1020, w: 300, h: 180, focused: false },
    { panel_id: "embedded-web", x: 320, y: 1020, w: 300, h: 180, focused: false },
    { panel_id: "gmail", x: 640, y: 1020, w: 280, h: 180, focused: false },
    { panel_id: "calendar", x: 940, y: 1020, w: 260, h: 180, focused: false },
  ],
};
