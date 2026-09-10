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
			// No absolute-URL escape hatch remains on the bridge surface.
			assert.equal(typeof bridge.fetchFrom, 'undefined');
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

test('channel exposes only the read-only commands and never the bearer', async () => {
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

// --- Slice 2 Task 2: task detail and trajectory reads over the bridge ---

async function readFixture(name) {
	return readFile(new URL(`./fixtures/${name}`, import.meta.url), 'utf8');
}

test('getTaskDetail fetches the task route and decodes the whitelist projection', async () => {
	const { dir, service } = await loadBridge();
	try {
		let seen;
		const detail = JSON.parse(await readFixture('task-detail-run.real.json'));
		await withServer((req, res) => {
			seen = { method: req.method, path: req.url, authorization: req.headers.authorization };
			res.end(JSON.stringify(detail));
		}, async port => {
			const descriptorPath = await writeDescriptor(dir, descriptorFor(port));
			const bridge = new service.RuntimeTaskCatalogMainService(descriptorPath);
			const result = await bridge.getTaskDetail(detail.task_id);
			assert.equal(result.taskId, detail.task_id);
			assert.equal(result.runId, detail.run.run_id);
			assert.equal(result.runStatus, 'FAILED');
			assert.equal(result.statement, detail.goal.statement);
			assert.deepEqual(seen, {
				method: 'GET',
				path: `/v1/tasks/${detail.task_id}`,
				authorization: 'Bearer test-bearer-token',
			});
			// The over-rich task_json keys must not cross the bridge.
			const wire = JSON.stringify(result);
			for (const forbidden of ['approval', 'proposed_action', 'provider', 'events', 'artifacts', 'domain_pack', 'workspace', 'test-bearer-token']) {
				assert.equal(wire.includes(forbidden), false, `forbidden payload leaked: ${forbidden}`);
			}
		});
	} finally {
		await rm(dir, { recursive: true, force: true });
	}
});

test('getTaskTrajectory fetches the run trajectory route and decodes steps', async () => {
	const { dir, service } = await loadBridge();
	try {
		let seen;
		const trajectory = JSON.parse(await readFixture('task-trajectory.real.json'));
		await withServer((req, res) => {
			seen = { method: req.method, path: req.url, authorization: req.headers.authorization };
			res.end(JSON.stringify(trajectory));
		}, async port => {
			const descriptorPath = await writeDescriptor(dir, descriptorFor(port));
			const bridge = new service.RuntimeTaskCatalogMainService(descriptorPath);
			const result = await bridge.getTaskTrajectory(trajectory.manifest.task_id, trajectory.manifest.run_id);
			assert.equal(result.steps.length, 20);
			assert.equal(result.sourceStreamLastSequence, 20);
			assert.deepEqual(seen, {
				method: 'GET',
				path: `/v1/tasks/${trajectory.manifest.task_id}/runs/${encodeURIComponent(trajectory.manifest.run_id)}/trajectory`,
				authorization: 'Bearer test-bearer-token',
			});
			assert.equal(JSON.stringify(result).includes('test-bearer-token'), false);
		});
	} finally {
		await rm(dir, { recursive: true, force: true });
	}
});

test('unsafe task and run ids are rejected before any HTTP request', async () => {
	const { dir, service } = await loadBridge();
	try {
		let hit = false;
		await withServer((req, res) => {
			hit = true;
			res.end(catalogBody());
		}, async port => {
			const descriptorPath = await writeDescriptor(dir, descriptorFor(port));
			const bridge = new service.RuntimeTaskCatalogMainService(descriptorPath);
			const badIds = ['../admin', 'task/1', 'task 1', 'task\\1', '', 'x'.repeat(300), 42, null, undefined];
			for (const bad of badIds) {
				await assert.rejects(() => bridge.getTaskDetail(bad), /not allowed|invalid/i);
				await assert.rejects(() => bridge.getTaskTrajectory(bad, 'run:9'), /not allowed|invalid/i);
				await assert.rejects(() => bridge.getTaskTrajectory('task:1', bad), /not allowed|invalid/i);
			}
			// Encoded slash inside a raw id must never smuggle a path segment.
			await assert.rejects(() => bridge.getTaskDetail('task%2Fadmin'), /not allowed|invalid/i);
		});
		assert.equal(hit, false, 'server must never receive a request for an unsafe id');
	} finally {
		await rm(dir, { recursive: true, force: true });
	}
});

test('channel exposes detail and trajectory reads with typed argument validation', async () => {
	const { dir, service, channel } = await loadBridge();
	try {
		const detail = JSON.parse(await readFixture('task-detail-run.real.json'));
		const trajectory = JSON.parse(await readFixture('task-trajectory.real.json'));
		await withServer((req, res) => {
			res.end(JSON.stringify(req.url.endsWith('/trajectory') ? trajectory : detail));
		}, async port => {
			const descriptorPath = await writeDescriptor(dir, descriptorFor(port));
			const bridge = new service.RuntimeTaskCatalogMainService(descriptorPath);
			const ipc = new channel.RuntimeTaskCatalogChannel(bridge);
			const detailResult = await ipc.call(null, 'getTaskDetail', [detail.task_id]);
			assert.equal(detailResult.runStatus, 'FAILED');
			const trajectoryResult = await ipc.call(null, 'getTaskTrajectory', [trajectory.manifest.task_id, trajectory.manifest.run_id]);
			assert.equal(trajectoryResult.steps.length, 20);
			await assert.rejects(() => ipc.call(null, 'getTaskDetail', []), /taskId|argument|invalid/i);
			await assert.rejects(() => ipc.call(null, 'getTaskDetail', [42]), /taskId|argument|invalid/i);
			await assert.rejects(() => ipc.call(null, 'getTaskTrajectory', ['task:1']), /runId|argument|invalid/i);
			await assert.rejects(() => ipc.call(null, 'getTaskTrajectory', [42, 'run:9']), /taskId|argument|invalid/i);
			await assert.rejects(() => ipc.call(null, 'cancelRun', ['run:9']), /Unknown runtime task catalog command/);
			const wire = JSON.stringify([detailResult, trajectoryResult]);
			assert.equal(wire.includes('test-bearer-token'), false);
		});
	} finally {
		await rm(dir, { recursive: true, force: true });
	}
});

test('detail and trajectory reads inherit the descriptor and response guards', async () => {
	const { dir, service } = await loadBridge();
	try {
		const detail = JSON.parse(await readFixture('task-detail-run.real.json'));
		const trajectory = JSON.parse(await readFixture('task-trajectory.real.json'));

		// 401 marks the descriptor stale.
		await withServer((req, res) => {
			res.statusCode = 401;
			res.end(JSON.stringify({ error: 'local_authentication_failed' }));
		}, async port => {
			const descriptorPath = await writeDescriptor(dir, descriptorFor(port));
			const bridge = new service.RuntimeTaskCatalogMainService(descriptorPath);
			await assert.rejects(() => bridge.getTaskDetail('task:1'), error => error.code === 'RUNTIME_DESCRIPTOR_STALE');
			await assert.rejects(() => bridge.getTaskTrajectory('task:1', 'run:9'), error => error.code === 'RUNTIME_DESCRIPTOR_STALE');
		});

		// Oversized responses are refused on both routes.
		await withServer((req, res) => {
			const big = req.url.endsWith('/trajectory')
				? { ...trajectory, steps: [...trajectory.steps, { ...trajectory.steps[0], event_digest: 'x'.repeat(2 * 1024 * 1024) }] }
				: { ...detail, oversized: 'x'.repeat(2 * 1024 * 1024) };
			res.end(JSON.stringify(big));
		}, async port => {
			const descriptorPath = await writeDescriptor(dir, descriptorFor(port));
			const bridge = new service.RuntimeTaskCatalogMainService(descriptorPath);
			await assert.rejects(() => bridge.getTaskDetail('task:1'), /too large|1 MiB/i);
			await assert.rejects(() => bridge.getTaskTrajectory('task:1', 'run:9'), /too large|1 MiB/i);
		});

		// A descriptor swap mid-request invalidates the detail response.
		await withServer(async (req, res) => {
			await new Promise(resolve => setTimeout(resolve, 250));
			res.end(JSON.stringify(detail));
		}, async port => {
			const descriptorPath = await writeDescriptor(dir, descriptorFor(port));
			const bridge = new service.RuntimeTaskCatalogMainService(descriptorPath);
			const pending = bridge.getTaskDetail('task:1');
			await new Promise(resolve => setTimeout(resolve, 50));
			await writeDescriptor(dir, descriptorFor(port, { boot_id: 'boot:swapped' }));
			await assert.rejects(pending, /descriptor/i);
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
	// A wedged runtime: ignores SIGTERM but still serves bearer-authenticated HTTP.
	const stubborn = spawn(process.execPath, ['-e', `
		process.on("SIGTERM", () => {});
		require("node:http").createServer((req, res) => {
			if (req.headers.authorization === "Bearer lifecycle-token") { res.writeHead(200); res.end("{}"); }
			else { res.writeHead(401); res.end(); }
		}).listen(0, "127.0.0.1", function () { process.stdout.write(String(this.address().port)); });
		setInterval(() => {}, 1000);
	`]);
	try {
		const port = await new Promise(resolve => stubborn.stdout.once('data', data => resolve(Number(data.toString()))));
		const exited = new Promise(resolve => stubborn.once('exit', resolve));
		const descriptorPath = await descriptorFileFor(dir, stubborn.pid, { port });
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

test('quit termination skips SIGKILL when the runtime identity probe fails', async () => {
	const { dir, lifecycle } = await loadBridge();
	const stubborn = spawn(process.execPath, ['-e', 'process.on("SIGTERM", () => {}); setInterval(() => {}, 1000); process.stdout.write("ready");']);
	try {
		await new Promise(resolve => stubborn.stdout.once('data', resolve));
		const descriptorPath = await descriptorFileFor(dir, stubborn.pid);
		// Same pid, same start time, unchanged descriptor — but no process answers
		// with the bearer on the descriptor socket, so identity is NOT proven.
		const termination = lifecycle.beginInteractiveRuntimeTermination(descriptorPath, 300, {
			probeIdentity: async () => false,
		});
		assert.equal(termination.pending, true);
		const exited = new Promise(resolve => stubborn.once('exit', () => resolve(true)));
		const result = await termination.done;
		assert.equal(result, 'terminated');
		const wasKilled = await Promise.race([exited, new Promise(resolve => setTimeout(() => resolve(false), 500))]);
		assert.equal(wasKilled, false);
		assert.equal(pidAlive(stubborn.pid), true);
	} finally {
		if (stubborn.exitCode === null) {
			stubborn.kill('SIGKILL');
		}
		await rm(dir, { recursive: true, force: true });
	}
});

test('quit termination never SIGKILLs a reused pid identity', async () => {
	const { dir, lifecycle } = await loadBridge();
	const stubborn = spawn(process.execPath, ['-e', 'process.on("SIGTERM", () => {}); setInterval(() => {}, 1000); process.stdout.write("ready");']);
	try {
		await new Promise(resolve => stubborn.stdout.once('data', resolve));
		const descriptorPath = await descriptorFileFor(dir, stubborn.pid);
		// Simulate pid reuse: the process identity fingerprint flips after
		// SIGTERM lands, i.e. the pid now hosts a different process.
		let fingerprint = 'identity:original';
		const termination = lifecycle.beginInteractiveRuntimeTermination(descriptorPath, 300, {
			fingerprintOf: () => fingerprint,
		});
		assert.equal(termination.pending, true);
		const exited = new Promise(resolve => stubborn.once('exit', () => resolve(true)));
		fingerprint = 'identity:reused';
		const result = await termination.done;
		assert.equal(result, 'terminated');
		// Fail closed: the foreign process at the reused pid must survive. Wait
		// past the kill so a (buggy) SIGKILL has time to reap before we assert.
		const wasKilled = await Promise.race([exited, new Promise(resolve => setTimeout(() => resolve(false), 500))]);
		assert.equal(wasKilled, false);
		assert.equal(pidAlive(stubborn.pid), true);
	} finally {
		if (stubborn.exitCode === null) {
			stubborn.kill('SIGKILL');
		}
		await rm(dir, { recursive: true, force: true });
	}
});

test('quit termination skips SIGKILL when the descriptor identity changes mid-flight', async () => {
	const { dir, lifecycle } = await loadBridge();
	const stubborn = spawn(process.execPath, ['-e', 'process.on("SIGTERM", () => {}); setInterval(() => {}, 1000); process.stdout.write("ready");']);
	try {
		await new Promise(resolve => stubborn.stdout.once('data', resolve));
		const descriptorPath = await descriptorFileFor(dir, stubborn.pid);
		const termination = lifecycle.beginInteractiveRuntimeTermination(descriptorPath, 300);
		assert.equal(termination.pending, true);
		// A different runtime instance now owns the descriptor file.
		await descriptorFileFor(dir, stubborn.pid, { boot_id: 'boot:other-runtime' });
		const result = await termination.done;
		assert.equal(result, 'descriptor-changed');
		assert.equal(pidAlive(stubborn.pid), true);
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
