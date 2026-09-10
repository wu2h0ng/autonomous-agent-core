import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { stripTypeScriptTypes } from 'node:module';
import { test } from 'node:test';
import { runInNewContext } from 'node:vm';
import path from 'node:path';
import { upstreamRoot } from '../scripts/paths.mjs';

const source = relative => readFile(path.join(upstreamRoot, relative), 'utf8');

async function navigation() {
  const text = await source('src/vs/agentos/electron-browser/windowNavigation.ts');
  return import(`data:text/javascript;base64,${Buffer.from(stripTypeScriptTypes(text)).toString('base64')}`);
}

test('Agent Window uses the upstream native window kind and renderer', async () => {
  const [configuration, bootstrap, main] = await Promise.all([
    source('src/vs/platform/window/common/window.ts'),
    source('src/vs/sessions/electron-browser/sessions.ts'),
    source('src/vs/platform/windows/electron-main/windowsMainService.ts'),
  ]);
  assert.match(configuration, /isSessionsWindow\?: boolean/);
  assert.doesNotMatch(configuration, /agentOSWindow\?: boolean/);
  assert.match(bootstrap, /vs\/sessions\/sessions\.desktop\.main\.js/);
  assert.match(main, /isSessionsWindow: isWorkspaceIdentifier\(options.workspace\)/);
});

test('Agent OS destination commands are loaded by both native renderers', async () => {
  const [actions, desktop, sessions, ide, nativeHost, contract] = await Promise.all([
    source('src/vs/agentos/electron-browser/windowActions.ts'),
    source('src/vs/workbench/electron-browser/desktop.contribution.ts'),
    source('src/vs/sessions/sessions.desktop.main.ts'),
    source('src/vs/workbench/workbench.desktop.main.ts'),
    source('src/vs/platform/native/electron-main/nativeHostMainService.ts'),
    source('src/vs/platform/window/common/window.ts'),
  ]);
  assert.match(desktop, /import '\.\.\/\.\.\/agentos\/electron-browser\/windowActions\.js'/);
  assert.match(sessions, /workbench\/electron-browser\/desktop\.contribution\.js/);
  assert.match(ide, /electron-browser\/desktop\.contribution\.js/);
  assert.match(actions, /id: 'agentOS\.openSessionsWindow'/);
  assert.match(actions, /id: 'agentOS\.focusOrOpenIDEWindow'/);
  assert.match(actions, /INativeHostService/);
  assert.match(actions, /MenuId\.TitleBarAdjacentCenter/);
  assert.match(actions, /Menus\.TitleBarCenterRight/);
  assert.match(actions, /IsSessionsWindowContext/);
  assert.match(nativeHost, /isSessionsWindow: window\.config\?\.isSessionsWindow === true/);
  assert.match(contract, /interface IOpenedMainWindow[^}]*readonly isSessionsWindow\?: boolean/s);
});

test('opening Agent Window delegates to the native Sessions service', async () => {
  const { openSessionsWindow } = await navigation();
  const calls = [];
  await openSessionsWindow({ openAgentsWindow: async () => calls.push('sessions') });
  assert.deepEqual(calls, ['sessions']);
});

test('registered command handlers invoke the native navigation through ServicesAccessor', async () => {
  const handlers = new Map();
  const serviceId = Symbol('INativeHostService');
  const contextKey = { toNegated: () => false };
  const text = await source('src/vs/agentos/electron-browser/windowActions.ts');
  // Only external registration/context dependencies are doubled; execute the real
  // action classes and navigation functions through their native service boundary.
  runInNewContext(stripTypeScriptTypes(text).replace(/^import .*;\s*$/gm, ''), {
    ...(await navigation()),
    INativeHostService: serviceId,
    Action2: class { constructor(options) { this.options = options; } },
    registerAction2: Action => { const action = new Action(); handlers.set(action.options.id, action); },
    localize2: (_key, value) => value,
    Codicon: { commentDiscussion: {}, code: {} },
    IsWebContext: contextKey,
    IsAuxiliaryWindowContext: contextKey,
    IsSessionsWindowContext: contextKey,
    ContextKeyExpr: { and: (...values) => values },
    MenuId: { TitleBarAdjacentCenter: 'TitleBarAdjacentCenter' },
    Menus: { TitleBarCenterRight: 'SessionsTitleBarCenterRight' },
  });
  const calls = [];
  const native = {
    openAgentsWindow: async () => calls.push('sessions'),
    getWindows: async () => [{ id: 7, isSessionsWindow: false }],
    focusWindow: async options => calls.push(['focus', options.targetWindowId]),
  };
  const accessor = { get: id => { assert.equal(id, serviceId); return native; } };
  await handlers.get('agentOS.openSessionsWindow').run(accessor);
  await handlers.get('agentOS.focusOrOpenIDEWindow').run(accessor);
  assert.deepEqual(calls, ['sessions', ['focus', 7]]);
});

test('return to IDE skips Sessions and unknown kinds, and focuses a real IDE', async () => {
  const { focusOrOpenIDEWindow } = await navigation();
  const calls = [];
  await focusOrOpenIDEWindow({
    getWindows: async options => {
      assert.deepEqual(options, { includeAuxiliaryWindows: false });
      return [{ id: 1, isSessionsWindow: true }, { id: 2 }, { id: 3, isSessionsWindow: false }];
    },
    focusWindow: async options => calls.push(['focus', options]),
    openWindow: async () => assert.fail('must focus existing IDE'),
  });
  assert.deepEqual(calls, [['focus', { targetWindowId: 3 }]]);
});

test('return to IDE opens an empty native IDE when no IDE exists', async () => {
  const { focusOrOpenIDEWindow } = await navigation();
  for (const windows of [[], [{ id: 1, isSessionsWindow: true }], [{ id: 2 }]]) {
    const calls = [];
    await focusOrOpenIDEWindow({
      getWindows: async () => windows,
      focusWindow: async () => assert.fail('must not focus Sessions or an unknown kind'),
      openWindow: async (...args) => calls.push(args),
    });
    assert.deepEqual(calls, [[]]);
  }
});

test('native navigation failures propagate without a fallback side effect', async () => {
  const { openSessionsWindow, focusOrOpenIDEWindow } = await navigation();
  const failure = new Error('native window unavailable');
  await assert.rejects(openSessionsWindow({ openAgentsWindow: async () => { throw failure; } }), failure);
  await assert.rejects(focusOrOpenIDEWindow({
    getWindows: async () => { throw failure; },
    openWindow: async () => assert.fail('failed enumeration must not open a window'),
  }), failure);
  await assert.rejects(focusOrOpenIDEWindow({
    getWindows: async () => [{ id: 3, isSessionsWindow: false }],
    focusWindow: async () => { throw failure; },
    openWindow: async () => assert.fail('failed focus must not open a window'),
  }), failure);
});
