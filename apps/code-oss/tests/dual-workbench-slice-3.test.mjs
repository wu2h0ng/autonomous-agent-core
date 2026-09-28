import assert from 'node:assert/strict';
import { spawn, spawnSync } from 'node:child_process';
import { createServer } from 'node:http';
import { mkdtemp, mkdir, readFile, rm, writeFile } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { test } from 'node:test';
import { overlayRoot } from '../scripts/paths.mjs';

// Slice 3 Task 1 — recipe probe (HTTP only, no Electron).
//
// Fixes the two-step approval recipe against the real runtime before any UI
// work: workflow with an `approval` node parks the run at WAITING_APPROVAL;
// `POST /v1/tasks/{id}/approval` records the decision WITHOUT resuming;
// `POST /v1/tasks/{id}/run` (configuration_snapshot_id only — exactly what the
// bridge's resumeTaskRun may send) resumes, and the approval node re-checks
// the recorded digest before dispatching the approved action.
//
// Falsifiable oracle for spec §12 (3): the digest on the approval card
// (task_json.proposed_action.action_digest) must equal the recorded
// approval's action_digest AND the executed action receipt's action_digest.

const repoRoot = path.resolve(overlayRoot, '../..');
const venvPython = process.env.AGENT_OS_E2E_PYTHON ?? path.resolve(repoRoot, '../../.venv/bin/python');
const contractsSrc = path.join(repoRoot, 'packages/contracts/src');
const osCoreSrc = path.join(repoRoot, 'packages/os_core/src');
const pythonPath = [contractsSrc, osCoreSrc, process.env.PYTHONPATH].filter(Boolean).join(path.delimiter);
const logsDir = path.join(repoRoot, '.agent_runs/dual-workbench-slice-1-20260909/e2e-logs');
const electronBinary = path.join(repoRoot, '.code-oss/upstream/.build/electron/Code - OSS.app/Contents/MacOS/Code - OSS');
const codeLauncher = path.join(repoRoot, '.code-oss/upstream/scripts/code.sh');

/** Minimal CDP client over the Node built-in WebSocket (same as slice 2). */
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
	throw new Error(`timed out waiting for ${label}${lastError ? ` (last error: ${lastError.message})` : ''}`);
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

