import assert from 'node:assert/strict';
import { spawn, spawnSync } from 'node:child_process';
import { createServer } from 'node:http';
import { mkdtemp, mkdir, readFile, rm, writeFile } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { test } from 'node:test';
import { overlayRoot, upstreamRoot } from '../scripts/paths.mjs';

// End-to-end oracle for Slice 2: selecting a projected runtime task in the
// Sessions window opens its whitelist task detail and trajectory as a
// read-only transcript — ordered event entries, no write controls, and no
// bearer or over-rich task_json keys anywhere in the renderer.
//
// Gap-annotation rendering is unit-covered only (tests/agent-os-sessions-provider.test.mjs):
// the real runtime emits continuous per-run sequences, so no genuine gap can
// be produced over HTTP without mutating contracts.

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

/** Loopback stub implementing just enough of the OpenAI chat-completions API. */
async function startStubProvider() {
	const server = createServer((req, res) => {
		if (req.method === 'POST' && req.url === '/chat/completions') {
			const body = JSON.stringify({
				id: 'chatcmpl-e2e-s2',
				object: 'chat.completion',
				created: 0,
				model: 'e2e-stub',
				choices: [{
					index: 0,
					message: {
						role: 'assistant',
						content: null,
						tool_calls: [{
							id: 'call_e2e_s2_1',
							type: 'function',
							function: {
								name: 'workspace.apply_patch',
								arguments: JSON.stringify({ path: 'fixture.txt', content: 'after\n' }),
							},
						}],
					},
					finish_reason: 'tool_calls',
				}],
				usage: { prompt_tokens: 1, completion_tokens: 1, total_tokens: 2 },
			});
			res.writeHead(200, { 'Content-Type': 'application/json' });
			res.end(body);
			return;
		}
		res.writeHead(404);
		res.end();
	});
	await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
	return server;
}

