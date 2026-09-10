import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { stripTypeScriptTypes } from 'node:module';
import { test } from 'node:test';
import { runInNewContext } from 'node:vm';
import path from 'node:path';
import { upstreamRoot } from '../scripts/paths.mjs';

const source = relative => readFile(path.join(upstreamRoot, relative), 'utf8');

// The provider imports real vs/ workbench modules (observables, URI, sessions
// contracts). Tests double exactly those imports and execute the real provider
// code, so projection, diffing and read-only rejection logic run unmodified.
async function loadProviderModule() {
	const text = await source('src/vs/agentos/browser/agentOSSessionsProvider.ts');
	const stripped = stripTypeScriptTypes(text)
		.replace(/^import .*;\s*$/gm, '')
		.replace(/^export /gm, '')
		+ '\nglobalThis.__exports = { AgentOSSessionsProvider, AgentOSReadOnlyError, agentOSTaskResource, projectSessionStatus, AGENT_OS_READ_ONLY_MESSAGE };';

	class Emitter {
		constructor() { this.listeners = new Set(); }
		get event() {
			return listener => {
				this.listeners.add(listener);
				return { dispose: () => this.listeners.delete(listener) };
			};
		}
		fire(event) { for (const listener of [...this.listeners]) listener(event); }
	}
	class Disposable {
		_register(disposable) { return disposable; }
		dispose() { }
	}
	const observableValue = (_name, initial) => {
		const listeners = new Set();
		return {
			value: initial,
			get() { return this.value; },
			set(next) { this.value = next; for (const listener of [...listeners]) listener(next); },
		};
	};
	const constObservable = value => ({ get: () => value });
	const sandbox = {
		Emitter,
		Event: { none: () => () => ({ dispose() { } }) },
		Disposable,
		observableValue,
		constObservable,
		URI: {
			from: ({ scheme, path }) => ({ scheme, path, toString: () => `${scheme}:${path}` }),
		},
		Codicon: { tasklist: { id: 'tasklist' } },
		localize: (_key, value) => value,
		toSessionId: (providerId, resource) => `${providerId}:${resource.toString()}`,
		ChatOriginKind: { Tool: 'tool', User: 'user', Fork: 'fork', SideChat: 'sideChat' },
		ChatInteractivity: { Full: 'full', ReadOnly: 'read-only', Hidden: 'hidden' },
		SessionStatus: { Untitled: 0, InProgress: 1, NeedsInput: 2, Completed: 3, Error: 4 },
		SessionTypeAuthRequirement: { None: 'none', GitHub: 'github', Unusable: 'unusable' },
	};
	runInNewContext(stripped, sandbox);
	return sandbox.__exports;
}

function catalog(tasks) {
	return { listTasks: async () => ({ tasks, fetchedAt: 1000 }) };
}

function failingCatalog(error) {
	return { listTasks: async () => { throw error; } };
}

function task(taskId, overrides = {}) {
	return { taskId, status: 'RUNNING', statement: `statement of ${taskId}`, runStatus: 'RUNNING', sequence: 1, ...overrides };
}

test('provider identity, capability flags and empty initial catalog', async () => {
	const { AgentOSSessionsProvider } = await loadProviderModule();
	const provider = new AgentOSSessionsProvider(catalog([]));
	assert.equal(provider.id, 'agent-os-runtime');
	assert.equal(typeof provider.label, 'string');
	assert.equal(provider.supportsQuickChats, false);
	assert.deepEqual([...provider.browseActions], []);
	assert.equal(provider.automations, undefined);
	assert.deepEqual([...provider.getSessions()], []);
	assert.equal(provider.resolveWorkspace(), undefined);
	assert.deepEqual([...provider.getSessionTypes()], []);
	assert.equal(provider.lastError.get(), undefined);
});

