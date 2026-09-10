import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { mkdtemp, readFile, readdir, rm, stat } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { test } from 'node:test';
import { overlayRoot, upstreamRoot } from '../scripts/paths.mjs';

const source = relative => readFile(path.join(upstreamRoot, relative), 'utf8');
const git = args => execFileSync('git', args, { cwd: upstreamRoot, encoding: 'utf8' });

test('Agent Window retains upstream native Parts and layout, not a fake EditorPane', async () => {
  const [workbench, sessionsPart, desktop] = await Promise.all([
    source('src/vs/sessions/browser/workbench.ts'),
    source('src/vs/sessions/browser/parts/sessionsPart.ts'),
    source('src/vs/sessions/sessions.desktop.main.ts'),
  ]);
  // 1.136.2 owns a Workbench implementation rather than subclassing the IDE Workbench.
  assert.match(workbench, /export class Workbench extends Disposable/);
  assert.match(workbench, /SerializableGrid\.deserialize/);
  assert.match(workbench, /new SessionsLayoutPolicy\(/);
  assert.match(sessionsPart, /export class SessionsPart extends Part/);
  assert.match(desktop, /sessions\.layout\.contribution\.js/);
  assert.doesNotMatch(workbench, /agentOSWindowEditor|createWebviewPanel|extends EditorPane/);
});

test('Task 2 leaves every Sessions byte and path identical to the pinned upstream', async () => {
  const lock = JSON.parse(await readFile(path.join(overlayRoot, 'upstream.lock.json'), 'utf8'));
  assert.equal(git(['rev-parse', 'HEAD']).trim(), lock.commit);
  assert.equal(git(['diff', lock.commit, '--', 'src/vs/sessions']), '');
  assert.equal(git(['ls-files', '--others', '--exclude-standard', '--', 'src/vs/sessions']), '');
});

test('active patch cannot restore the retired fake Agent surface', async () => {
  await assert.rejects(stat(path.join(upstreamRoot, 'src/vs/workbench/agentOSWindow/browser/agentOSWindowEditor.ts')), { code: 'ENOENT' });
  const agentosRoot = path.join(upstreamRoot, 'src/vs/agentos');
  for (const name of await readdir(agentosRoot, { recursive: true })) {
    if (!name.endsWith('.ts')) continue;
    const implementation = await readFile(path.join(agentosRoot, name), 'utf8');
    assert.doesNotMatch(implementation, /AgentOSTaskListPart extends Disposable|extends EditorPane|createWebviewPanel/);
  }
  for (const name of await readdir(path.join(overlayRoot, 'patches'))) {
    if (!name.endsWith('.patch')) continue;
    const patch = await readFile(path.join(overlayRoot, 'patches', name), 'utf8');
    assert.doesNotMatch(patch, /AgentOSTaskListPart extends Disposable|agentOSWindowEditor|createWebviewPanel|agentOSWindow\?: boolean/);
    assert.doesNotMatch(patch, /^diff --git a\/src\/vs\/sessions\//m);
  }
});

test('Task 2 patch replays from an exact clean upstream HEAD without Sessions changes', async () => {
  const checkout = await mkdtemp(path.join(os.tmpdir(), 'agent-os-sessions-replay-'));
  const patch = path.join(overlayRoot, 'patches/010-agent-os-sessions-window.patch');
  const lock = JSON.parse(await readFile(path.join(overlayRoot, 'upstream.lock.json'), 'utf8'));
  const run = args => execFileSync('git', args, { cwd: checkout, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] });
  try {
    run(['clone', '--quiet', '--local', '--shared', '--no-checkout', upstreamRoot, '.']);
    run(['-c', 'filter.lfs.process=', '-c', 'filter.lfs.required=false', 'checkout', '--quiet', '--detach', lock.commit]);
    assert.equal(run(['rev-parse', 'HEAD']).trim(), lock.commit);
    assert.equal(run(['status', '--porcelain']), '');
    run(['apply', '--check', '--whitespace=error-all', patch]);
    run(['apply', patch]);
    run(['apply', '--reverse', '--check', patch]);
    run(['diff', '--check']);
    assert.equal(run(['diff', lock.commit, '--', 'src/vs/sessions']), '');
    assert.equal(run(['ls-files', '--others', '--', 'src/vs/sessions']), '');
    const modified = run(['diff', '--name-only']).trim().split('\n');
    const added = run(['ls-files', '--others', '--exclude-standard']).trim().split('\n');
    assert.deepEqual([...modified, ...added].sort(), [
      'src/vs/agentos/electron-browser/windowActions.ts',
      'src/vs/agentos/electron-browser/windowNavigation.ts',
      'src/vs/platform/native/electron-main/nativeHostMainService.ts',
      'src/vs/platform/window/common/window.ts',
      'src/vs/workbench/electron-browser/desktop.contribution.ts',
    ]);
    for (const file of [...modified, ...added]) {
      assert.equal(await readFile(path.join(checkout, file), 'utf8'), await source(file), `generated checkout drift: ${file}`);
    }
  } finally {
    await rm(checkout, { recursive: true, force: true });
  }
});
