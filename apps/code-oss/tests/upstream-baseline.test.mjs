import assert from 'node:assert/strict';
import test from 'node:test';
import { readFile } from 'node:fs/promises';
import { execFileSync } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..', '..');

test('active Code-OSS baseline is the reviewed Sessions release', async () => {
  const lock = JSON.parse(await readFile(path.join(root, 'apps/code-oss/upstream.lock.json'), 'utf8'));

  assert.equal(lock.tag, '1.136.2');
  assert.equal(lock.commit, '88e44fa0e00b08f7758b4f6d05632e4fd5e4df6f');
  assert.equal(lock.sessionsBaseline.status, 'ACTIVE');
});

test('Task 1 baseline toolchain is complete in the Git index', () => {
  const tracked = new Set(execFileSync('git', ['ls-files'], { cwd: root, encoding: 'utf8' }).trim().split('\n'));

  for (const required of [
    'apps/code-oss/upstream.lock.json',
    'apps/code-oss/scripts/bootstrap.mjs',
    'apps/code-oss/scripts/paths.mjs',
    'apps/code-oss/scripts/apply-workbench-overlay.mjs',
    'apps/code-oss/scripts/verify.mjs',
    'apps/code-oss/extensions/agent-os/package.json',
  ]) {
    assert.ok(tracked.has(required), `missing tracked bootstrap dependency: ${required}`);
  }
});

test('bootstrap clone arguments safely bypass an unavailable Git LFS filter', async () => {
  const { cloneArguments } = await import('../scripts/bootstrap.mjs');

  assert.deepEqual(cloneArguments({ tag: '1.136.2', repository: 'https://example.invalid/vscode.git' }), [
    '-c', 'filter.lfs.clean=cat',
    '-c', 'filter.lfs.smudge=cat',
    '-c', 'filter.lfs.process=',
    '-c', 'filter.lfs.required=false',
    'clone', '--depth', '1', '--branch', '1.136.2', 'https://example.invalid/vscode.git', 'upstream',
  ]);
});
