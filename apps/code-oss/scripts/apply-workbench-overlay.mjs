import { readdir } from 'node:fs/promises';
import { spawnSync } from 'node:child_process';
import path from 'node:path';
import { overlayRoot, upstreamRoot } from './paths.mjs';

const patchesRoot = path.join(overlayRoot, 'patches');
const patches = (await readdir(patchesRoot)).filter(name => name.endsWith('.patch')).sort();
for (const name of patches) {
  const patch = path.join(patchesRoot, name);
  const reverse = spawnSync('git', ['apply', '--reverse', '--check', patch], { cwd: upstreamRoot, encoding: 'utf8' });
  if (reverse.status === 0) continue;
  const check = spawnSync('git', ['apply', '--check', patch], { cwd: upstreamRoot, encoding: 'utf8' });
  if (check.status !== 0) {
    throw new Error(`cannot apply ${name}: ${check.stderr || check.stdout}`);
  }
  const apply = spawnSync('git', ['apply', patch], { cwd: upstreamRoot, stdio: 'inherit' });
  if (apply.status !== 0) throw new Error(`git apply failed for ${name}`);
}
