/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Agent OS contributors. All rights reserved.
 *  Licensed under the MIT License. See License.txt in the project root for license information.
 *--------------------------------------------------------------------------------------------*/

import { Emitter, Event } from '../../base/common/event.js';
import { Disposable } from '../../base/common/lifecycle.js';
import { constObservable, IObservable, ISettableObservable, observableValue } from '../../base/common/observable.js';
import { Codicon } from '../../base/common/codicons.js';
import { ThemeIcon } from '../../base/common/themables.js';
import { URI } from '../../base/common/uri.js';
import { localize } from '../../nls.js';
import { ChatInteractivity, ChatOriginKind, IChat, ISession, ISessionType, ISessionWorkspace, SessionStatus, SessionTypeAuthRequirement, toSessionId } from '../../sessions/services/sessions/common/session.js';
import { IDeleteChatOptions, ISendRequestOptions, ISessionChangeEvent, ISessionModelPickerOptions, ISessionModelsSnapshot, ISessionsProvider, ISessionsProviderCreateSessionOptions } from '../../sessions/services/sessions/common/sessionsProvider.js';
import type { AgentOSTaskCatalogSnapshot, AgentOSTaskSummary } from '../common/runtimeTaskCatalog.js';
import type { IRuntimeTaskCatalogService } from '../common/runtimeTaskCatalogService.js';

export const AGENT_OS_PROVIDER_ID = 'agent-os-runtime';
export const AGENT_OS_SESSION_TYPE_ID = 'agent-os-runtime-task';
export const AGENT_OS_TASK_SCHEME = 'agentos-task';
export const AGENT_OS_READ_ONLY_MESSAGE = 'Agent OS Slice 1 is read-only';

/**
 * Typed rejection for every mutation path. Slice 1 is a read-only projection:
 * nothing in this provider may create, rename, delete, steer or otherwise
 * mutate runtime state. Consumers must see an explicit refusal, never a
 * silent no-op.
 */
export class AgentOSReadOnlyError extends Error {
	constructor() {
		super(AGENT_OS_READ_ONLY_MESSAGE);
		this.name = 'AgentOSReadOnlyError';
	}
}

function readOnly(): never {
	throw new AgentOSReadOnlyError();
}

/** Canonical task resource: `agentos-task:/<encoded-task-id>`. */
export function agentOSTaskResource(taskId: string): URI {
	return URI.from({ scheme: AGENT_OS_TASK_SCHEME, path: `/${encodeURIComponent(taskId)}` });
}

/**
 * Maps the runtime task/run status pair onto the upstream session status.
 * Fail closed on unknown values: misrepresenting runtime state is worse than
 * refusing the refresh.
 */
export function projectSessionStatus(task: AgentOSTaskSummary): SessionStatus {
	const raw = task.runStatus ?? task.status;
	switch (raw) {
		case null:
		case 'DRAFT':
			// NOT Untitled: upstream treats Untitled as a locally-composed,
			// unsent chat and opens the interactive new-chat composer for it,
			// which would hand a write surface to a runtime-owned draft.
			return SessionStatus.InProgress;
		case 'COMMITTED':
		case 'CREATED':
		case 'QUEUED':
		case 'RUNNING':
		case 'VERIFYING':
			return SessionStatus.InProgress;
		case 'WAITING':
		case 'WAITING_APPROVAL':
		case 'WAITING_EVENT':
		case 'PAUSED':
			return SessionStatus.NeedsInput;
		case 'COMPLETED':
		case 'SUCCEEDED':
			return SessionStatus.Completed;
		case 'FAILED':
		case 'CANCELLED':
			return SessionStatus.Error;
		default:
			throw new Error(`Unknown Agent OS task status: ${String(raw)}`);
	}
}

