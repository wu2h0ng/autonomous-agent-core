/**
 * Interactive list-selector model for mainstream pickers (`/resume`,
 * `/theme`, `/mode`). Pure: the controller supplies items, App routes keys
 * and renders. No kernel/session state here.
 */
export interface SelectorState {
  items: readonly string[];
  index: number;
}

export function moveSelector(state: SelectorState, delta: number): SelectorState {
  const count = state.items.length;
  if (count === 0) return { ...state, index: 0 };
  return { ...state, index: (state.index + delta + count) % count };
}

export function selectorChoice(state: SelectorState): string | undefined {
  return state.items[state.index];
}

/** 1-based numeric choice (mainstream radio lists let you press 1..9). */
export function numberedChoice(state: SelectorState, digit: number): string | undefined {
  return state.items[digit - 1];
}

/** Case-insensitive substring filter for pickers (typing narrows the list). */
export function filterSelectorItems(items: readonly string[], query: string): string[] {
  const needle = query.trim().toLowerCase();
  if (!needle) return [...items];
  return items.filter((item) => item.toLowerCase().includes(needle));
}