test('refresh projects runtime tasks into stable read-only sessions', async () => {
	const { AgentOSSessionsProvider, SessionStatusDouble } = await loadProviderModule();
	const provider = new AgentOSSessionsProvider(catalog([task('task:1', { statement: 'Build the workbench' })]));
	const events = [];
	provider.onDidChangeSessions(event => events.push(event));
	await provider.refresh();
	assert.equal(events.length, 1);
	assert.equal(events[0].added.length, 1);
	assert.deepEqual([...events[0].removed], []);
	const session = provider.getSessions()[0];
	assert.equal(session.providerId, 'agent-os-runtime');
	assert.equal(session.resource.scheme, 'agentos-task');
	assert.equal(session.resource.path, '/task%3A1');
	assert.equal(session.sessionId, 'agent-os-runtime:agentos-task:/task%3A1');
	assert.equal(session.title.get(), 'Build the workbench');
	assert.equal(session.status.get(), 1 /* SessionStatus.InProgress */);
	const chat = session.mainChat.get();
	assert.equal(chat.interactivity.get(), 'read-only');
	assert.equal(chat.origin.kind, 'user');
	assert.equal(chat.capabilities.get().canRename, false);
	assert.equal(chat.capabilities.get().canDelete, false);
	assert.equal(session.capabilities.get().supportsMultipleChats, false);
	assert.equal(session.capabilities.get().supportsFork ?? false, false);
	assert.equal(session.capabilities.get().supportsRename ?? false, false);
	assert.equal(session.capabilities.get().supportsDelete ?? false, false);
});

test('statement and status updates keep the session facade and fire changed', async () => {
	const { AgentOSSessionsProvider } = await loadProviderModule();
	const backing = { tasks: [task('task:1')], fetchedAt: 1 };
	const provider = new AgentOSSessionsProvider({ listTasks: async () => backing });
	await provider.refresh();
	const before = provider.getSessions()[0];
	const events = [];
	provider.onDidChangeSessions(event => events.push(event));
	backing.tasks = [task('task:1', { statement: 'Ship it', runStatus: 'WAITING_APPROVAL' })];
	await provider.refresh();
	assert.equal(events.length, 1);
	assert.deepEqual([...events[0].added], []);
	assert.deepEqual([...events[0].removed], []);
	assert.equal(events[0].changed.length, 1);
	const after = provider.getSessions()[0];
	assert.equal(after, before);
	assert.equal(after.title.get(), 'Ship it');
	assert.equal(after.status.get(), 2 /* SessionStatus.NeedsInput */);
});

test('removal emits removed and keeps remaining sessions stable', async () => {
	const { AgentOSSessionsProvider } = await loadProviderModule();
	const backing = { tasks: [task('task:1'), task('task:2', { sequence: 2 })], fetchedAt: 1 };
	const provider = new AgentOSSessionsProvider({ listTasks: async () => backing });
	await provider.refresh();
	const survivor = provider.getSessions().find(session => session.resource.path === '/task%3A1');
	const events = [];
	provider.onDidChangeSessions(event => events.push(event));
	backing.tasks = [task('task:1')];
	await provider.refresh();
	assert.equal(events.length, 1);
	assert.equal(events[0].removed.length, 1);
	assert.deepEqual([...events[0].added], []);
	assert.equal(provider.getSessions().length, 1);
	assert.equal(provider.getSessions()[0], survivor);
});

test('duplicate task ids and unknown statuses fail closed without touching state', async () => {
	const { AgentOSSessionsProvider } = await loadProviderModule();
	const backing = { tasks: [task('task:1')], fetchedAt: 1 };
	const provider = new AgentOSSessionsProvider({ listTasks: async () => backing });
	await provider.refresh();
	const stable = provider.getSessions();
	for (const bad of [
		[task('task:1'), task('task:1', { sequence: 9 })],
		[task('task:1', { runStatus: 'TOTALLY_UNKNOWN' })],
	]) {
		const events = [];
		const listener = provider.onDidChangeSessions(event => events.push(event));
		backing.tasks = bad;
		await provider.refresh();
		listener.dispose();
		assert.equal(provider.getSessions().length, stable.length);
		assert.equal(provider.getSessions()[0], stable[0]);
		assert.ok(provider.lastError.get() !== undefined && provider.lastError.get() !== null);
		assert.deepEqual(events, []);
	}
});