const READ_ONLY_CHAT_CAPABILITIES = constObservable({ canRename: false, canDelete: false });
const READ_ONLY_SESSION_CAPABILITIES = constObservable({
	supportsMultipleChats: false,
	supportsFork: false,
	supportsSideChat: false,
	supportsRename: false,
	supportsDelete: false,
});

/**
 * The single read-only main chat projected for a runtime task. The composer,
 * rename and delete affordances stay hidden because the runtime — not the
 * workbench — owns the conversation.
 */
class AgentOSChat implements IChat {
	readonly resource: URI;
	readonly createdAt: Date;
	readonly title: IObservable<string>;
	readonly updatedAt: IObservable<Date>;
	readonly status: IObservable<SessionStatus>;
	readonly changes = constObservable([]);
	readonly checkpoints = constObservable(undefined);
	readonly modelId = constObservable(undefined);
	readonly modelSource = constObservable(undefined);
	readonly mode = constObservable(undefined);
	readonly isArchived = constObservable(false);
	readonly isRead = constObservable(true);
	readonly interactivity = constObservable(ChatInteractivity.ReadOnly);
	readonly description = constObservable(undefined);
	readonly lastTurnEnd = constObservable(undefined);
	readonly origin = { kind: ChatOriginKind.User };
	readonly capabilities = READ_ONLY_CHAT_CAPABILITIES;

	constructor(resource: URI, task: AgentOSTaskSummary, status: SessionStatus, fetchedAt: number) {
		this.resource = resource;
		this.createdAt = new Date(fetchedAt);
		this.title = observableValue('agentOSChatTitle', task.statement.length > 0 ? task.statement : task.taskId);
		this.updatedAt = observableValue('agentOSChatUpdatedAt', new Date(fetchedAt));
		this.status = observableValue('agentOSChatStatus', status);
	}
}

/**
 * Stable session facade for one runtime task. Facade identity and the task
 * resource never change across refreshes; only the projected observables move.
 */
class AgentOSSession implements ISession {
	readonly sessionId: string;
	readonly resource: URI;
	readonly providerId = AGENT_OS_PROVIDER_ID;
	readonly sessionType = AGENT_OS_SESSION_TYPE_ID;
	readonly icon: ThemeIcon = Codicon.tasklist;
	readonly createdAt: Date;
	readonly workspace = constObservable<ISessionWorkspace | undefined>(undefined);
	readonly title: ISettableObservable<string>;
	readonly updatedAt: ISettableObservable<Date>;
	readonly status: ISettableObservable<SessionStatus>;
	readonly changes = constObservable([]);
	readonly changesets = constObservable(undefined);
	readonly modelId = constObservable(undefined);
	readonly mode = constObservable(undefined);
	readonly loading = constObservable(false);
	readonly isArchived = constObservable(false);
	readonly isRead = constObservable(true);
	readonly description = constObservable(undefined);
	readonly lastTurnEnd = constObservable(undefined);
	readonly chats: IObservable<readonly IChat[]>;
	readonly mainChat: IObservable<IChat>;
	readonly capabilities = READ_ONLY_SESSION_CAPABILITIES;

	constructor(task: AgentOSTaskSummary, fetchedAt: number) {
		this.resource = agentOSTaskResource(task.taskId);
		this.sessionId = toSessionId(AGENT_OS_PROVIDER_ID, this.resource);
		this.createdAt = new Date(fetchedAt);
		const chat = new AgentOSChat(this.resource, task, projectSessionStatus(task), fetchedAt);
		this.title = observableValue('agentOSSessionTitle', task.statement.length > 0 ? task.statement : task.taskId);
		this.updatedAt = observableValue('agentOSSessionUpdatedAt', new Date(fetchedAt));
		this.status = observableValue('agentOSSessionStatus', projectSessionStatus(task));
		this.chats = constObservable([chat]);
		this.mainChat = constObservable(chat);
	}

