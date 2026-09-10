/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Agent OS contributors. All rights reserved.
 *  Licensed under the MIT License. See License.txt in the project root for license information.
 *--------------------------------------------------------------------------------------------*/

import { Disposable } from '../../base/common/lifecycle.js';
import { IWorkbenchContribution, registerWorkbenchContribution2, WorkbenchPhase } from '../../workbench/common/contributions.js';
import { ISessionsProvidersService } from '../../sessions/services/sessions/browser/sessionsProvidersService.js';
import { IRuntimeTaskCatalogService } from '../common/runtimeTaskCatalogService.js';
import { AgentOSSessionsProvider } from './agentOSSessionsProvider.js';

/**
 * Registers the read-only Agent OS Runtime sessions provider. Imported only
 * from the Sessions desktop entry — the IDE workbench never loads it, and no
 * shared `vs/sessions` module imports `vs/agentos`.
 */
class AgentOSSessionsProviderContribution extends Disposable implements IWorkbenchContribution {
	static readonly ID = 'agentOS.sessionsProvider';

	constructor(
		@ISessionsProvidersService sessionsProvidersService: ISessionsProvidersService,
		@IRuntimeTaskCatalogService runtimeTaskCatalogService: IRuntimeTaskCatalogService,
	) {
		super();
		const provider = this._register(new AgentOSSessionsProvider(runtimeTaskCatalogService));
		this._register(sessionsProvidersService.registerProvider(provider));
		// Runtime offline is a normal Slice 1 state: refresh records the error
		// and the projection simply stays empty until the next refresh.
		void provider.refresh();
	}
}

registerWorkbenchContribution2(AgentOSSessionsProviderContribution.ID, AgentOSSessionsProviderContribution, WorkbenchPhase.AfterRestored);
