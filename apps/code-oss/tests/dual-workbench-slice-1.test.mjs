import assert from 'node:assert/strict';
import { spawn, spawnSync } from 'node:child_process';
import { mkdtemp, mkdir, readFile, rm, writeFile } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { test } from 'node:test';
import { overlayRoot, upstreamRoot } from '../scripts/paths.mjs';

// End-to-end oracle for Slice 1: one Code-OSS application, two native windows,
// a real Python Runtime, and a read-only task projection — with the bearer
// token provably absent from every renderer.

const repoRoot = path.resolve(overlayRoot, '../..');
// The shared development venv lives at the main checkout root (gitignored, so
// never inside a worktree); the contracts sources are the worktree's own.
const venvPython = process.env.AGENT_OS_E2E_PYTHON ?? path.resolve(repoRoot, '../../.venv/bin/python');
const contractsSrc = path.join(repoRoot, 'packages/contracts/src');
const osCoreSrc = path.join(repoRoot, 'packages/os_core/src');
const pythonPath = [contractsSrc, osCoreSrc, process.env.PYTHONPATH].filter(Boolean).join(path.delimiter);
const electronBinary = path.join(upstreamRoot, '.build/electron/Code - OSS.app/Contents/MacOS/Code - OSS');
const codeLauncher = path.join(upstreamRoot, 'scripts/code.sh');
const logsDir = path.join(repoRoot, '.agent_runs/dual-workbench-slice-1-20260909/e2e-logs');

const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

async function waitFor(label, predicate, timeoutMs, intervalMs = 250) {
	const deadline = Date.now() + timeoutMs;
	let lastError;
	while (Date.now() < deadline) {
		try {
			const value = await predicate();
			if (value) {
				return value;
			}
		} catch (error) {
			lastError = error;
		}
		await sleep(intervalMs);
	}
	throw new Error(`timed out waiting for ${label}${lastError ? ` (last error: ${lastError.message} ${lastError.cause?.code ?? lastError.cause?.message ?? ''})` : ''}`);
}

function spawnLogged(command, args, options, logName) {
	const child = spawn(command, args, { ...options, stdio: ['ignore', 'pipe', 'pipe'] });
	const out = [];
	const err = [];
	child.stdout.on('data', chunk => out.push(chunk));
	child.stderr.on('data', chunk => err.push(chunk));
	child.on('exit', async () => {
		await mkdir(logsDir, { recursive: true });
		await writeFile(path.join(logsDir, `${logName}.out.log`), Buffer.concat(out));
		await writeFile(path.join(logsDir, `${logName}.err.log`), Buffer.concat(err));
	});
	return child;
}

/** Minimal CDP client over the Node built-in WebSocket. */
class CdpSession {
	constructor(wsUrl) {
		this.nextId = 1;
		this.pending = new Map();
		this.consoleMessages = [];
		this.ws = new WebSocket(wsUrl);
		this.ready = new Promise((resolve, reject) => {
			this.ws.addEventListener('open', resolve, { once: true });
			this.ws.addEventListener('error', reject, { once: true });
		});
		this.ws.addEventListener('message', event => {
			const message = JSON.parse(event.data);
			if (message.id !== undefined) {
				const entry = this.pending.get(message.id);
				if (entry) {
					this.pending.delete(message.id);
					if (message.error) {
						entry.reject(new Error(`${entry.method} failed: ${message.error.message}`));
					} else {
						entry.resolve(message.result);
					}
				}
			} else if (message.method === 'Runtime.consoleAPICalled') {
				this.consoleMessages.push(message.params.args.map(arg => arg.value ?? arg.description ?? '').join(' '));
			} else if (message.method === 'Runtime.exceptionThrown') {
				this.consoleMessages.push(`EXCEPTION ${JSON.stringify(message.params.exceptionDetails)}`);
			}
		});
		this.ws.addEventListener('close', () => {
			for (const entry of this.pending.values()) {
				entry.reject(new Error(`${entry.method} aborted: CDP socket closed`));
			}
			this.pending.clear();
		});
	}

	static async connect(wsUrl, { enableRuntime = true } = {}) {
		const session = new CdpSession(wsUrl);
		await session.ready;
		if (enableRuntime) {
			try {
				await session.send('Runtime.enable');
			} catch (error) {
				throw new Error(`Runtime.enable on ${wsUrl}: ${error.message}`);
			}
		}
		console.log(`[e2e] CDP connected: ${wsUrl}`);
		return session;
	}

	send(method, params = {}) {
		const id = this.nextId++;
		return new Promise((resolve, reject) => {
			this.pending.set(id, { resolve, reject, method });
			this.ws.send(JSON.stringify({ id, method, params }));
		});
	}

	async evaluate(expression) {
		const result = await this.send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
		if (result.exceptionDetails) {
			throw new Error(`evaluation failed: ${JSON.stringify(result.exceptionDetails).slice(0, 400)}`);
		}
		return result.result.value;
	}

	close() {
		try { this.ws.close(); } catch { /* already closed */ }
	}
}

