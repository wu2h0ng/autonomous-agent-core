import { chmod, copyFile, mkdir, readdir, readFile, rm, stat, writeFile } from 'node:fs/promises';
import { spawnSync } from 'node:child_process';
import path from 'node:path';
import { upstreamRoot } from './paths.mjs';

function run(command, args, options = {}) {
  const result = spawnSync(command, args, { cwd: upstreamRoot, stdio: 'inherit', ...options });
  if (result.status !== 0) throw new Error(`${command} exited with ${result.status}`);
}

run('npm', ['ci', '--ignore-scripts', '--prefer-offline', '--fetch-retries=8', '--fetch-retry-maxtimeout=180000', '--fetch-timeout=600000']);
run(process.execPath, ['build/npm/postinstall.ts'], {
  env: { ...process.env, npm_command: 'ci --ignore-scripts' }
});

if (process.platform === 'darwin') {
  const fmtHeader = path.join(upstreamRoot, 'node_modules/@vscode/spdlog/deps/spdlog/include/spdlog/fmt/bundled/core.h');
  const source = await readFile(fmtHeader, 'utf8');
  const incompatible = '#    define FMT_CONSTEVAL consteval';
  const compatible = '#    define FMT_CONSTEVAL';
  if (!source.includes(compatible)) throw new Error('Unexpected bundled fmt header; refusing an unverified patch');
  if (source.includes(incompatible)) await writeFile(fmtHeader, source.replace(incompatible, compatible));
}

const ripgrepBin = path.join(upstreamRoot, 'node_modules/@vscode/ripgrep/bin');
await rm(ripgrepBin, { recursive: true, force: true });
const systemRipgrep = spawnSync('which', ['rg'], { encoding: 'utf8' }).stdout.trim();
if (systemRipgrep) {
  await mkdir(ripgrepBin, { recursive: true });
  await copyFile(systemRipgrep, path.join(ripgrepBin, 'rg'));
  await chmod(path.join(ripgrepBin, 'rg'), 0o755);
} else {
  run(process.execPath, ['node_modules/@vscode/ripgrep/lib/postinstall.js']);
}

// node-gyp breaks when the resolved Python lives under a path with spaces
// (e.g. "~/Library/Application Support/..."); prefer the space-free system Python.
const systemPython = spawnSync('ls', ['/usr/bin/python3'], { encoding: 'utf8' });

// Native modules must target the bundled Electron ABI. The upstream .npmrc
// `target`/`disturl` keys are silently ignored by newer npm, so pass them
// explicitly as env vars that node-gyp still honors. Electron is downloaded
// to `.build/electron` by postinstall; its version file is the source of truth.
const electronVersion = (
  await readFile(path.join(upstreamRoot, '.build/electron/version'), 'utf8')
).trim();

const rebuildEnv = {
  ...process.env,
  ...(systemPython.status === 0 && !process.env.npm_config_python
    ? { npm_config_python: '/usr/bin/python3' }
    : {}),
  npm_config_runtime: 'electron',
  npm_config_target: electronVersion,
  npm_config_dist_url: 'https://electronjs.org/headers',
  npm_config_build_from_source: 'true',
};

run('npm', ['rebuild',
  '@parcel/watcher', '@vscode/deviceid', '@vscode/fs-copyfile', '@vscode/native-watchdog',
  '@vscode/policy-watcher', '@vscode/spdlog', '@vscode/sqlite3',
  'bufferutil', 'native-is-elevated', 'native-keymap',
  'node-pty', 'utf-8-validate', 'kerberos'
  // cpu-features (ssh2) intentionally excluded: NAN pins break against the
  // bundled Node headers and remote tunnelling is not part of the desktop slice.
], { env: rebuildEnv });

// Extensions keep their own nested node_modules (installed by postinstall.ts
// with scripts disabled), so their native addons never get built. Rebuild them
// here against the Electron ABI. Failures are tolerated except for the
// required list — a missing required addon surfaces as a broken extension.
const requiredNested = [path.join('extensions', 'git', 'node_modules', '@vscode', 'fs-copyfile')];
const nestedAddons = [];
async function findAddons(dir) {
  let entries = [];
  try { entries = await readdir(dir, { withFileTypes: true }); } catch { return; }
  for (const entry of entries) {
    if (!entry.isDirectory()) continue;
    if (entry.name === '.bin' || entry.name.startsWith('.')) continue;
    const full = path.join(dir, entry.name);
    try {
      await stat(path.join(full, 'binding.gyp'));
      nestedAddons.push(full);
      continue;
    } catch {}
    await findAddons(full);
  }
}
await findAddons(path.join(upstreamRoot, 'extensions'));
for (const addon of nestedAddons) {
  const relative = path.relative(upstreamRoot, addon);
  const build = spawnSync('npx', ['node-gyp', 'rebuild'], { cwd: addon, env: rebuildEnv, stdio: 'pipe' });
  if (build.status !== 0) {
    if (requiredNested.includes(relative)) {
      console.error(build.stderr?.toString() ?? '');
      throw new Error(`required nested native addon failed to build: ${relative}`);
    }
    console.warn(`optional nested native addon skipped (build failed): ${relative}`);
  }
}

console.log('Code-OSS dependencies installed and native modules rebuilt.');
