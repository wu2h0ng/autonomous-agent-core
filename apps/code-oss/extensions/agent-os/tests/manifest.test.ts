import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

const manifest = JSON.parse(readFileSync(new URL('../package.json', import.meta.url), 'utf8'));

describe('native Surface ownership', () => {
  it('does not contribute extension-owned title bar switching', () => {
    expect(manifest.contributes.menus.titleBar).toBeUndefined();
    expect(JSON.stringify(manifest)).not.toMatch(/openAgentSurface|openIdeSurface/);
  });

  it('does not expose an Agent selector', () => {
    expect(JSON.stringify(manifest)).not.toMatch(/selectAgent|agentPicker|chooseAgent/);
  });
});
