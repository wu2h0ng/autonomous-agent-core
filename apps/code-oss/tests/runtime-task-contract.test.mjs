import assert from 'node:assert/strict';
import { mkdtemp, mkdir, rm, symlink, writeFile } from 'node:fs/promises';
import { stripTypeScriptTypes } from 'node:module';
import { readFile } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { test } from 'node:test';
import { overlayRoot, upstreamRoot } from '../scripts/paths.mjs';

const generatedCatalog = path.join(upstreamRoot, 'src/vs/agentos/common/runtimeTaskCatalog.ts');

async function loadDecoder(sourcePath = generatedCatalog) {
	const text = await readFile(sourcePath, 'utf8');
	return import(`data:text/javascript;base64,${Buffer.from(stripTypeScriptTypes(text)).toString('base64')}`);
}

const validPayload = () => ({
	tasks: [
		{ task_id: 'task:1', status: 'RUNNING', statement: 'Build the workbench', run_status: 'RUNNING', sequence: 7 },
		{ task_id: 'task:2', status: null, statement: 'Quick chat', run_status: null, sequence: 0 },
	],
});

test('decoder maps the exact GET /v1/tasks projection', async () => {
	const { decodeTaskCatalog } = await loadDecoder();
	const snapshot = decodeTaskCatalog(validPayload(), 1234);
	assert.equal(snapshot.fetchedAt, 1234);
	assert.deepEqual(snapshot.tasks[0], {
		taskId: 'task:1',
		status: 'RUNNING',
		statement: 'Build the workbench',
		runStatus: 'RUNNING',
		sequence: 7,
	});
	assert.deepEqual(snapshot.tasks[1], {
		taskId: 'task:2',
		status: null,
		statement: 'Quick chat',
		runStatus: null,
		sequence: 0,
	});
});

test('decoder rejects extra root keys including authority material', async () => {
	const { decodeTaskCatalog } = await loadDecoder();
	assert.throws(() => decodeTaskCatalog({ tasks: [], bearer_token: 'forbidden' }));
	assert.throws(() => decodeTaskCatalog({ tasks: [], principal: 'user:x' }));
	assert.throws(() => decodeTaskCatalog({}));
	assert.throws(() => decodeTaskCatalog(null));
	assert.throws(() => decodeTaskCatalog({ tasks: {} }));
});

test('decoder rejects extra or missing task keys', async () => {
	const { decodeTaskCatalog } = await loadDecoder();
	const extra = validPayload();
	extra.tasks[0].token = 'secret';
	assert.throws(() => decodeTaskCatalog(extra));
	const missing = validPayload();
	delete missing.tasks[0].run_status;
	assert.throws(() => decodeTaskCatalog(missing));
});

test('decoder enforces field shapes fail-closed', async () => {
	const { decodeTaskCatalog } = await loadDecoder();
	const withTask = patch => {
		const payload = validPayload();
		Object.assign(payload.tasks[0], patch);
		return payload;
	};
	assert.throws(() => decodeTaskCatalog(withTask({ task_id: '' })));
	assert.throws(() => decodeTaskCatalog(withTask({ task_id: 42 })));
	assert.throws(() => decodeTaskCatalog(withTask({ sequence: -1 })));
	assert.throws(() => decodeTaskCatalog(withTask({ sequence: 1.5 })));
	assert.throws(() => decodeTaskCatalog(withTask({ sequence: '7' })));
	assert.throws(() => decodeTaskCatalog(withTask({ status: 7 })));
	assert.throws(() => decodeTaskCatalog(withTask({ statement: null })));
	assert.throws(() => decodeTaskCatalog(withTask({ statement: 9 })));
});

test('overlay copy rejects symlinks and path escape', async () => {
	const { copyOverlaySource } = await import('../scripts/apply-workbench-overlay.mjs');
	const fixture = await mkdtemp(path.join(os.tmpdir(), 'agent-os-overlay-'));
	const overlaySrc = path.join(fixture, 'overlay-src/src/vs/agentos');
	const target = path.join(fixture, 'upstream/src/vs/agentos');
	try {
		await mkdir(overlaySrc, { recursive: true });
		await mkdir(target, { recursive: true });
		await writeFile(path.join(overlaySrc, 'real.ts'), 'export const ok = 1;\n');
		await symlink(path.join(overlaySrc, 'real.ts'), path.join(overlaySrc, 'evil.ts'));
		await assert.rejects(
			copyOverlaySource({ overlaySrcRoot: path.join(fixture, 'overlay-src'), upstreamRoot: path.join(fixture, 'upstream') }),
			/symlink/,
		);
	} finally {
		await rm(fixture, { recursive: true, force: true });
	}
});

test('overlay copy places tracked sources into the generated checkout', async () => {
	const { copyOverlaySource } = await import('../scripts/apply-workbench-overlay.mjs');
	const fixture = await mkdtemp(path.join(os.tmpdir(), 'agent-os-overlay-'));
	const overlaySrc = path.join(fixture, 'overlay-src/src/vs/agentos/common');
	const upstream = path.join(fixture, 'upstream');
	try {
		await mkdir(overlaySrc, { recursive: true });
		await mkdir(path.join(upstream, 'src/vs'), { recursive: true });
		await writeFile(path.join(overlaySrc, 'sample.ts'), 'export const sample = true;\n');
		await copyOverlaySource({ overlaySrcRoot: path.join(fixture, 'overlay-src'), upstreamRoot: upstream });
		const copied = await readFile(path.join(upstream, 'src/vs/agentos/common/sample.ts'), 'utf8');
		assert.equal(copied, 'export const sample = true;\n');
	} finally {
		await rm(fixture, { recursive: true, force: true });
	}
});

test('generated checkout carries the tracked runtime task catalog', async () => {
	const { decodeTaskCatalog } = await loadDecoder();
	assert.equal(typeof decodeTaskCatalog, 'function');
	const tracked = await readFile(
		path.join(overlayRoot, 'overlay-src/src/vs/agentos/common/runtimeTaskCatalog.ts'), 'utf8');
	const generated = await readFile(generatedCatalog, 'utf8');
	assert.equal(generated, tracked, 'generated checkout drifted from tracked overlay-src');
});
