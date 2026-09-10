import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
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