test('dual workbench slice 2: task detail and read-only trajectory transcript', { timeout: 420_000 }, async () => {
	assert.ok(existsSync(venvPython), `python venv missing: ${venvPython}`);
	assert.ok(existsSync(electronBinary), `electron build missing: ${electronBinary}`);

	const tmp = await mkdtemp(path.join(os.tmpdir(), 'agent-os-e2e-s2-'));
	const descriptorPath = path.join(tmp, 'runtime.json');
	const workspaceDir = path.join(tmp, 'workspace');
	const userDataDir = path.join(tmp, 'user-data');
	const extensionsDir = path.join(tmp, 'extensions');
	await mkdir(workspaceDir, { recursive: true });
	await mkdir(path.join(userDataDir, 'User'), { recursive: true });
	await writeFile(path.join(workspaceDir, 'README.md'), '# e2e workspace\n');
	await writeFile(path.join(workspaceDir, 'fixture.txt'), 'before\n');
	await writeFile(path.join(userDataDir, 'User', 'settings.json'), JSON.stringify({
		'chat.agentHost.allowSignedOutWhenUsable': true,
		'security.workspace.trust.enabled': false,
		'telemetry.telemetryLevel': 'off',
		'update.mode': 'none',
	}));

	let runtime;
	let app;
	let stubProvider;
	try {
		// --- 1. Real runtime, stub provider configured, one run-bearing task ---
		stubProvider = await startStubProvider();
		const stubPort = stubProvider.address().port;

		runtime = spawnLogged(venvPython, [
			'-m', 'apps.runtime_daemon',
			'--database', path.join(tmp, 'runtime.sqlite3'),
			'--workspace', workspaceDir,
			'--descriptor', descriptorPath,
			'--port', '0',
		], {
			cwd: repoRoot,
			env: { ...process.env, PYTHONPATH: pythonPath },
		}, 'runtime-s2');
		await waitFor('runtime descriptor', () => existsSync(descriptorPath) || null, 20_000);
		const descriptor = JSON.parse(await readFile(descriptorPath, 'utf8'));
		const token = descriptor.bearer_token;
		const base = `http://127.0.0.1:${descriptor.port}`;

		const call = async (method, route, body) => {
			const response = await fetch(`${base}${route}`, {
				method,
				headers: {
					'Authorization': `Bearer ${token}`,
					...(body !== undefined ? { 'Content-Type': 'application/json' } : {}),
				},
				...(body !== undefined ? { body: JSON.stringify(body) } : {}),
			});
			const text = await response.text();
			let parsed;
			try {
				parsed = JSON.parse(text);
			} catch {
				parsed = text;
			}
			return { status: response.status, body: parsed };
		};

		const configured = await call('POST', '/v1/provider', {
			base_url: `http://127.0.0.1:${stubPort}`,
			model: 'e2e-stub',
			api_key: 'e2e-key',
			temperature: 0,
		});
		assert.equal(configured.status, 200, `provider configuration failed: ${JSON.stringify(configured.body)}`);
		assert.equal(configured.body.connection_test, 'PASS');

		const NOW = new Date().toISOString();
		const runStatement = 'Run the slice two transcript task';
		const created = await call('POST', '/v1/tasks', {
			goal_id: 'goal:e2e:slice2',
			tenant_id: 'tenant:local',
			workspace_id: 'workspace:local',
			created_by: 'user:local',
			created_at: NOW,
			statement: runStatement,
		});
		assert.equal(created.status, 201, `task seeding failed: ${created.status} ${JSON.stringify(created.body)}`);
		const taskId = created.body.task_id;

		const committed = await call('POST', `/v1/tasks/${taskId}:commit`, {
			commitment: {
				commitment_id: 'commitment:e2e:slice2',
				task_id: taskId,
				goal_id: 'goal:e2e:slice2',
				tenant_id: 'tenant:local',
				workspace_id: 'workspace:local',
				accepted_by: 'user:local',
				accepted_at: NOW,
				deliverables: ['slice two transcript'],
				acceptance_criteria: ['run recorded'],
				authority_scopes: ['workspace:read', 'task.configuration.snapshot'],
				budget: { max_cost_usd: '1', max_duration_seconds: 300, max_provider_tokens: 1000, max_tool_calls: 10 },
				risk_tier: 1,
				exit_conditions: ['done'],
				expires_at: new Date(Date.now() + 86_400_000).toISOString(),
			},
			workflow: {
				workflow_id: 'workflow:e2e:slice2',
				version: 1,
				tenant_id: 'tenant:local',
				workspace_id: 'workspace:local',
				created_by: 'user:local',
				created_at: NOW,
				policy_version: 'policy-1',
				evaluator_refs: ['evaluator:none:1'],
				nodes: [
					{ node_id: 'read', kind: 'tool', capability: 'workspace.read', idempotency: 'idempotent' },
					{ node_id: 'provider', kind: 'provider', capability: 'provider.chat' },
					{ node_id: 'evaluate', kind: 'evaluation' },
					{ node_id: 'done', kind: 'terminal' },
				],
				edges: [
					{ source: 'read', target: 'provider' },
					{ source: 'provider', target: 'evaluate' },
					{ source: 'evaluate', target: 'done' },
				],
			},
			expected_outcome: {
				expected_outcome_id: 'expected:e2e:slice2',
				task_id: taskId,
				tenant_id: 'tenant:local',
				workspace_id: 'workspace:local',
				evaluator_type: 'none',
				evaluator_version: '1',
				evidence_requirements: ['none'],
				failure_semantics: ['missing'],
				threshold: 1,
				observation_window_seconds: 60,
				frozen_at: NOW,
			},
		});
		assert.equal(committed.status, 200, `commit failed: ${committed.status} ${JSON.stringify(committed.body)}`);

		const sealed = await call('POST', `/v1/tasks/${taskId}/configuration-snapshots:seal`, {});
		assert.equal(sealed.status, 201, `seal failed: ${sealed.status} ${JSON.stringify(sealed.body)}`);

		const run = await call('POST', `/v1/tasks/${taskId}/run`, {
			target_path: 'fixture.txt',
			prompt: 'e2e slice two prompt',
			configuration_snapshot_id: sealed.body.snapshot_id,
		});
		assert.equal(run.status, 200, `run failed to start: ${run.status} ${JSON.stringify(run.body)}`);
		const runId = run.body.run?.run_id;
		assert.ok(runId, 'run must produce a run_id');

		// Ground truth for the transcript assertions.
		const trajectory = await call('GET', `/v1/tasks/${taskId}/runs/${runId}/trajectory`);
		assert.equal(trajectory.status, 200, `trajectory read failed: ${trajectory.status}`);
		const stepSequences = trajectory.body.steps.map(step => step.sequence);
		assert.ok(stepSequences.length >= 10, 'the e2e run must produce a substantive transcript');
		const firstEventType = trajectory.body.steps[0].event_type;
		const lastEventType = trajectory.body.steps[stepSequences.length - 1].event_type;
		console.log('[e2e] transcript ground truth:', JSON.stringify({
			steps: stepSequences.length, firstEventType, lastEventType,
			runStatus: run.body.run.status,
		}));

		const draftStatement = 'Draft the slice two notes';
		const draftCreated = await call('POST', '/v1/tasks', {
			goal_id: 'goal:e2e:slice2:draft',
			tenant_id: 'tenant:local',
			workspace_id: 'workspace:local',
			created_by: 'user:local',
			created_at: new Date().toISOString(),
			statement: draftStatement,
		});
		assert.equal(draftCreated.status, 201, `draft task seeding failed: ${draftCreated.status}`);

		// --- 2. Launch one application, then open the Agents window in it ------
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
		], { env: appEnv }, 'app-s2');

		const listTargets = async () => (await (await fetch(`http://127.0.0.1:${debugPort}/json/list`)).json())
			.filter(target => target.type === 'page');
		await waitFor('IDE renderer', async () => {
			const pages = await listTargets();
			return pages.find(page => page.url.includes('workbench-dev.html')) ?? null;
		}, 120_000);

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
		const ide = await CdpSession.connect(targets.ide.webSocketDebuggerUrl);
		const sessions = await CdpSession.connect(targets.sessions.webSocketDebuggerUrl);
		try {
			await waitFor('Sessions workbench parts', async () => {
				const ready = await sessions.evaluate(`!!document.querySelector('.monaco-workbench') && document.querySelectorAll('[class*="part"]').length > 0`);
				return ready || null;
			}, 60_000);

			// The sessions welcome sign-in gate appears on a flaky schedule and
			// swallows pointer events; dismiss it before driving the UI.
			const dismissSignInGate = async cdp => {
				await cdp.evaluate(`(() => {
					const clickables = [...document.querySelectorAll('a, button, [role="button"]')];
					const skip = clickables.find(el => /continue without signing in/i.test((el.textContent || '').trim()));
					if (skip && skip.offsetParent !== null) {
						skip.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
						skip.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
						skip.click();
					}
					for (const dialog of [...document.querySelectorAll('.monaco-dialog-box, .modal, [role="dialog"]')]) {
						const close = dialog.querySelector('.codicon-close, [aria-label*="Close" i], button.close');
						if (close) close.click();
					}
					document.body.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', code: 'Escape', bubbles: true, cancelable: true }));
				})()`);
			};
			await dismissSignInGate(ide);
			await dismissSignInGate(sessions);

			const bodyText = () => sessions.evaluate(`document.body ? document.body.innerText : ''`);
			await waitFor('runtime task labels in Sessions window', async () => {
				const text = await bodyText();
				return text.includes(runStatement) && text.includes(draftStatement) ? true : null;
			}, 90_000);

			// --- 3. Select the run-bearing task: detail + transcript render ------
			await dismissSignInGate(sessions);
			const clicked = await waitFor('run-bearing task row clickable', async () => {
				const result = await sessions.evaluate(`(() => {
					const rows = [...document.querySelectorAll('.monaco-list-row, [role="listitem"], [role="treeitem"]')];
					const row = rows.find(el => el.textContent && el.textContent.includes(${JSON.stringify(runStatement)}));
					if (!row || row.offsetParent === null) return null;
					row.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
					row.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
					row.click();
					return row.className;
				})()`);
				return result || null;
			}, 30_000);
			console.log('[e2e] clicked session row:', clicked);

			await waitFor('transcript renders the trajectory in order', async () => {
				await dismissSignInGate(sessions);
				const text = await bodyText();
				// Request turn: the task statement heads the transcript.
				if (!text.includes(runStatement)) {
					return null;
				}
				// Every trajectory step renders exactly one seq annotation.
				const seqCount = (text.match(/seq #/g) ?? []).length;
				if (seqCount !== stepSequences.length) {
					return null;
				}
				// Order: the first event type appears before the last one.
				const firstAt = text.indexOf(firstEventType);
				const lastAt = text.lastIndexOf(lastEventType);
				if (firstAt < 0 || lastAt <= firstAt) {
					return null;
				}
				return true;
			}, 60_000);

			// --- 4. The transcript must not carry over-rich task_json keys -------
			const transcriptText = await bodyText();
			for (const forbidden of ['proposed_action', 'provider_usage', 'lease_fence', 'bearer_token', 'workflow_digest', 'tenant_id']) {
				assert.equal(transcriptText.includes(forbidden), false, `over-rich key leaked into the transcript: ${forbidden}`);
			}
			// A continuous run renders no gap annotation (gap rendering itself is
			// unit-covered; see the file header).
			assert.equal(/not part of this run/.test(transcriptText), false, 'continuous run must not show a gap annotation');

			// --- 5. A task without a run shows the detail and the no-run note ---
			// Click exactly once: re-clicking an already-active session opens a
			// NEW chat composer instead of the transcript. The sign-in gate is
			// dismissed inside the wait loop only.
			await sessions.evaluate(`(() => {
				const rows = [...document.querySelectorAll('.monaco-list-row, [role="listitem"], [role="treeitem"]')];
				const row = rows.find(el => el.textContent && el.textContent.includes(${JSON.stringify(draftStatement)}));
				if (row && row.offsetParent !== null) {
					row.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
					row.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
					row.click();
				}
			})()`);
			try {
				await waitFor('no-run note for the draft task', async () => {
					await dismissSignInGate(sessions);
					const text = await bodyText();
					return /No run has been recorded/.test(text) || null;
				}, 90_000);
			} catch (error) {
				const text = await bodyText();
				console.log('[e2e] draft selection diagnostics, body text tail:', JSON.stringify(text.slice(-3000)));
				const surface = await sessions.evaluate(`(() => {
					const textareas = [...document.querySelectorAll('textarea')].map(el => ({
						placeholder: el.placeholder, disabled: el.disabled, visible: el.offsetParent !== null,
					}));
					const composer = [...document.querySelectorAll('[class*="chat"], [class*="composer"], [class*="new-chat"]')]
						.filter(el => el.offsetParent !== null)
						.slice(0, 12)
						.map(el => el.className.split(' ').slice(0, 3).join('.'));
					const readOnlyBanner = document.body.innerText.includes('This chat is read-only');
					return { textareas, composer, readOnlyBanner };
				})()`);
				console.log('[e2e] draft selection surface:', JSON.stringify(surface));
				console.log('[e2e] draft selection diagnostics, console messages:', JSON.stringify(sessions.consoleMessages.slice(-15)));
				throw error;
			}

			// --- 6. Bearer and write controls stay absent -------------------------
			for (const [name, cdp] of [['ide', ide], ['sessions', sessions]]) {
				const inDom = await cdp.evaluate(`document.documentElement.outerHTML.includes(${JSON.stringify(token)})`);
				assert.equal(inDom, false, `bearer leaked into ${name} DOM`);
				const inStorage = await cdp.evaluate(`Object.values(localStorage).join(' ').includes(${JSON.stringify(token)}) || Object.values(sessionStorage).join(' ').includes(${JSON.stringify(token)})`);
				assert.equal(inStorage, false, `bearer leaked into ${name} storage`);
			}
			for (const message of [...ide.consoleMessages, ...sessions.consoleMessages]) {
				assert.ok(!message.includes(token), `bearer leaked into renderer console: ${message.slice(0, 120)}`);
			}
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
				return text.includes(runStatement) && text.includes(draftStatement) ? true : null;
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
		if (stubProvider) {
			stubProvider.close();
		}
		await rm(tmp, { recursive: true, force: true });
	}
});
