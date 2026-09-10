import { fileURLToPath } from 'node:url';
import path from 'node:path';

export const overlayRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
export const repositoryRoot = path.resolve(overlayRoot, '..', '..');
export const generatedRoot = path.join(repositoryRoot, '.code-oss');
export const upstreamRoot = path.join(generatedRoot, 'upstream');
export const extensionSource = path.join(overlayRoot, 'extensions', 'agent-os');
export const extensionTarget = path.join(upstreamRoot, 'extensions', 'agent-os');
