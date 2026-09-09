import { cp, mkdir, readFile, stat } from 'node:fs/promises';
import { spawnSync } from 'node:child_process';
import path from 'node:path';
import { overlayRoot, generatedRoot, upstreamRoot, extensionSource, extensionTarget } from './paths.mjs';

const lock = JSON.parse(await readFile(path.join(overlayRoot, 'upstream.lock.json'), 'utf8'));

function run(command, args, cwd = undefined) {
  const result = spawnSync(command, args, { cwd, stdio: 'inherit' });
  if (result.status !== 0) throw new Error(`${command} exited with ${result.status}`);
}

await mkdir(generatedRoot, { recursive: true, mode: 0o700 });
let checkoutExists = false;
try { checkoutExists = (await stat(path.join(upstreamRoot, '.git'))).isDirectory(); } catch {}
if (!checkoutExists) {
  run('git', ['clone', '--depth', '1', '--branch', lock.tag, lock.repository, upstreamRoot]);
}
const head = spawnSync('git', ['rev-parse', 'HEAD'], { cwd: upstreamRoot, encoding: 'utf8' });
if (head.status !== 0 || head.stdout.trim() !== lock.commit) {
  throw new Error(`Code-OSS checkout mismatch: expected ${lock.commit}; remove only ${upstreamRoot} and rerun bootstrap`);
}
await cp(extensionSource, extensionTarget, {
  recursive: true,
  force: true,
  filter: source => !source.includes('node_modules')
});
await import('./apply-workbench-overlay.mjs');
console.log(`Agent OS Code-OSS workspace ready at ${upstreamRoot}`);
