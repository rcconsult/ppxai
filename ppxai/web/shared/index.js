/**
 * Shared Module Index
 *
 * Re-exports all shared modules for easy importing.
 *
 * Usage (ES Modules):
 *   import { CommandRoster, ApiClient, formatToolsStatus } from './shared/index.js';
 *
 * Usage (CommonJS):
 *   const { CommandRoster, ApiClient, formatToolsStatus } = require('./shared');
 *
 * @version 1.14.0
 */

// Command roster (ADR 0007 step 3a). `commands.js` — the hand-written
// catalog this used to re-export — is gone: the roster is FETCHED from
// `GET /commands?client=web` and cached by `CommandRoster`.
export { CommandRoster } from './command-roster.js';

// API Client
export { ApiClient, getApiClient } from './api-client.js';

// Formatters
export {
    formatToolsStatus,
    formatToolsList,
    formatToolConfig,
    formatToolHelp,
    formatAgentStatus,
    formatCheckpointStatus,
    formatCheckpointList,
    formatCheckpointInfo,
    formatCheckpointBackendHelp,
    formatUsageStats,
    formatUsageDisplayHelp,
    formatStatus,
    formatProvidersList,
    formatModelsList,
    formatSessionsList,
    formatFileContents,
    formatError,
    formatSuccess
} from './formatters.js';

// CommonJS compatibility
if (typeof module !== 'undefined' && module.exports) {
    const commandRoster = require('./command-roster.js');
    const apiClient = require('./api-client.js');
    const formatters = require('./formatters.js');

    module.exports = {
        ...commandRoster,
        ...apiClient,
        ...formatters
    };
}