	/** Applies a refreshed task in place; returns whether anything observable moved. */
	update(task: AgentOSTaskSummary, fetchedAt: number): boolean {
		const nextTitle = task.statement.length > 0 ? task.statement : task.taskId;
		const nextStatus = projectSessionStatus(task);
		const titleChanged = this.title.get() !== nextTitle;
		const statusChanged = this.status.get() !== nextStatus;
		if (!titleChanged && !statusChanged) {
			return false;
		}
		if (titleChanged) {
			this.title.set(nextTitle, undefined);
		}
		if (statusChanged) {
			this.status.set(nextStatus, undefined);
		}
		this.updatedAt.set(new Date(fetchedAt), undefined);
		return true;
	}
}

/**
 * Read-only projection of the Agent OS Runtime task catalog into the upstream
 * sessions model. One session per runtime task, one read-only main chat per
 * session. Every mutation entry point rejects with {@link AgentOSReadOnlyError}.
 */
export class AgentOSSessionsProvider extends Disposable implements ISessionsProvider {
	readonly id = AGENT_OS_PROVIDER_ID;
	readonly label = localize('agentOS.providerLabel', "Agent OS Runtime");
	readonly icon: ThemeIcon = Codicon.tasklist;
	readonly order = 100;
	readonly supportsQuickChats = false;
	readonly browseActions = [];
	readonly automations = undefined;
	readonly sessionTypes: readonly ISessionType[] = [{
		id: AGENT_OS_SESSION_TYPE_ID,
		label: localize('agentOS.sessionTypeLabel', "Agent OS Task"),
		icon: Codicon.tasklist,
		authRequirement: SessionTypeAuthRequirement.None,
	}];
	readonly onDidChangeSessionTypes = Event.None;
	readonly onDidChangeModels = Event.None;

	private readonly _onDidChangeSessions = this._register(new Emitter<ISessionChangeEvent>());
	readonly onDidChangeSessions = this._onDidChangeSessions.event;

	/** Last refresh failure; the previous projection is kept when this is set. */
	private readonly _lastError = observableValue<Error | undefined>('agentOSProviderLastError', undefined);
	readonly lastError: IObservable<Error | undefined> = this._lastError;

	private readonly _sessions = new Map<string, AgentOSSession>();

	readonly catalog: IRuntimeTaskCatalogService;

	constructor(catalog: IRuntimeTaskCatalogService) {
		super();
		this.catalog = catalog;
	}

	getSessions(): ISession[] {
		return [...this._sessions.values()];
	}

	/**
	 * Pulls the catalog and reconciles the projection. Any failure — transport,
	 * decode, duplicate ids, unknown statuses — leaves the previous projection
	 * untouched and records the error; bad data never reaches the UI.
	 */
	async refresh(): Promise<void> {
		let snapshot: AgentOSTaskCatalogSnapshot;
		try {
			snapshot = await this.catalog.listTasks();
		} catch (error) {
			this._lastError.set(error instanceof Error ? error : new Error(String(error)), undefined);
			return;
		}
		const seen = new Set<string>();
		for (const task of snapshot.tasks) {
			if (seen.has(task.taskId)) {
				this._lastError.set(new Error(`Duplicate Agent OS task id: ${task.taskId}`), undefined);
				return;
			}
			seen.add(task.taskId);
		}
		try {
			for (const task of snapshot.tasks) {
				projectSessionStatus(task);
			}
		} catch (error) {
			this._lastError.set(error instanceof Error ? error : new Error(String(error)), undefined);
			return;
		}

		const added: ISession[] = [];
		const removed: ISession[] = [];
		const changed: ISession[] = [];
		const next = new Map<string, AgentOSSession>();
		for (const task of [...snapshot.tasks].sort((a, b) => a.sequence - b.sequence)) {
			const existing = this._sessions.get(task.taskId);
			if (existing) {
				if (existing.update(task, snapshot.fetchedAt)) {
					changed.push(existing);
				}
				next.set(task.taskId, existing);
			} else {
				const session = new AgentOSSession(task, snapshot.fetchedAt);
				added.push(session);
				next.set(task.taskId, session);
			}
		}
		for (const [taskId, session] of this._sessions) {
			if (!next.has(taskId)) {
				removed.push(session);
			}
		}
		this._sessions.clear();
		for (const [taskId, session] of next) {
			this._sessions.set(taskId, session);
		}
		this._lastError.set(undefined, undefined);
		if (added.length > 0 || removed.length > 0 || changed.length > 0) {
			this._onDidChangeSessions.fire({ added, removed, changed });
		}
	}

