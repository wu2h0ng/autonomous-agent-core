/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Agent OS contributors. All rights reserved.
 *  Licensed under the MIT License. See License.txt in the project root for license information.
 *--------------------------------------------------------------------------------------------*/

import { registerSingleton, InstantiationType } from '../../platform/instantiation/common/extensions.js';
import { IRuntimeTaskCatalogService } from '../common/runtimeTaskCatalogService.js';
import { RuntimeTaskCatalogService } from './runtimeTaskCatalogService.js';

registerSingleton(IRuntimeTaskCatalogService, RuntimeTaskCatalogService, InstantiationType.Delayed);
