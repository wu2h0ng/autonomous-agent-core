import { mkdir, readFile, stat } from 'node:fs/promises';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import { overlayRoot, generatedRoot, upstreamRoot } from './paths.mjs';

const lock = JSON.parse(await readFile(path.join(overlayRoot, 'upstream.lock.json'), 'utf8'));

export function cloneArguments({ tag, repository }, destination = 'upstream') {
  return [
    '-c', 'filter.lfs.clean=cat',
    '-c', 'filter.lfs.smudge=cat',
    '-c', 'filter.lfs.process=',
    '-c', 'filter.lfs.required=false',
    'clone', '--depth', '1', '--branch', tag, repository, destination,
  ];
}

function run(command, args, cwd = undefined) {
  const result = spawnSync(command, args, { cwd, stdio: 'inherit' });
  if (result.status !== 0) throw new Error(`${command} exited with ${result.status}`);
}

export async function bootstrap({
  generatedRoot: configuredGeneratedRoot = generatedRoot,
  upstreamRoot: configuredUpstreamRoot = upstreamRoot,
  lock: configuredLock = lock,
  applyOverlay = () => import('./apply-workbench-overlay.mjs'),
} = {}) {
  await mkdir(configuredGeneratedRoot, { recursive: true, mode: 0o700 });
  let checkoutExists = false;
  try { checkoutExists = (await stat(path.join(configuredUpstreamRoot, '.git'))).isDirectory(); } catch {}
  if (!checkoutExists) {
    run('git', cloneArguments(configuredLock, configuredUpstreamRoot));
  }
  const head = spawnSync('git', ['rev-parse', 'HEAD'], { cwd: configuredUpstreamRoot, encoding: 'utf8' });
  if (head.status !== 0 || head.stdout.trim() !== configuredLock.commit) {
    throw new Error(`Code-OSS checkout mismatch: expected ${configuredLock.commit}; remove only ${configuredUpstreamRoot} and rerun bootstrap`);
  }
  await applyOverlay();
  console.log(`Agent OS Code-OSS workspace ready at ${configuredUpstreamRoot}`);
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  await bootstrap();
}