	resolveWorkspace(_workspaceUri: URI): ISessionWorkspace | undefined {
		return undefined;
	}

	/**
	 * Records a transcript/content projection failure on the shared error
	 * surface. The chat view itself rejects fail-closed; this makes the same
	 * failure visible next to the session list the user clicked.
	 */
	reportContentError(error: Error): void {
		this._lastError.set(error, undefined);
	}

	getSessionTypes(_workspaceUri: URI): ISessionType[] {
		return [];
	}

	getModelsSnapshot(_sessionId: string, _desiredModelId?: string): ISessionModelsSnapshot {
		return { models: [], desiredModelResolution: { kind: 'notRequested' }, modelTarget: undefined };
	}

	getModelPickerOptions(_sessionId: string): ISessionModelPickerOptions {
		return {
			useGroupedModelPicker: false,
			showFeatured: false,
			showUnavailableFeatured: false,
			showManageModelsAction: false,
			showAutoModel: false,
		};
	}

	createNewSession(_workspaceUri: URI, _sessionTypeId: string, _options?: ISessionsProviderCreateSessionOptions): ISession {
		return readOnly();
	}

	createQuickChat(_sessionTypeId: string): ISession {
		return readOnly();
	}

	deleteNewSession(_sessionId: string): void {
		readOnly();
	}

	renameChat(_sessionId: string, _chatUri: URI, _title: string): Promise<void> {
		return Promise.reject(new AgentOSReadOnlyError());
	}

	renameSession(_sessionId: string, _title: string): Promise<void> {
		return Promise.reject(new AgentOSReadOnlyError());
	}

	setModel(_sessionId: string, _chatResource: URI, _modelId: string, _source: unknown): void {
		readOnly();
	}

	archiveSession(_sessionId: string): Promise<void> {
		return Promise.reject(new AgentOSReadOnlyError());
	}

	unarchiveSession(_sessionId: string): Promise<void> {
		return Promise.reject(new AgentOSReadOnlyError());
	}

	setSessionReadState(_sessionId: string, _isRead: boolean): Promise<void> {
		return Promise.reject(new AgentOSReadOnlyError());
	}

	deleteSession(_sessionId: string): Promise<void> {
		return Promise.reject(new AgentOSReadOnlyError());
	}

	deleteSessions(_sessionIds: readonly string[]): Promise<void> {
		return Promise.reject(new AgentOSReadOnlyError());
	}

	deleteChat(_sessionId: string, _chatUri: URI, _options?: IDeleteChatOptions): Promise<boolean> {
		return Promise.reject(new AgentOSReadOnlyError());
	}

	createNewChat(_sessionId: string, _prompt?: string): Promise<IChat> {
		return Promise.reject(new AgentOSReadOnlyError());
	}

	forkChat(_sessionId: string, _sourceChat: URI, _turnId: string): Promise<IChat> {
		return Promise.reject(new AgentOSReadOnlyError());
	}

	createSideChat(_sessionId: string, _sourceChat: URI, _turnId: string): Promise<IChat> {
		return Promise.reject(new AgentOSReadOnlyError());
	}

	sendRequest(_sessionId: string, _chatResource: URI, _options: ISendRequestOptions): Promise<ISession> {
		return Promise.reject(new AgentOSReadOnlyError());
	}
}
