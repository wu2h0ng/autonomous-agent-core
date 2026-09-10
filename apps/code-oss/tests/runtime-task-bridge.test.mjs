import assert from 'node:assert/strict';
import { chmod, mkdtemp, mkdir, rm, symlink, writeFile } from 'node:fs/promises';
import { stripTypeScriptTypes } from 'node:module';
import { readFile } from 'node:fs/promises';
import { spawn, spawnSync } from 'node:child_process';
import { createServer } from 'node:http';
import os from 'node:os';
import path from 'node:path';
import { test } from 'node:test';
import { upstreamRoot } from '../scripts/paths.mjs';

// Load the real overlay sources with types stripped, preserving the relative
// layout so `../common/runtimeTaskCatalog.js` resolves.
async function loadBridge() {
	const dir = await mkdtemp(path.join(os.tmpdir(), 'agent-os-bridge-'));
	await writeFile(path.join(dir, 'package.json'), '{"type":"module"}');
	const files = [
		'common/runtimeTaskCatalog.ts',
		'electron-main/runtimeTaskCatalogMainService.ts',
		'electron-main/runtimeTaskCatalogChannel.ts',
		'electron-main/interactiveRuntimeLifecycle.ts',
	];
	for (const relative of files) {
		const source = await readFile(path.join(upstreamRoot, 'src/vs/agentos', relative), 'utf8');
		const target = path.join(dir, relative.replace(/\.ts$/, '.js'));
		await mkdir(path.dirname(target), { recursive: true });
		await writeFile(target, stripTypeScriptTypes(source));
	}
	return {
		dir,
		service: await import(path.join(dir, 'electron-main/runtimeTaskCatalogMainService.js')),
		channel: await import(path.join(dir, 'electron-main/runtimeTaskCatalogChannel.js')),
		lifecycle: await import(path.join(dir, 'electron-main/interactiveRuntimeLifecycle.js')),
	};
}

function descriptorFor(port, overrides = {}) {
	return {
		protocol_version: '1.0',
		pid: process.pid,
		boot_id: 'boot:test',
		host: '127.0.0.1',
		port,
		bearer_token: 'test-bearer-token',
		database_path: '/tmp/agent-os.sqlite3',
		workspace_path: '/tmp',
		created_at: new Date().toISOString(),
		...overrides,
	};
}

async function writeDescriptor(dir, descriptor, { mode = 0o600, asSymlink = false } = {}) {
	const target = path.join(dir, 'runtime.json');
	if (asSymlink) {
		const real = path.join(dir, 'real.json');
		await writeFile(real, JSON.stringify(descriptor), { mode: 0o600 });
		await symlink(real, target);
		return target;
	}
	await writeFile(target, JSON.stringify(descriptor), { mode });
	return target;
}

async function withServer(handler, run) {
	const server = createServer(handler);
	await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
	try {
		await run(server.address().port);
	} finally {
		await new Promise(resolve => server.close(resolve));
	}
}

const catalogBody = () => JSON.stringify({
	tasks: [{ task_id: 'task:1', status: 'RUNNING', statement: 'Build the workbench', run_status: 'RUNNING', sequence: 7 }],
});

test('listTasks fetches over loopback with bearer and decodes', async () => {
	const { dir, service } = await loadBridge();
	try {
		let seen;
		await withServer((req, res) => {
			seen = { method: req.method, path: req.url, authorization: req.headers.authorization };
			res.end(catalogBody());
		}, async port => {
			const descriptorPath = await writeDescriptor(dir, descriptorFor(port));
			const snapshot = await new service.RuntimeTaskCatalogMainService(descriptorPath).listTasks();
			assert.equal(snapshot.tasks[0].taskId, 'task:1');
			assert.equal(snapshot.tasks[0].runStatus, 'RUNNING');
			assert.deepEqual(seen, {
				method: 'GET',
				path: '/v1/tasks',
				authorization: 'Bearer test-bearer-token',
			});
			assert.equal(JSON.stringify(snapshot).includes('test-bearer-token'), false);
		});
	} finally {
		await rm(dir, { recursive: true, force: true });
	}
});