test('an offline runtime keeps prior sessions and records the error', async () => {
	const { AgentOSSessionsProvider } = await loadProviderModule();
	const provider = new AgentOSSessionsProvider(catalog([task('task:1')]));
	await provider.refresh();
	provider.catalog = failingCatalog(new Error('descriptor missing'));
	await provider.refresh();
	assert.equal(provider.getSessions().length, 1);
	assert.match(String(provider.lastError.get()), /descriptor missing/);
});

test('every mutation entry point rejects with the typed read-only error', async () => {
	const { AgentOSSessionsProvider, AgentOSReadOnlyError, AGENT_OS_READ_ONLY_MESSAGE } = await loadProviderModule();
	const provider = new AgentOSSessionsProvider(catalog([task('task:1')]));
	await provider.refresh();
	const session = provider.getSessions()[0];
	const chat = session.mainChat.get();
	const syncThrowers = [
		() => provider.createNewSession({}, 'agent-os-runtime-task'),
		() => provider.createQuickChat('agent-os-runtime-task'),
		() => provider.deleteNewSession('x'),
		() => provider.setModel(session.sessionId, chat.resource, 'm', 'chosen'),
	];
	for (const fn of syncThrowers) {
		assert.throws(fn, error => error instanceof AgentOSReadOnlyError && error.message === AGENT_OS_READ_ONLY_MESSAGE);
	}
	const asyncRejecters = [
		() => provider.renameChat(session.sessionId, chat.resource, 'x'),
		() => provider.renameSession(session.sessionId, 'x'),
		() => provider.archiveSession(session.sessionId),
		() => provider.unarchiveSession(session.sessionId),
		() => provider.setSessionReadState(session.sessionId, true),
		() => provider.deleteSession(session.sessionId),
		() => provider.deleteSessions([session.sessionId]),
		() => provider.deleteChat(session.sessionId, chat.resource),
		() => provider.createNewChat(session.sessionId),
		() => provider.forkChat(session.sessionId, chat.resource, 'turn'),
		() => provider.createSideChat(session.sessionId, chat.resource, 'turn'),
		() => provider.sendRequest(session.sessionId, chat.resource, { query: 'hi' }),
	];
	for (const fn of asyncRejecters) {
		await assert.rejects(fn(), error => error instanceof AgentOSReadOnlyError && error.message === AGENT_OS_READ_ONLY_MESSAGE);
	}
});

test('model picker contracts stay empty and hidden', async () => {
	const { AgentOSSessionsProvider } = await loadProviderModule();
	const provider = new AgentOSSessionsProvider(catalog([task('task:1')]));
	await provider.refresh();
	const snapshot = provider.getModelsSnapshot(provider.getSessions()[0].sessionId);
	assert.deepEqual([...snapshot.models], []);
	assert.equal(snapshot.desiredModelResolution.kind, 'notRequested');
	const options = provider.getModelPickerOptions(provider.getSessions()[0].sessionId);
	assert.equal(options.useGroupedModelPicker, false);
	assert.equal(options.showFeatured, false);
	assert.equal(options.showUnavailableFeatured, false);
	assert.equal(options.showManageModelsAction, false);
	assert.equal(options.showAutoModel, false);
});

