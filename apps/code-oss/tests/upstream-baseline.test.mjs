import assert from 'node:assert/strict';
import test from 'node:test';
import { mkdir, mkdtemp, readFile, readdir, rm, stat, writeFile } from 'node:fs/promises';
import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..', '..');

test('active Code-OSS baseline is the reviewed Sessions release', async () => {
  const lock = JSON.parse(await readFile(path.join(root, 'apps/code-oss/upstream.lock.json'), 'utf8'));

  assert.equal(lock.tag, '1.136.2');
  assert.equal(lock.commit, '88e44fa0e00b08f7758b4f6d05632e4fd5e4df6f');
  assert.equal(lock.sessionsBaseline.tag, lock.tag);
  assert.equal(lock.sessionsBaseline.commit, lock.commit);
  assert.equal(lock.sessionsBaseline.status, 'ACTIVE');

  const activePatches = (await readdir(path.join(root, 'apps/code-oss/patches')))
    .filter(name => name.endsWith('.patch'));
  assert.deepEqual(activePatches, []);
  await assert.rejects(stat(path.join(root, 'apps/code-oss/patches/010-native-agent-workbench.patch')));
  await stat(path.join(root, 'apps/code-oss/retired-patches/010-native-agent-workbench-1.106.3.patch'));
});

test('Task 1 baseline toolchain is complete in the Git index', () => {
  const tracked = new Set(execFileSync('git', ['ls-files'], { cwd: root, encoding: 'utf8' }).trim().split('\n'));

  for (const required of [
    'apps/code-oss/upstream.lock.json',
    'apps/code-oss/scripts/bootstrap.mjs',
    'apps/code-oss/scripts/paths.mjs',
    'apps/code-oss/scripts/apply-workbench-overlay.mjs',
    'apps/code-oss/scripts/verify.mjs',
    'apps/code-oss/patches/.gitkeep',
    'apps/code-oss/retired-patches/010-native-agent-workbench-1.106.3.patch',
  ]) {
    assert.ok(tracked.has(required), `missing tracked bootstrap dependency: ${required}`);
  }
  assert.ok(!tracked.has('apps/code-oss/extensions/agent-os/package.json'), 'legacy extension manifest must not be part of Task 1');
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

test('mismatched checkout stops before overlay mutation', async () => {
  const { bootstrap } = await import('../scripts/bootstrap.mjs');
  const fixtureRoot = await mkdtemp(path.join(os.tmpdir(), 'agent-os-bootstrap-mismatch-'));
  const generatedRoot = path.join(fixtureRoot, '.code-oss');
  const upstreamRoot = path.join(generatedRoot, 'upstream');
  const sentinel = path.join(upstreamRoot, 'sentinel.txt');

  try {
    await mkdir(upstreamRoot, { recursive: true });
    execFileSync('git', ['init'], { cwd: upstreamRoot });
    execFileSync('git', ['config', 'user.email', 'test@example.invalid'], { cwd: upstreamRoot });
    execFileSync('git', ['config', 'user.name', 'Task 1 test'], { cwd: upstreamRoot });
    await writeFile(sentinel, 'preserve this checkout\n');
    execFileSync('git', ['add', 'sentinel.txt'], { cwd: upstreamRoot });
    execFileSync('git', ['commit', '-m', 'fixture'], { cwd: upstreamRoot });

    const beforeDigest = createHash('sha256').update(await readFile(sentinel)).digest('hex');
    const beforeStatus = execFileSync('git', ['status', '--porcelain'], { cwd: upstreamRoot, encoding: 'utf8' });
    const expected = '0123456789abcdef0123456789abcdef01234567';

    await assert.rejects(
      bootstrap({
        generatedRoot,
        upstreamRoot,
        lock: { tag: 'fixture', repository: 'https://example.invalid/vscode.git', commit: expected },
        applyOverlay: () => writeFile(path.join(upstreamRoot, 'apply-marker.txt'), 'must not happen\n'),
      }),
      new Error(`Code-OSS checkout mismatch: expected ${expected}; remove only ${upstreamRoot} and rerun bootstrap`),
    );

    assert.equal(createHash('sha256').update(await readFile(sentinel)).digest('hex'), beforeDigest);
    assert.equal(execFileSync('git', ['status', '--porcelain'], { cwd: upstreamRoot, encoding: 'utf8' }), beforeStatus);
    await assert.rejects(stat(path.join(upstreamRoot, 'apply-marker.txt')));
  } finally {
    await rm(fixtureRoot, { recursive: true, force: true });
  }
});