test('bridge is read-only and loopback-only', async () => {
	const { dir, service } = await loadBridge();
	try {
		await withServer((req, res) => res.end(catalogBody()), async port => {
			const descriptorPath = await writeDescriptor(dir, descriptorFor(port));
			const bridge = new service.RuntimeTaskCatalogMainService(descriptorPath);
			await assert.rejects(() => bridge.request('POST', '/v1/tasks'), /read-only/);
			await assert.rejects(() => bridge.request('GET', '/v1/admin/shutdown'), /not allowed/);
			await assert.rejects(() => bridge.fetchFrom('http://example.com/v1/tasks'), /loopback/);
		});
	} finally {
		await rm(dir, { recursive: true, force: true });
	}
});

test('unsafe descriptors are refused fail-closed', async () => {
	const { dir, service } = await loadBridge();
	try {
		await withServer((req, res) => res.end(catalogBody()), async port => {
			const deadPid = spawnSync('true').pid;
			const cases = [
				await writeDescriptor(dir, descriptorFor(port), { asSymlink: true }),
				await writeDescriptor(dir, descriptorFor(port, { host: '0.0.0.0' }), ),
				await writeDescriptor(dir, descriptorFor(port, { protocol_version: '0.9' })),
				await writeDescriptor(dir, descriptorFor(port, { pid: deadPid })),
				await writeDescriptor(dir, descriptorFor(port, { bearer_token: '' })),
			];
			for (const descriptorPath of cases) {
				await assert.rejects(() => new service.RuntimeTaskCatalogMainService(descriptorPath).listTasks(), /descriptor/i);
			}
			const groupReadable = await writeDescriptor(dir, descriptorFor(port), { mode: 0o640 });
			await assert.rejects(() => new service.RuntimeTaskCatalogMainService(groupReadable).listTasks(), /descriptor/i);
		});
	} finally {
		await rm(dir, { recursive: true, force: true });
	}
});

test('descriptor mutation during a request rejects the response', async () => {
	const { dir, service } = await loadBridge();
	try {
		await withServer(async (req, res) => {
			await new Promise(resolve => setTimeout(resolve, 250));
			res.end(catalogBody());
		}, async port => {
			const descriptorPath = await writeDescriptor(dir, descriptorFor(port));
			const bridge = new service.RuntimeTaskCatalogMainService(descriptorPath);
			const pending = bridge.listTasks();
			await new Promise(resolve => setTimeout(resolve, 50));
			await writeDescriptor(dir, descriptorFor(port, { boot_id: 'boot:swapped' }));
			await assert.rejects(pending, /descriptor/i);
		});
	} finally {
		await rm(dir, { recursive: true, force: true });
	}
});

test('oversized responses are rejected', async () => {
	const { dir, service } = await loadBridge();
	try {
		await withServer((req, res) => {
			res.end(JSON.stringify({ tasks: [{ task_id: 'task:big', status: 'x'.repeat(2 * 1024 * 1024), statement: 'x', run_status: null, sequence: 1 }] }));
		}, async port => {
			const descriptorPath = await writeDescriptor(dir, descriptorFor(port));
			await assert.rejects(() => new service.RuntimeTaskCatalogMainService(descriptorPath).listTasks(), /too large|1 MiB/i);
		});
	} finally {
		await rm(dir, { recursive: true, force: true });
	}
});

test('401 marks the descriptor stale with a typed error', async () => {
	const { dir, service } = await loadBridge();
	try {
		await withServer((req, res) => {
			res.statusCode = 401;
			res.end(JSON.stringify({ error: 'local_authentication_failed' }));
		}, async port => {
			const descriptorPath = await writeDescriptor(dir, descriptorFor(port));
			await assert.rejects(
				() => new service.RuntimeTaskCatalogMainService(descriptorPath).listTasks(),
				error => error.code === 'RUNTIME_DESCRIPTOR_STALE',
			);
		});
	} finally {
		await rm(dir, { recursive: true, force: true });
	}
});

test('channel exposes exactly one read-only command and never the bearer', async () => {
	const { dir, service, channel } = await loadBridge();
	try {
		await withServer((req, res) => res.end(catalogBody()), async port => {
			const descriptorPath = await writeDescriptor(dir, descriptorFor(port));
			const bridge = new service.RuntimeTaskCatalogMainService(descriptorPath);
			const ipc = new channel.RuntimeTaskCatalogChannel(bridge);
			const snapshot = await ipc.call(null, 'listTasks', []);
			assert.equal(snapshot.tasks[0].taskId, 'task:1');
			await assert.rejects(() => ipc.call(null, 'deleteAll', []), /Unknown runtime task catalog command/);
			await assert.rejects(() => ipc.call(null, 'request', ['POST', '/v1/tasks']), /Unknown runtime task catalog command/);
			assert.equal(JSON.stringify(snapshot).includes('test-bearer-token'), false);
		});
	} finally {
		await rm(dir, { recursive: true, force: true });
	}
});