test('provider contribution registers through the upstream provider registry seam', async () => {
	const [contribution, desktopMain] = await Promise.all([
		source('src/vs/agentos/browser/agentOSSessionsProvider.contribution.ts'),
		source('src/vs/sessions/sessions.desktop.main.ts'),
	]);
	assert.match(contribution, /registerWorkbenchContribution2\(/);
	assert.match(contribution, /sessionsProvidersService\.registerProvider\(provider\)/);
	assert.match(contribution, /ISessionsProvidersService/);
	assert.match(contribution, /IChatSessionsService/);
	assert.match(contribution, /registerChatSessionContentProvider\(AGENT_OS_TASK_SCHEME, transcript\)/);
	assert.match(desktopMain, /agentos\/browser\/agentOSSessionsProvider\.contribution\.js/);
});

// --- Slice 2 Task 3: task detail + trajectory transcript content provider ---

async function loadContentProviderModule() {
	const text = await source('src/vs/agentos/browser/agentOSTaskContentProvider.ts');
	const stripped = stripTypeScriptTypes(text)
		.replace(/^import .*;\s*$/gm, '')
		.replace(/^export /gm, '')
		+ '\nglobalThis.__exports = { AgentOSTaskContentProvider, agentOSTaskTranscript, parseAgentOSTaskResource, AGENT_OS_TRANSCRIPT_EVENT_LABELS };';

	class Disposable {
		_register(disposable) { return disposable; }
		dispose() { }
	}
	const sandbox = {
		Disposable,
		Emitter: class Emitter {
			constructor() { this.listeners = new Set(); }
			get event() {
				return listener => {
					this.listeners.add(listener);
					return { dispose: () => this.listeners.delete(listener) };
				};
			}
			fire(event) { for (const listener of [...this.listeners]) listener(event); }
		},
		Event: { None: Object.assign(() => ({ dispose() { } }), { none: true }) },
		constObservable: value => ({ get: () => value }),
		localize: (_key, value, ...args) => value.replace(/\{(\d+)\}/g, (_m, i) => String(args[Number(i)])),
		MarkdownString: class MarkdownString { constructor(value) { this.value = value; } },
		AGENT_OS_TASK_SCHEME: 'agentos-task',
	};
	runInNewContext(stripped, sandbox);
	return sandbox.__exports;
}

function taskResource(taskId) {
	return { scheme: 'agentos-task', path: `/${encodeURIComponent(taskId)}`, toString: () => `agentos-task:/${encodeURIComponent(taskId)}` };
}

function detail(overrides = {}) {
	return {
		taskId: 'task:1',
		status: 'COMPLETED',
		statement: 'Build the workbench',
		runId: 'run:9',
		runStatus: 'FAILED',
		runCreatedAt: '2026-09-10T12:00:00.000Z',
		sequence: 3,
		...overrides,
	};
}

function trajectory(steps, overrides = {}) {
	return {
		taskId: 'task:1',
		runId: 'run:9',
		sourceStreamLastSequence: 20,
		trajectoryDigest: 'digest:abc',
		steps,
		...overrides,
	};
}

function step(sequence, eventType, gapBefore = 0) {
	return { stepId: `step:${sequence}`, sequence, eventType, occurredAt: '2026-09-10T12:00:00.000Z', gapBefore };
}

function markdownOf(historyItem) {
	return historyItem.parts.map(part => part.content.value).join('\n');
}

test('selecting a task opens its read-only detail and trajectory transcript', async () => {
	const { AgentOSTaskContentProvider } = await loadContentProviderModule();
	const catalogApi = {
		getTaskDetail: async taskId => (assert.equal(taskId, 'task:1'), detail()),
		getTaskTrajectory: async (taskId, runId) => {
			assert.equal(taskId, 'task:1');
			assert.equal(runId, 'run:9');
			return trajectory([step(1, 'TASK_CREATED'), step(5, 'RUN_FAILED', 3)]);
		},
	};
	const content = new AgentOSTaskContentProvider(catalogApi, () => { });
	const session = await content.provideChatSessionContent(taskResource('task:1'));
	assert.equal(session.isReadOnly.get(), true);
	assert.equal(session.requestHandler, undefined, 'no write path may exist on the transcript session');
	assert.equal(session.history[0].type, 'request');
	assert.equal(session.history[0].prompt, 'Build the workbench');
	const responses = session.history.filter(item => item.type === 'response');
	// Two steps + one gap annotation.
	assert.equal(responses.length, 3);
	const texts = responses.map(markdownOf);
	assert.match(texts[0], /TASK_CREATED/);
	assert.match(texts[1], /3/);
	assert.match(texts[1], /not part of this run|gap/i);
	assert.match(texts[2], /RUN_FAILED/);
	// Sequence numbers stay visible so ordering is auditable.
	assert.match(texts[0], /#1|seq(?:uence)? 1/i);
	assert.match(texts[2], /#5|seq(?:uence)? 5/i);
});

test('a task without a run renders the detail and a no-run note only', async () => {
	const { AgentOSTaskContentProvider } = await loadContentProviderModule();
	let trajectoryCalled = false;
	const catalogApi = {
		getTaskDetail: async () => detail({ runId: null, runStatus: null, runCreatedAt: null, status: 'DRAFT' }),
		getTaskTrajectory: async () => { trajectoryCalled = true; },
	};
	const content = new AgentOSTaskContentProvider(catalogApi, () => { });
	const session = await content.provideChatSessionContent(taskResource('task:1'));
	assert.equal(trajectoryCalled, false);
	assert.equal(session.history[0].type, 'request');
	const responses = session.history.filter(item => item.type === 'response');
	assert.equal(responses.length, 1);
	assert.match(markdownOf(responses[0]), /no run/i);
});

test('transcript failures reject and surface on the sessions provider lastError', async () => {
	const { AgentOSSessionsProvider } = await loadProviderModule();
	const { AgentOSTaskContentProvider } = await loadContentProviderModule();
	const decodeError = new Error('Invalid Agent OS task catalog: steps[0].event_type is unknown: TOTALLY_UNKNOWN');
	const catalogApi = {
		listTasks: async () => ({ tasks: [], fetchedAt: 1 }),
		getTaskDetail: async () => detail(),
		getTaskTrajectory: async () => { throw decodeError; },
	};
	const sessionsProvider = new AgentOSSessionsProvider(catalogApi);
	// Wired exactly like the contribution: content errors land on the provider.
	const content = new AgentOSTaskContentProvider(catalogApi, error => sessionsProvider.reportContentError(error));
	await assert.rejects(() => content.provideChatSessionContent(taskResource('task:1')), /TOTALLY_UNKNOWN/);
	assert.match(String(sessionsProvider.lastError.get()), /TOTALLY_UNKNOWN/);
});

test('task resource parsing is fail-closed', async () => {
	const { parseAgentOSTaskResource } = await loadContentProviderModule();
	assert.equal(parseAgentOSTaskResource(taskResource('task:1')), 'task:1');
	assert.equal(parseAgentOSTaskResource(taskResource('run:abb1cba2-818c')), 'run:abb1cba2-818c');
	for (const bad of [
		{ scheme: 'file', path: '/task%3A1' },
		{ scheme: 'agentos-task', path: '' },
		{ scheme: 'agentos-task', path: '/' },
		{ scheme: 'agentos-task', path: '/a%2Fb' },
		{ scheme: 'agentos-task', path: '/%2E%2E' },
	]) {
		assert.throws(() => parseAgentOSTaskResource(bad), /agentos-task|task id/i);
	}
});

test('the transcript label whitelist totals the frozen event-type contract', async () => {
	const { AGENT_OS_TRANSCRIPT_EVENT_LABELS } = await loadContentProviderModule();
	const keys = Object.keys(AGENT_OS_TRANSCRIPT_EVENT_LABELS);
	assert.equal(keys.length, 42);
	for (const key of keys) {
		assert.match(AGENT_OS_TRANSCRIPT_EVENT_LABELS[key], /\S/);
	}
});
