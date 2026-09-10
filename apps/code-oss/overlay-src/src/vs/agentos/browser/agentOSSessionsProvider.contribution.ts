/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Agent OS contributors. All rights reserved.
 *  Licensed under the MIT License. See License.txt in the project root for license information.
 *--------------------------------------------------------------------------------------------*/

import { Disposable } from '../../base/common/lifecycle.js';
import { IWorkbenchContribution, registerWorkbenchContribution2, WorkbenchPhase } from '../../workbench/common/contributions.js';
import { IChatSessionsService } from '../../workbench/contrib/chat/common/chatSessionsService.js';
import { ISessionsProvidersService } from '../../sessions/services/sessions/browser/sessionsProvidersService.js';
import { IRuntimeTaskCatalogService } from '../common/runtimeTaskCatalogService.js';
import { AGENT_OS_TASK_SCHEME, AgentOSSessionsProvider } from './agentOSSessionsProvider.js';
import { AgentOSTaskContentProvider } from './agentOSTaskContentProvider.js';

/**
 * Registers the read-only Agent OS Runtime sessions provider and the matching
 * task transcript content provider. Imported only from the Sessions desktop
 * entry — the IDE workbench never loads it, and no shared `vs/sessions`
 * module imports `vs/agentos`.
 */
class AgentOSSessionsProviderContribution extends Disposable implements IWorkbenchContribution {
	static readonly ID = 'agentOS.sessionsProvider';

	constructor(
		@ISessionsProvidersService sessionsProvidersService: ISessionsProvidersService,
		@IRuntimeTaskCatalogService runtimeTaskCatalogService: IRuntimeTaskCatalogService,
		@IChatSessionsService chatSessionsService: IChatSessionsService,
	) {
		super();
		const provider = this._register(new AgentOSSessionsProvider(runtimeTaskCatalogService));
		this._register(sessionsProvidersService.registerProvider(provider));
		// Read-only transcript: selecting a projected task opens its whitelist
		// detail and trajectory as chat history through the upstream content
		// provider seam. Projection failures reject the render fail-closed and
		// land on the provider's lastError surface.
		const transcript = this._register(new AgentOSTaskContentProvider(runtimeTaskCatalogService, error => provider.reportContentError(error)));
		this._register(chatSessionsService.registerChatSessionContentProvider(AGENT_OS_TASK_SCHEME, transcript));
		// Runtime offline is a normal Slice 1 state: refresh records the error
		// and the projection simply stays empty until the next refresh.
		void provider.refresh();
	}
}

registerWorkbenchContribution2(AgentOSSessionsProviderContribution.ID, AgentOSSessionsProviderContribution, WorkbenchPhase.AfterRestored);
