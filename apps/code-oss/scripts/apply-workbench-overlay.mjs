import { copyFile, lstat, mkdir, readdir } from 'node:fs/promises';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import { overlayRoot, upstreamRoot } from './paths.mjs';

/**
 * Recursively copy tracked Agent OS overlay sources into the generated
 * checkout. Symlinks are rejected outright and every destination must stay
 * inside `<upstreamRoot>/src/vs/agentos`.
 */
export async function copyOverlaySource({
  overlaySrcRoot = path.join(overlayRoot, 'overlay-src'),
  upstreamRoot: targetUpstreamRoot = upstreamRoot,
} = {}) {
  const sourceRoot = path.join(overlaySrcRoot, 'src', 'vs', 'agentos');
  const targetRoot = path.join(targetUpstreamRoot, 'src', 'vs', 'agentos');
  const resolvedTarget = path.resolve(targetRoot);

  let topLevel;
  try {
    topLevel = await readdir(sourceRoot, { withFileTypes: true });
  } catch {
    return { copied: 0 }; // no overlay sources tracked yet
  }

  const pending = [{ from: sourceRoot, to: resolvedTarget }];
  let copied = 0;
  while (pending.length) {
    const { from, to } = pending.pop();
    const entries = await readdir(from, { withFileTypes: true });
    await mkdir(to, { recursive: true });
    for (const entry of entries) {
      const sourcePath = path.join(from, entry.name);
      const targetPath = path.join(to, entry.name);
      const resolved = path.resolve(targetPath);
      if (resolved !== resolvedTarget && !resolved.startsWith(resolvedTarget + path.sep)) {
        throw new Error(`overlay path escapes target root: ${sourcePath}`);
      }
      const info = await lstat(sourcePath);
      if (info.isSymbolicLink()) {
        throw new Error(`overlay source must not contain symlinks: ${sourcePath}`);
      }
      if (entry.isDirectory()) {
        pending.push({ from: sourcePath, to: targetPath });
      } else if (entry.isFile()) {
        await copyFile(sourcePath, targetPath);
        copied += 1;
      }
    }
  }
  return { copied };
}

function applyPatches({ overlayRoot: root = overlayRoot, upstreamRoot: targetUpstreamRoot = upstreamRoot } = {}) {
  return (async () => {
    const patchesRoot = path.join(root, 'patches');
    const patches = (await readdir(patchesRoot)).filter(name => name.endsWith('.patch')).sort();
    for (const name of patches) {
      const patch = path.join(patchesRoot, name);
      const reverse = spawnSync('git', ['apply', '--reverse', '--check', patch], { cwd: targetUpstreamRoot, encoding: 'utf8' });
      if (reverse.status === 0) continue;
      const check = spawnSync('git', ['apply', '--check', patch], { cwd: targetUpstreamRoot, encoding: 'utf8' });
      if (check.status !== 0) {
        throw new Error(`cannot apply ${name}: ${check.stderr || check.stdout}`);
      }
      const apply = spawnSync('git', ['apply', patch], { cwd: targetUpstreamRoot, stdio: 'inherit' });
      if (apply.status !== 0) throw new Error(`git apply failed for ${name}`);
    }
  })();
}

export async function applyWorkbenchOverlay(options = {}) {
  const copy = await copyOverlaySource(options);
  if (copy.copied > 0) console.log(`copied ${copy.copied} overlay source file(s) into src/vs/agentos`);
  await applyPatches(options);
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  await applyWorkbenchOverlay();
}
