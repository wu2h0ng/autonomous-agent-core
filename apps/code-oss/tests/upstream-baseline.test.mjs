import assert from 'node:assert/strict';
import test from 'node:test';
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..', '..');

test('active Code-OSS baseline is the reviewed Sessions release', async () => {
  const lock = JSON.parse(await readFile(path.join(root, 'apps/code-oss/upstream.lock.json'), 'utf8'));

  assert.equal(lock.tag, '1.136.2');
  assert.equal(lock.commit, '88e44fa0e00b08f7758b4f6d05632e4fd5e4df6f');
  assert.equal(lock.sessionsBaseline.status, 'ACTIVE');
});