function descriptorFileFor(dir, pid, overrides = {}) {
	return writeDescriptor(dir, {
		protocol_version: '1.0',
		pid,
		boot_id: 'boot:lifecycle',
		host: '127.0.0.1',
		port: 9,
		bearer_token: 'lifecycle-token',
		database_path: '/tmp/agent-os.sqlite3',
		workspace_path: '/tmp',
		created_at: new Date().toISOString(),
		...overrides,
	});
}

function pidAlive(pid) {
	try {
		process.kill(pid, 0);
		return true;
	} catch {
		return false;
	}
}

test('application quit termination SIGTERMs the live interactive runtime', async () => {
	const { dir, lifecycle } = await loadBridge();
	const sleeper = spawn('sleep', ['30']);
	try {
		const descriptorPath = await descriptorFileFor(dir, sleeper.pid);
		const termination = lifecycle.beginInteractiveRuntimeTermination(descriptorPath);
		assert.equal(termination.pending, true);
		assert.equal(await termination.done, 'terminated');
		assert.equal(pidAlive(sleeper.pid), false);
	} finally {
		if (sleeper.exitCode === null) {
			sleeper.kill('SIGKILL');
		}
		await rm(dir, { recursive: true, force: true });
	}
});

test('quit termination escalates to SIGKILL past the deadline', async () => {
	const { dir, lifecycle } = await loadBridge();
	const stubborn = spawn(process.execPath, ['-e', 'process.on("SIGTERM", () => {}); setInterval(() => {}, 1000); process.stdout.write("ready");']);
	try {
		await new Promise(resolve => stubborn.stdout.once('data', resolve));
		const exited = new Promise(resolve => stubborn.once('exit', resolve));
		const descriptorPath = await descriptorFileFor(dir, stubborn.pid);
		const termination = lifecycle.beginInteractiveRuntimeTermination(descriptorPath, 300);
		assert.equal(termination.pending, true);
		assert.equal(await termination.done, 'terminated');
		await exited;
		assert.equal(stubborn.signalCode, 'SIGKILL');
	} finally {
		if (stubborn.exitCode === null) {
			stubborn.kill('SIGKILL');
		}
		await rm(dir, { recursive: true, force: true });
	}
});

test('quit termination skips missing, unsafe or dead descriptors', async () => {
	const { dir, lifecycle } = await loadBridge();
	try {
		const missing = lifecycle.beginInteractiveRuntimeTermination(path.join(dir, 'nope.json'));
		assert.equal(missing.pending, false);
		assert.equal(await missing.done, 'descriptor-unavailable');

		const dead = lifecycle.beginInteractiveRuntimeTermination(await descriptorFileFor(dir, 2 ** 20));
		assert.equal(dead.pending, false);
		assert.equal(await dead.done, 'not-running');

		const worldReadable = await descriptorFileFor(dir, process.pid, {});
		const { chmod } = await import('node:fs/promises');
		await chmod(worldReadable, 0o644);
		const unsafe = lifecycle.beginInteractiveRuntimeTermination(worldReadable);
		assert.equal(unsafe.pending, false);
		assert.equal(await unsafe.done, 'descriptor-unavailable');
	} finally {
		await rm(dir, { recursive: true, force: true });
	}
});

test('application quit hook is gated on having served the catalog', async () => {
	const appSource = await readFile(path.join(upstreamRoot, 'src/vs/code/electron-main/app.ts'), 'utf8');
	assert.match(appSource, /app\.once\('will-quit'/);
	assert.match(appSource, /runtimeTaskCatalogMainService\.hasServedCatalog/);
	assert.match(appSource, /beginInteractiveRuntimeTermination\(runtimeDescriptorPath\)/);
	assert.match(appSource, /import \{ beginInteractiveRuntimeTermination \} from '\.\.\/\.\.\/agentos\/electron-main\/interactiveRuntimeLifecycle\.js'/);
});
