/**
 * Shared Module Index
 *
 * Re-exports all shared modules for easy importing.
 *
 * Usage (ES Modules):
 *   import { SLASH_COMMANDS, ApiClient, formatToolsStatus } from './shared/index.js';
 *
 * Usage (CommonJS):
 *   const { SLASH_COMMANDS, ApiClient, formatToolsStatus } = require('./shared');
 *
 * @version 1.14.0
 */

// Commands
export {
    CommandCategory,
    SLASH_COMMANDS,
    getCommandNames,
    getCommandsByCategory,
    isSlashCommand,
    parseCommand,
    generateHelpText,
    AI_FORWARDED_COMMANDS,
    isAIForwardedCommand
} from './commands.js';

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
    const commands = require('./commands.js');
    const apiClient = require('./api-client.js');
    const formatters = require('./formatters.js');

    module.exports = {
        ...commands,
        ...apiClient,
        ...formatters
    };
}
