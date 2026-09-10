/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Agent OS contributors. All rights reserved.
 *  Licensed under the MIT License. See License.txt in the project root for license information.
 *--------------------------------------------------------------------------------------------*/

import { Codicon } from '../../base/common/codicons.js';
import { localize2 } from '../../nls.js';
import { Action2, MenuId, registerAction2 } from '../../platform/actions/common/actions.js';
import { IsWebContext } from '../../platform/contextkey/common/contextkeys.js';
import { ContextKeyExpr } from '../../platform/contextkey/common/contextkey.js';
import { ServicesAccessor } from '../../platform/instantiation/common/instantiation.js';
import { INativeHostService } from '../../platform/native/common/native.js';
import { Menus } from '../../sessions/browser/menus.js';
import { IsAuxiliaryWindowContext, IsSessionsWindowContext } from '../../workbench/common/contextkeys.js';
import { focusOrOpenIDEWindow, openSessionsWindow } from './windowNavigation.js';

const nativeMainWindow = ContextKeyExpr.and(IsWebContext.toNegated(), IsAuxiliaryWindowContext.toNegated());

registerAction2(class OpenSessionsWindowAction extends Action2 {
	constructor() {
		super({
			id: 'agentOS.openSessionsWindow',
			title: localize2('agentOS.openSessionsWindow', 'Agent OS: Open Agent Window'),
			f1: true,
			icon: Codicon.commentDiscussion,
			precondition: nativeMainWindow,
			menu: {
				id: MenuId.TitleBarAdjacentCenter,
				group: 'navigation',
				order: 1,
				when: ContextKeyExpr.and(nativeMainWindow, IsSessionsWindowContext.toNegated()),
			},
		});
	}

	override async run(accessor: ServicesAccessor): Promise<void> {
		await openSessionsWindow(accessor.get(INativeHostService));
	}
});

registerAction2(class FocusOrOpenIDEWindowAction extends Action2 {
	constructor() {
		super({
			id: 'agentOS.focusOrOpenIDEWindow',
			title: localize2('agentOS.focusOrOpenIDEWindow', 'Agent OS: Open IDE Window'),
			f1: true,
			icon: Codicon.code,
			precondition: nativeMainWindow,
			menu: {
				id: Menus.TitleBarCenterRight,
				group: 'navigation',
				order: 1,
				when: ContextKeyExpr.and(nativeMainWindow, IsSessionsWindowContext),
			},
		});
	}

	override async run(accessor: ServicesAccessor): Promise<void> {
		await focusOrOpenIDEWindow(accessor.get(INativeHostService));
	}
});