test('dual workbench slice 1: real runtime, two native windows, read-only projection', { timeout: 420_000 }, async () => {
	assert.ok(existsSync(venvPython), `python venv missing: ${venvPython}`);
	assert.ok(existsSync(electronBinary), `electron build missing: ${electronBinary}`);

	const tmp = await mkdtemp(path.join(os.tmpdir(), 'agent-os-e2e-'));
	const descriptorPath = path.join(tmp, 'runtime.json');
	const workspaceDir = path.join(tmp, 'workspace');
	const userDataDir = path.join(tmp, 'user-data');
	const extensionsDir = path.join(tmp, 'extensions');
	await mkdir(workspaceDir, { recursive: true });
	await mkdir(path.join(userDataDir, 'User'), { recursive: true });
	await writeFile(path.join(workspaceDir, 'README.md'), '# e2e workspace\n');
	await writeFile(path.join(userDataDir, 'User', 'settings.json'), JSON.stringify({
		'chat.agentHost.allowSignedOutWhenUsable': true,
		'security.workspace.trust.enabled': false,
		'telemetry.telemetryLevel': 'off',
		'update.mode': 'none',
	}));

	let runtime;
	let app;
	try {
		// --- 1. Real runtime with two persisted tasks --------------------------
		runtime = spawnLogged(venvPython, [
			'-m', 'apps.runtime_daemon',
			'--database', path.join(tmp, 'runtime.sqlite3'),
			'--workspace', workspaceDir,
			'--descriptor', descriptorPath,
			'--port', '0',
		], {
			cwd: repoRoot,
			env: { ...process.env, PYTHONPATH: pythonPath },
		}, 'runtime');
		await waitFor('runtime descriptor', () => existsSync(descriptorPath) || null, 20_000);
		const descriptor = JSON.parse(await readFile(descriptorPath, 'utf8'));
		const token = descriptor.bearer_token;
		const base = `http://127.0.0.1:${descriptor.port}`;

		const statements = ['Design the dual workbench', 'Review the slice one gates'];
		for (const [index, statement] of statements.entries()) {
			const created = await fetch(`${base}/v1/tasks`, {
				method: 'POST',
				headers: { 'Authorization': `Bearer ${token}`, 'Content-Type': 'application/json' },
				body: JSON.stringify({
					goal_id: `goal:e2e:${index}`,
					tenant_id: 'tenant:e2e',
					workspace_id: 'workspace:e2e',
					created_by: 'test:dual-workbench-slice-1',
					created_at: new Date().toISOString(),
					statement,
				}),
			});
			assert.equal(created.status, 201, `task seeding failed: ${created.status} ${await created.text()}`);
		}
		const listed = await (await fetch(`${base}/v1/tasks`, { headers: { Authorization: `Bearer ${token}` } })).json();
		assert.equal(listed.tasks.length, 2);

		// --- 2. Launch one application, then open the Agents window in it ------
		// Launch through scripts/code.sh (the proven dev path); it `exec`s the
		// Electron binary, so the spawned pid is the application itself.
		// `--agents` alone would open *only* the Agents window, so the Agents
		// window is opened by a second CLI invocation routed to the same
		// instance through the single-instance channel (same user-data-dir).
		const debugPort = 9333 + Math.floor(Math.random() * 1000);
		const appEnv = {
			...process.env,
			VSCODE_SKIP_PRELAUNCH: '1',
			AGENTOS_RUNTIME_DESCRIPTOR: descriptorPath,
		};
		app = spawnLogged(codeLauncher, [
			'--user-data-dir', userDataDir,
			'--extensions-dir', extensionsDir,
			`--remote-debugging-port=${debugPort}`,
			'--disable-workspace-trust',
			'--skip-release-notes',
			workspaceDir,
		], { env: appEnv }, 'app');

		const listTargets = async () => (await (await fetch(`http://127.0.0.1:${debugPort}/json/list`)).json())
			.filter(target => target.type === 'page');
		await waitFor('IDE renderer', async () => {
			const pages = await listTargets();
			return pages.find(page => page.url.includes('workbench-dev.html')) ?? null;
		}, 120_000);

		// Open the Agents window in the same application instance.
		const agentsOpen = spawn(codeLauncher, [
			'--user-data-dir', userDataDir,
			'--extensions-dir', extensionsDir,
			'--agents',
		], { env: appEnv, stdio: 'ignore' });
		await new Promise(resolve => agentsOpen.once('exit', resolve));

		const targets = await waitFor('IDE and Sessions renderers', async () => {
			const pages = await listTargets();
			const ide = pages.find(page => page.url.includes('workbench-dev.html'));
			const sessions = pages.find(page => page.url.includes('sessions-dev.html'));
			return ide && sessions ? { ide, sessions } : null;
		}, 120_000);
		assert.ok(targets.ide.url !== targets.sessions.url, 'windows must use different renderer entrypoints');
		console.log('[e2e] ide target:', JSON.stringify({ url: targets.ide.url.slice(-60), ws: targets.ide.webSocketDebuggerUrl }));
		console.log('[e2e] sessions target:', JSON.stringify({ url: targets.sessions.url.slice(-60), ws: targets.sessions.webSocketDebuggerUrl }));

		async function connectPage(target, name) {
			try {
				return await CdpSession.connect(target.webSocketDebuggerUrl);
			} catch (error) {
				throw new Error(`CDP connect failed for ${name} (${target.url}): ${error.message}`);
			}
		}
		const ide = await connectPage(targets.ide, 'ide');
		const sessions = await connectPage(targets.sessions, 'sessions');
		try {
			// --- 3. Upstream workbench and parts, not a fake page ----------------
			await waitFor('IDE workbench parts', async () => {
				const ready = await ide.evaluate(`!!document.querySelector('.monaco-workbench') && document.querySelectorAll('[class*="part"]').length > 0`);
				return ready || null;
			}, 60_000);
			await waitFor('Sessions workbench parts', async () => {
				const ready = await sessions.evaluate(`!!document.querySelector('.monaco-workbench') && document.querySelectorAll('[class*="part"]').length > 0`);
				return ready || null;
			}, 60_000);

			// --- 4. Runtime tasks render in the Sessions window ------------------
			const bodyText = () => sessions.evaluate(`document.body ? document.body.innerText : ''`);
			await waitFor('runtime task labels in Sessions window', async () => {
				const text = await bodyText();
				return statements.every(statement => text.includes(statement)) || null;
			}, 90_000);

			// --- 5. The bearer token must not exist in any renderer --------------
			for (const [name, cdp] of [['ide', ide], ['sessions', sessions]]) {
				const inDom = await cdp.evaluate(`document.documentElement.outerHTML.includes(${JSON.stringify(token)})`);
				assert.equal(inDom, false, `bearer leaked into ${name} DOM`);
				const inStorage = await cdp.evaluate(`Object.values(localStorage).join(' ').includes(${JSON.stringify(token)}) || Object.values(sessionStorage).join(' ').includes(${JSON.stringify(token)})`);
				assert.equal(inStorage, false, `bearer leaked into ${name} storage`);
				const inGlobals = await cdp.evaluate(`(() => {
					const token = ${JSON.stringify(token)};
					for (const key of Object.getOwnPropertyNames(globalThis)) {
						if (['window', 'self', 'globalThis', 'document', 'frames', 'top', 'parent'].includes(key)) continue;
						try {
							const value = globalThis[key];
							if (typeof value === 'string' && value.includes(token)) return key;
							if (typeof value === 'function') continue;
							if (value && typeof value === 'object' && JSON.stringify(value)?.includes(token)) return key;
						} catch { /* unreadable global */ }
					}
					return null;
				})()`);
				assert.equal(inGlobals, null, `bearer leaked into ${name} global: ${inGlobals}`);
			}
			for (const message of [...ide.consoleMessages, ...sessions.consoleMessages]) {
				assert.ok(!message.includes(token), `bearer leaked into renderer console: ${message.slice(0, 120)}`);
			}

			// --- 6. No mutation affordances for the read-only projection ---------
			const mutationControls = await sessions.evaluate(`(() => {
				const needles = ['send request', 'delete session', 'archive session', 'fork chat', 'approve'];
				const labels = [...document.querySelectorAll('[aria-label]')].map(el => el.getAttribute('aria-label').toLowerCase());
				const buttons = [...document.querySelectorAll('button, a')].map(el => (el.textContent || '').toLowerCase());
				return needles.filter(needle => labels.some(label => label.includes(needle)) || buttons.some(label => label.includes(needle)));
			})()`);
			assert.deepEqual([...mutationControls], []);

			// --- 7. Renderer lifecycle must not own the runtime ------------------
			await sessions.send('Page.enable');
			await sessions.send('Page.reload');
			await waitFor('Sessions renderer back after reload', async () => {
				const ready = await sessions.evaluate(`!!document.querySelector('.monaco-workbench')`).catch(() => false);
				return ready || null;
			}, 60_000);
			const afterReload = await fetch(`${base}/v1/tasks`, { headers: { Authorization: `Bearer ${token}` } });
			assert.equal(afterReload.status, 200, 'renderer reload must not terminate the runtime');
			await waitFor('runtime task labels after reload', async () => {
				const text = await bodyText();
				return statements.every(statement => text.includes(statement)) || null;
			}, 90_000);
		} finally {
			ide.close();
			sessions.close();
		}

		// --- 8. Application quit boundedly terminates the interactive runtime --
		const browserTargets = await (await fetch(`http://127.0.0.1:${debugPort}/json/version`)).json();
		const browser = await CdpSession.connect(browserTargets.webSocketDebuggerUrl, { enableRuntime: false });
		// The browser socket drops as the application quits; a closed socket is success here.
		await browser.send('Browser.close').catch(() => { });
		await waitFor('application exit', () => app.exitCode !== null || null, 30_000);
		await waitFor('interactive runtime exit after application quit', () => {
			const alive = spawnSync('kill', ['-0', String(descriptor.pid)]).status === 0;
			return alive ? null : true;
		}, 30_000);
	} finally {
		if (app && app.exitCode === null) {
			app.kill('SIGKILL');
		}
		if (runtime && runtime.exitCode === null) {
			runtime.kill('SIGKILL');
		}
		await rm(tmp, { recursive: true, force: true });
	}
});