/** Loopback stub implementing just enough of the OpenAI chat-completions API. */
async function startStubProvider() {
	const server = createServer((req, res) => {
		if (req.method === 'POST' && req.url === '/chat/completions') {
			const body = JSON.stringify({
				id: 'chatcmpl-e2e-s3',
				object: 'chat.completion',
				created: 0,
				model: 'e2e-stub',
				choices: [{
					index: 0,
					message: {
						role: 'assistant',
						content: null,
						tool_calls: [{
							id: 'call_e2e_s3_1',
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

test('dual workbench slice 3: two-step approval recipe probe', { timeout: 240_000 }, async () => {
	assert.ok(existsSync(venvPython), `python venv missing: ${venvPython}`);

	const tmp = await mkdtemp(path.join(os.tmpdir(), 'agent-os-e2e-s3-'));
	const descriptorPath = path.join(tmp, 'runtime.json');
	const workspaceDir = path.join(tmp, 'workspace');
	await mkdir(workspaceDir, { recursive: true });
	await writeFile(path.join(workspaceDir, 'README.md'), '# e2e workspace\n');
	await writeFile(path.join(workspaceDir, 'fixture.txt'), 'before\n');

	let runtime;
	let stubProvider;
	const probe = {};
	try {
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
		}, 'runtime-s3-probe');
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

		// Seed one approval-parking task per disposition scenario.
		const seedTask = async (label) => {
			const NOW = new Date().toISOString();
			const created = await call('POST', '/v1/tasks', {
				goal_id: `goal:e2e:slice3:${label}`,
				tenant_id: 'tenant:local',
				workspace_id: 'workspace:local',
				created_by: 'user:local',
				created_at: NOW,
				statement: `Slice three approval probe (${label})`,
			});
			assert.equal(created.status, 201, `task seeding failed: ${created.status} ${JSON.stringify(created.body)}`);
			const taskId = created.body.task_id;

			const committed = await call('POST', `/v1/tasks/${taskId}:commit`, {
				commitment: {
					commitment_id: `commitment:e2e:slice3:${label}`,
					task_id: taskId,
					goal_id: `goal:e2e:slice3:${label}`,
					tenant_id: 'tenant:local',
					workspace_id: 'workspace:local',
					accepted_by: 'user:local',
					accepted_at: NOW,
					deliverables: ['slice three approval'],
					acceptance_criteria: ['approval recorded'],
					authority_scopes: ['workspace:read', 'task.configuration.snapshot'],
					budget: { max_cost_usd: '1', max_duration_seconds: 300, max_provider_tokens: 1000, max_tool_calls: 10 },
					risk_tier: 1,
					exit_conditions: ['done'],
					expires_at: new Date(Date.now() + 86_400_000).toISOString(),
				},
				workflow: {
					workflow_id: `workflow:e2e:slice3:${label}`,
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
						{ node_id: 'approve', kind: 'approval' },
						{ node_id: 'apply', kind: 'tool', capability: 'workspace.apply_patch', idempotency: 'compensatable' },
						{ node_id: 'evaluate', kind: 'evaluation' },
						{ node_id: 'done', kind: 'terminal' },
					],
					edges: [
						{ source: 'read', target: 'provider' },
						{ source: 'provider', target: 'approve' },
						{ source: 'approve', target: 'apply' },
						{ source: 'apply', target: 'evaluate' },
						{ source: 'evaluate', target: 'done' },
					],
				},
				expected_outcome: {
					expected_outcome_id: `expected:e2e:slice3:${label}`,
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
				prompt: 'e2e slice three prompt',
				configuration_snapshot_id: sealed.body.snapshot_id,
			});
			assert.equal(run.status, 200, `run failed to start: ${run.status} ${JSON.stringify(run.body)}`);
			return { taskId, snapshotId: sealed.body.snapshot_id };
		};

		const eventTypes = (taskJson) => taskJson.events.map(event => event.event_type);
		const receiptFor = (taskJson) => {
			const receipts = [];
			for (const event of taskJson.events) {
				if (event.event_type !== 'ACTION_RECEIPT_RECORDED') {
					continue;
				}
				const receipt = event.payload?.receipt;
				if (receipt) {
					receipts.push(receipt);
				}
			}
			return receipts;
		};

		// --- Scenario A: APPROVE — park, decide, resume, execute ---------------
		const approved = await seedTask('approve');
		const parked = await call('GET', `/v1/tasks/${approved.taskId}`);
		assert.equal(parked.status, 200);
		assert.equal(parked.body.run?.status, 'WAITING_APPROVAL', `run must park at WAITING_APPROVAL, got ${parked.body.run?.status}: ${JSON.stringify(eventTypes(parked.body))}`);
		assert.ok(eventTypes(parked.body).includes('APPROVAL_REQUESTED'), 'parking must emit APPROVAL_REQUESTED');
		const cardDigest = parked.body.proposed_action?.action_digest;
		assert.ok(typeof cardDigest === 'string' && cardDigest.length === 64, 'approval card digest must be present on proposed_action');
		assert.equal(parked.body.proposed_action?.capability_id, 'workspace.apply_patch');

		// Capture real fixtures for the decoder contract tests (provider_status
		// carries no api_key — app.py:802-810; same capture policy as slice 2).
		const fixturesDir = path.join(repoRoot, 'apps', 'code-oss', 'tests', 'fixtures');
		await mkdir(fixturesDir, { recursive: true });
		await writeFile(path.join(fixturesDir, 'task-detail-waiting-approval.real.json'), JSON.stringify(parked.body, null, 2));

		// record_approval does NOT resume the run.
		const decided = await call('POST', `/v1/tasks/${approved.taskId}/approval`, {
			action_digest: cardDigest,
			disposition: 'APPROVE',
			reason: 'e2e slice three approval',
		});
		assert.equal(decided.status, 200, `approval failed: ${decided.status} ${JSON.stringify(decided.body)}`);
		assert.equal(decided.body.run?.status, 'WAITING_APPROVAL', 'recording the approval must not resume the run');
		const approvalDigest = decided.body.approval?.action_digest;
		assert.equal(approvalDigest, cardDigest, 'recorded approval digest must equal the card digest');
		await writeFile(path.join(fixturesDir, 'task-detail-approved.real.json'), JSON.stringify(decided.body, null, 2));

		// Resume with configuration_snapshot_id ONLY — the exact payload shape the
		// bridge's resumeTaskRun is allowed to send (no inputs, no lease recovery).
		const resumed = await call('POST', `/v1/tasks/${approved.taskId}/run`, {
			configuration_snapshot_id: approved.snapshotId,
		});
		assert.equal(resumed.status, 200, `resume failed: ${resumed.status} ${JSON.stringify(resumed.body)}`);
		const finalTypes = eventTypes(resumed.body);
		assert.ok(finalTypes.includes('RUN_RESUMED'), `resume must emit RUN_RESUMED, got ${JSON.stringify(finalTypes)}`);
		const receipts = receiptFor(resumed.body);
		const receipt = receipts.find(candidate => candidate.action_digest === cardDigest);
		assert.ok(receipt, `approved action must produce a matching ACTION_RECEIPT_RECORDED, got digests ${JSON.stringify(receipts.map(r => r.action_digest))} vs card ${cardDigest}`);
		probe.approve = {
			cardDigest,
			approvalDigest,
			receiptDigest: receipt.action_digest,
			finalRunStatus: resumed.body.run?.status,
			finalEvents: finalTypes,
		};

		// --- Scenario B: REJECT — no resume, no execution, run stays parked -----
		const rejected = await seedTask('reject');
		const parkedReject = await call('GET', `/v1/tasks/${rejected.taskId}`);
		assert.equal(parkedReject.body.run?.status, 'WAITING_APPROVAL');
		const rejectDigest = parkedReject.body.proposed_action?.action_digest;
		assert.ok(rejectDigest, 'reject scenario must also park with a proposed action');

		const rejectedDecision = await call('POST', `/v1/tasks/${rejected.taskId}/approval`, {
			action_digest: rejectDigest,
			disposition: 'REJECT',
			reason: 'e2e slice three rejection',
		});
		assert.equal(rejectedDecision.status, 200, `rejection failed: ${rejectedDecision.status} ${JSON.stringify(rejectedDecision.body)}`);
		assert.equal(rejectedDecision.body.approval?.disposition, 'REJECT');
		assert.equal(rejectedDecision.body.run?.status, 'WAITING_APPROVAL', 'rejected run must stay parked (termination belongs to slice 4)');
		assert.equal(
			receiptFor(rejectedDecision.body).some(candidate => candidate.action_digest === rejectDigest),
			false,
			'rejected action must never produce a receipt',
		);
		probe.reject = {
			cardDigest: rejectDigest,
			disposition: rejectedDecision.body.approval?.disposition,
			finalRunStatus: rejectedDecision.body.run?.status,
		};

		// --- Negative: wrong digest is refused ----------------------------------
		const wrongDigest = await call('POST', `/v1/tasks/${rejected.taskId}/approval`, {
			action_digest: '0'.repeat(64),
			disposition: 'APPROVE',
			reason: 'e2e slice three wrong digest',
		});
		assert.notEqual(wrongDigest.status, 200, 'a digest that does not bind the pending action must be refused');
		probe.negative = { wrongDigestStatus: wrongDigest.status };

		console.log('[e2e] slice 3 recipe probe:', JSON.stringify(probe, null, 2));
	} finally {
		if (runtime) {
			runtime.kill('SIGTERM');
		}
		if (stubProvider) {
			await new Promise(resolve => stubProvider.close(resolve));
		}
		await mkdir(logsDir, { recursive: true });
		await writeFile(path.join(logsDir, 'slice3-recipe-probe.json'), JSON.stringify(probe, null, 2));
		await rm(tmp, { recursive: true, force: true });
	}
});

// Slice 3 Task 5 — full e2e oracle: a real parked task renders the approval
// card in the Sessions window; clicking Approve (with a mandatory reason)
// submits through the bridge, resumes the run, and the card converges on the
// server-recorded decision. Reject never executes. No over-rich keys, no
// bearer, reload survives, quit terminates the runtime boundedly.

test('dual workbench slice 3: approval card decide flow end to end', { timeout: 420_000 }, async () => {
	assert.ok(existsSync(venvPython), `python venv missing: ${venvPython}`);
	assert.ok(existsSync(electronBinary), `electron build missing: ${electronBinary}`);

	const tmp = await mkdtemp(path.join(os.tmpdir(), 'agent-os-e2e-s3-ui-'));
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
		}, 'runtime-s3');
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
		assert.equal(configured.status, 200);

		const seedParkedTask = async (label, statement) => {
			const NOW = new Date().toISOString();
			const created = await call('POST', '/v1/tasks', {
				goal_id: `goal:e2e:slice3ui:${label}`,
				tenant_id: 'tenant:local',
				workspace_id: 'workspace:local',
				created_by: 'user:local',
				created_at: NOW,
				statement,
			});
			assert.equal(created.status, 201, `seeding failed: ${JSON.stringify(created.body)}`);
			const taskId = created.body.task_id;
			const committed = await call('POST', `/v1/tasks/${taskId}:commit`, {
				commitment: {
					commitment_id: `commitment:e2e:slice3ui:${label}`,
					task_id: taskId,
					goal_id: `goal:e2e:slice3ui:${label}`,
					tenant_id: 'tenant:local',
					workspace_id: 'workspace:local',
					accepted_by: 'user:local',
					accepted_at: NOW,
					deliverables: ['slice three approval ui'],
					acceptance_criteria: ['approval recorded'],
					authority_scopes: ['workspace:read', 'task.configuration.snapshot'],
					budget: { max_cost_usd: '1', max_duration_seconds: 300, max_provider_tokens: 1000, max_tool_calls: 10 },
					risk_tier: 1,
					exit_conditions: ['done'],
					expires_at: new Date(Date.now() + 86_400_000).toISOString(),
				},
				workflow: {
					workflow_id: `workflow:e2e:slice3ui:${label}`,
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
						{ node_id: 'approve', kind: 'approval' },
						{ node_id: 'apply', kind: 'tool', capability: 'workspace.apply_patch', idempotency: 'compensatable' },
						{ node_id: 'evaluate', kind: 'evaluation' },
						{ node_id: 'done', kind: 'terminal' },
					],
					edges: [
						{ source: 'read', target: 'provider' },
						{ source: 'provider', target: 'approve' },
						{ source: 'approve', target: 'apply' },
						{ source: 'apply', target: 'evaluate' },
						{ source: 'evaluate', target: 'done' },
					],
				},
				expected_outcome: {
					expected_outcome_id: `expected:e2e:slice3ui:${label}`,
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
			assert.equal(committed.status, 200, `commit failed: ${JSON.stringify(committed.body)}`);
			const sealed = await call('POST', `/v1/tasks/${taskId}/configuration-snapshots:seal`, {});
			assert.equal(sealed.status, 201);
			const run = await call('POST', `/v1/tasks/${taskId}/run`, {
				target_path: 'fixture.txt',
				prompt: 'e2e slice three ui prompt',
				configuration_snapshot_id: sealed.body.snapshot_id,
			});
			assert.equal(run.status, 200, `run failed: ${JSON.stringify(run.body)}`);
			assert.equal(run.body.run?.status, 'WAITING_APPROVAL', `run must park, got ${run.body.run?.status}`);
			const cardDigest = run.body.proposed_action?.action_digest;
			assert.ok(cardDigest, 'parked run must serve a proposed action digest');
			return { taskId, snapshotId: sealed.body.snapshot_id, cardDigest };
		};

		const approveStatement = 'Approve the slice three patch';
		const rejectStatement = 'Reject the slice three patch';
		const approveTask = await seedParkedTask('approve', approveStatement);
		// NOTE: the reject task is seeded only after the approve flow fully
		// completes. Two runs parked in the same workspace conflict on the
		// workspace work lease — the later park re-binds the lease, so resuming
		// the earlier run fails with "action/claim identity does not bind the
		// work lease". Sequential seeding matches the proven recipe probe;
		// concurrent parked approvals are a recorded server-side limitation,
		// not a Slice 3 UI concern.

		// --- Launch the application and open the Agents window ----------------
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
		], { env: appEnv }, 'app-s3');

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
			await waitFor('approve task label in Sessions window', async () => {
				const text = await bodyText();
				return text.includes(approveStatement) ? true : null;
			}, 90_000);

			const clickTaskRow = async (statement) => {
				await dismissSignInGate(sessions);
				return sessions.evaluate(`(() => {
					const rows = [...document.querySelectorAll('.monaco-list-row, [role="listitem"], [role="treeitem"]')];
					const row = rows.find(el => el.textContent && el.textContent.includes(${JSON.stringify(statement)}));
					if (!row || row.offsetParent === null) return null;
					row.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
					row.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
					row.click();
					return row.className;
				})()`);
			};

			// --- 1. The parked task renders the approval card -------------------
			await waitFor('approve task row clickable', () => clickTaskRow(approveStatement), 30_000);
			await waitFor('approval card renders', async () => {
				await dismissSignInGate(sessions);
				const text = await bodyText();
				if (!text.includes('Approval required')) {
					return null;
				}
				for (const expected of ['workspace.apply_patch', 'policy-1', 'user:local', approveTask.cardDigest.slice(0, 12), 'fixture.txt']) {
					if (!text.includes(expected)) {
						return null;
					}
				}
				return true;
			}, 60_000);

			// Command links must exist in the DOM with projection-bound args.
			// VS Code's markdown renderer keeps the real URI in data-href and
			// renders href="" on the anchor, so match on data-href.
			const linkHrefs = await sessions.evaluate(`[...document.querySelectorAll('a[data-href^="command:agentos.approval.decide"]')].map(a => a.getAttribute('data-href'))`);
			assert.equal(linkHrefs.length, 2, `approve and reject links must render, got ${JSON.stringify(linkHrefs)}`);
			for (const href of linkHrefs) {
				assert.ok(href.includes(encodeURIComponent(approveTask.cardDigest)), 'link must carry the exact card digest');
				assert.ok(href.includes(encodeURIComponent(approveTask.snapshotId)), 'link must carry the sealed snapshot id');
			}

			// --- 2. Approve: mandatory reason, decide + resume ------------------
			const clicked = await sessions.evaluate(`(() => {
				const links = [...document.querySelectorAll('a[data-href^="command:agentos.approval.decide"]')];
				const approve = links.find(a => decodeURIComponent(a.getAttribute('data-href')).includes('"APPROVE"'));
				if (!approve) return null;
				approve.click();
				return true;
			})()`);
			assert.equal(clicked, true, 'approve link must be clickable');
			await waitFor('reason input appears', async () => {
				const found = await sessions.evaluate(`(() => {
					const input = document.querySelector('.quick-input-widget input');
					return input && input.offsetParent !== null ? true : null;
				})()`);
				return found || null;
			}, 15_000);
			await sessions.evaluate(`(() => {
				const input = document.querySelector('.quick-input-widget input');
				const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
				setter.call(input, 'e2e approval via card');
				input.dispatchEvent(new Event('input', { bubbles: true }));
			})()`);
			await sleep(300);
			await sessions.evaluate(`(() => {
				const input = document.querySelector('.quick-input-widget input');
				for (const type of ['keydown', 'keypress', 'keyup']) {
					input.dispatchEvent(new KeyboardEvent(type, { key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true, cancelable: true }));
				}
			})()`);
			// Server truth: the run resumes and the approved action executes.
			await waitFor('approved run resumes and records the receipt', async () => {
				const detail = await call('GET', `/v1/tasks/${approveTask.taskId}`);
				const types = detail.body.events?.map(event => event.event_type) ?? [];
				if (!types.includes('APPROVAL_RECORDED') || !types.includes('RUN_RESUMED')) {
					return null;
				}
				const receipt = (detail.body.events ?? []).find(event => event.event_type === 'ACTION_RECEIPT_RECORDED'
					&& event.payload?.receipt?.action_digest === approveTask.cardDigest);
				return receipt ? detail.body : null;
			}, 60_000);

			// --- 3. The card converges on the recorded decision -----------------
			await waitFor('decision entry renders after re-selection', async () => {
				await clickTaskRow(approveStatement);
				await sleep(500);
				const text = await bodyText();
				return /Approved — awaiting governed execution|Decision recorded: approved/.test(text) ? true : null;
			}, 60_000);
			const convergedText = await bodyText();
			assert.ok(convergedText.includes(approveTask.cardDigest.slice(0, 12)), 'decision entry shows the same digest');

			// --- 4. Reject: no execution, run stays parked ----------------------
			const rejectTask = await seedParkedTask('reject', rejectStatement);
			await waitFor('reject task label appears in Sessions window', async () => {
				await dismissSignInGate(sessions);
				const text = await bodyText();
				return text.includes(rejectStatement) ? true : null;
			}, 60_000);
			await waitFor('reject task row clickable', () => clickTaskRow(rejectStatement), 30_000);
			await waitFor('reject card renders', async () => {
				const text = await bodyText();
				return text.includes('Approval required') && text.includes(rejectTask.cardDigest.slice(0, 12)) ? true : null;
			}, 60_000);
			const rejectClicked = await sessions.evaluate(`(() => {
				const links = [...document.querySelectorAll('a[data-href^="command:agentos.approval.decide"]')];
				const reject = links.find(a => decodeURIComponent(a.getAttribute('data-href')).includes('"REJECT"') && decodeURIComponent(a.getAttribute('data-href')).includes(${JSON.stringify(rejectTask.cardDigest)}));
				if (!reject) return null;
				reject.click();
				return true;
			})()`);
			assert.equal(rejectClicked, true, 'reject link must be clickable');
			await waitFor('reason input appears for reject', async () => {
				const found = await sessions.evaluate(`(() => {
					const input = document.querySelector('.quick-input-widget input');
					return input && input.offsetParent !== null ? true : null;
				})()`);
				return found || null;
			}, 15_000);
			await sessions.evaluate(`(() => {
				const input = document.querySelector('.quick-input-widget input');
				const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
				setter.call(input, 'e2e rejection via card');
				input.dispatchEvent(new Event('input', { bubbles: true }));
			})()`);
			await sleep(300);
			await sessions.evaluate(`(() => {
				const input = document.querySelector('.quick-input-widget input');
				for (const type of ['keydown', 'keypress', 'keyup']) {
					input.dispatchEvent(new KeyboardEvent(type, { key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true, cancelable: true }));
				}
			})()`);

			await waitFor('rejection recorded, run stays parked', async () => {
				const detail = await call('GET', `/v1/tasks/${rejectTask.taskId}`);
				if (detail.body.approval?.disposition !== 'REJECT') {
					return null;
				}
				return detail.body.run?.status === 'WAITING_APPROVAL' ? detail.body : null;
			}, 30_000);
			const rejectedDetail = await call('GET', `/v1/tasks/${rejectTask.taskId}`);
			const rejectedReceipt = (rejectedDetail.body.events ?? []).find(event => event.event_type === 'ACTION_RECEIPT_RECORDED'
				&& event.payload?.receipt?.action_digest === rejectTask.cardDigest);
			assert.equal(rejectedReceipt, undefined, 'a rejected action must never produce a receipt');

			await waitFor('reject decision entry renders after re-selection', async () => {
				await clickTaskRow(approveStatement);
				await sleep(500);
				await clickTaskRow(rejectStatement);
				await sleep(500);
				const text = await bodyText();
				return /Rejected — the action will not run/.test(text) ? true : null;
			}, 60_000);

			// --- 5. No over-rich keys, no bearer, anywhere in the renderer ------
			const pageText = await bodyText();
			for (const forbidden of ['proposed_action', 'provider_usage', 'lease_fence', 'bearer_token', 'tenant_id', 'arguments_json', 'observed_correction_epochs']) {
				assert.equal(pageText.includes(forbidden), false, `over-rich key leaked into the renderer: ${forbidden}`);
			}
			for (const [name, cdp] of [['ide', ide], ['sessions', sessions]]) {
				const inDom = await cdp.evaluate(`document.documentElement.outerHTML.includes(${JSON.stringify(token)})`);
				assert.equal(inDom, false, `bearer leaked into ${name} DOM`);
				const inStorage = await cdp.evaluate(`Object.values(localStorage).join(' ').includes(${JSON.stringify(token)}) || Object.values(sessionStorage).join(' ').includes(${JSON.stringify(token)})`);
				assert.equal(inStorage, false, `bearer leaked into ${name} storage`);
			}
			for (const message of [...ide.consoleMessages, ...sessions.consoleMessages]) {
				assert.ok(!message.includes(token), `bearer leaked into renderer console: ${message.slice(0, 120)}`);
			}

			// --- 6. Reload survival + bounded quit ------------------------------
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
				return text.includes(approveStatement) && text.includes(rejectStatement) ? true : null;
			}, 90_000);
		} finally {
			ide.close();
			sessions.close();
		}

		const browserTargets = await (await fetch(`http://127.0.0.1:${debugPort}/json/version`)).json();
		const browser = await CdpSession.connect(browserTargets.webSocketDebuggerUrl, { enableRuntime: false });
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
