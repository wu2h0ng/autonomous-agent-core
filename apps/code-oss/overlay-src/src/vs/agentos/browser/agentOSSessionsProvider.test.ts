/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Agent OS contributors. All rights reserved.
 *  Licensed under the MIT License. See License.txt in the project root for license information.
 *--------------------------------------------------------------------------------------------*/

import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { stripTypeScriptTypes } from 'node:module';
import { test } from 'node:test';
import { runInNewContext } from 'node:vm';

/**
 * Contract tests for the provider's pure helpers. The full behavioral suite
 * (projection diffing, read-only rejection, fail-closed refresh) lives in
 * `apps/code-oss/tests/agent-os-sessions-provider.test.mjs`.
 */
async function loadHelpers() {
	const url = new URL('./agentOSSessionsProvider.ts', import.meta.url);
	const text = await readFile(url, 'utf8');
	const stripped = stripTypeScriptTypes(text)
		.replace(/^import .*;\s*$/gm, '')
		.replace(/^export /gm, '')
		+ '\nglobalThis.__exports = { agentOSTaskResource, projectSessionStatus, AGENT_OS_READ_ONLY_MESSAGE };';
	const sandbox = {
		Emitter: class { },
		Event: { none: () => () => ({ dispose() { } }) },
		Disposable: class { _register(d: unknown) { return d; } },
		observableValue: (_name: string, initial: unknown) => ({ value: initial, get() { return this.value; }, set(v: unknown) { this.value = v; } }),
		constObservable: (value: unknown) => ({ get: () => value }),
		URI: { from: ({ scheme, path }: { scheme: string; path: string }) => ({ scheme, path, toString: () => `${scheme}:${path}` }) },
		Codicon: { tasklist: { id: 'tasklist' } },
		localize: (_key: string, value: string) => value,
		toSessionId: (providerId: string, resource: { toString(): string }) => `${providerId}:${resource.toString()}`,
		ChatOriginKind: { Tool: 'tool', User: 'user', Fork: 'fork', SideChat: 'sideChat' },
		ChatInteractivity: { Full: 'full', ReadOnly: 'read-only', Hidden: 'hidden' },
		SessionStatus: { Untitled: 0, InProgress: 1, NeedsInput: 2, Completed: 3, Error: 4 },
		SessionTypeAuthRequirement: { None: 'none', GitHub: 'github', Unusable: 'unusable' },
	};
	runInNewContext(stripped, sandbox);
	return (sandbox as unknown as {
		__exports: {
			agentOSTaskResource(taskId: string): { scheme: string; path: string; toString(): string };
			projectSessionStatus(task: { taskId: string; status: string | null; statement: string; runStatus: string | null; sequence: number }): number;
			AGENT_OS_READ_ONLY_MESSAGE: string;
		};
	}).__exports;
}

test('task resources use the agentos-task scheme with encoded ids', async () => {
	const { agentOSTaskResource } = await loadHelpers();
	const resource = agentOSTaskResource('task:1');
	assert.equal(resource.scheme, 'agentos-task');
	assert.equal(resource.path, '/task%3A1');
	assert.equal(resource.toString(), 'agentos-task:/task%3A1');
});

test('status projection covers the runtime enums and fails closed', async () => {
	const { projectSessionStatus } = await loadHelpers();
	const task = (status: string | null, runStatus: string | null) => ({ taskId: 't', status, statement: 's', runStatus, sequence: 0 });
	assert.equal(projectSessionStatus(task('RUNNING', null)), 1);
	assert.equal(projectSessionStatus(task(null, 'WAITING_APPROVAL')), 2);
	assert.equal(projectSessionStatus(task('COMPLETED', 'SUCCEEDED')), 3);
	assert.equal(projectSessionStatus(task('FAILED', null)), 4);
	assert.equal(projectSessionStatus(task('CANCELLED', null)), 4);
	assert.equal(projectSessionStatus(task('DRAFT', null)), 1); // never Untitled: Untitled opens the write composer
	assert.equal(projectSessionStatus(task(null, null)), 1);
	assert.throws(() => projectSessionStatus(task('BOGUS', null)), /Unknown Agent OS task status/);
});
