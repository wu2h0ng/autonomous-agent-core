/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Agent OS contributors. All rights reserved.
 *  Licensed under the MIT License. See License.txt in the project root for license information.
 *--------------------------------------------------------------------------------------------*/

import type { INativeHostService } from '../../platform/native/common/native.js';

export async function openSessionsWindow(nativeHostService: INativeHostService): Promise<void> {
	await nativeHostService.openAgentsWindow();
}

export async function focusOrOpenIDEWindow(nativeHostService: INativeHostService): Promise<void> {
	const windows = await nativeHostService.getWindows({ includeAuxiliaryWindows: false });
	const ideWindow = windows.find(window => window.isSessionsWindow === false);
	if (ideWindow) {
		await nativeHostService.focusWindow({ targetWindowId: ideWindow.id });
	} else {
		await nativeHostService.openWindow();
	}
}
