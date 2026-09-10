import { readFile } from 'node:fs/promises';
import { spawnSync } from 'node:child_process';
import path from 'node:path';
import { overlayRoot, upstreamRoot } from './paths.mjs';

const lock = JSON.parse(await readFile(path.join(overlayRoot, 'upstream.lock.json'), 'utf8'));
const head = spawnSync('git', ['rev-parse', 'HEAD'], { cwd: upstreamRoot, encoding: 'utf8' });
if (head.status !== 0 || head.stdout.trim() !== lock.commit) throw new Error('Code-OSS checkout does not match upstream.lock.json');
const read = relative => readFile(path.join(upstreamRoot, relative), 'utf8');
const [windowContract, sessionsBootstrap, sessionsWorkbench] = await Promise.all([
  read('src/vs/platform/window/common/window.ts'),
  read('src/vs/sessions/electron-browser/sessions.ts'),
  read('src/vs/sessions/browser/workbench.ts'),
]);
if (!windowContract.includes('isSessionsWindow?: boolean')) throw new Error('upstream Sessions window configuration is missing');
if (!sessionsBootstrap.includes('vs/sessions/sessions.desktop.main.js')) throw new Error('upstream Sessions renderer bootstrap is missing');
if (!sessionsWorkbench.includes('export class Workbench extends Disposable')) throw new Error('upstream Sessions Workbench is missing');
console.log(`verified Code-OSS ${lock.tag} upstream Sessions baseline (${lock.commit})`);

const focused = spawnSync(process.execPath, ['--test',
  path.join(overlayRoot, 'tests/upstream-baseline.test.mjs'),
  path.join(overlayRoot, 'tests/sessions-workbench-structure.test.mjs'),
  path.join(overlayRoot, 'tests/native-agent-window.test.mjs'),
  path.join(overlayRoot, 'tests/runtime-task-contract.test.mjs'),
  path.join(overlayRoot, 'tests/runtime-task-detail-contract.test.mjs'),
  path.join(overlayRoot, 'tests/runtime-task-bridge.test.mjs'),
  path.join(overlayRoot, 'tests/agent-os-sessions-provider.test.mjs'),
], { stdio: 'inherit' });
if (focused.status !== 0) throw new Error('Agent OS dual-workbench focused verification failed');
console.log('focused verification passed; run the end-to-end slice with: node --test apps/code-oss/tests/dual-workbench-slice-1.test.mjs');
