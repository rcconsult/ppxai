/**
 * Shared Module Index
 *
 * Re-exports all shared modules for easy importing.
 *
 * @version 1.14.0
 */

// Commands — ADR 0007 step 3b (2026-09-21).
//
// `./commands` is DELETED. It was a hand-written 31-entry slash-command
// catalog whose header claimed to be "the single source of truth across
// the Desktop Web App and the VSCode Extension" — it was neither shared
// (web had its own copy, also deleted, in step 3a) nor true (it listed
// neither /run, /task nor /token, all three intercepted at runtime).
// The catalog now comes from `GET /commands?client=vscode`; see
// `src/commandRoster.ts` and `src/commandRouter.ts`, which are NOT
// re-exported here — they are host-side modules, not shared mirrors.
//
// Its helpers went with it, none of them replaced:
//   generateHelpText()  -> the factory's /help (showHelp in chatPanel.ts)
//   isSlashCommand()/parseCommand()  -> no consumer; routing is the roster
//   AI_FORWARDED_COMMANDS/isAIForwardedCommand()  -> no consumer; the six
//       coding commands are declared `coding.stream` in Python
//   getCommandNames()/getCommandsByCategory()/SLASH_COMMANDS  -> no
//       consumer; autocomplete has been server-side since v1.17.4

// Formatters
export {
    ToolsStatusData,
    CheckpointData,
    CheckpointInfoData,
    UsageData,
    StatusData,
    ProviderData,
    ModelData,
    SessionData,
    ToolHelpData,
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
    formatSuccess,
    formatTokens,
    formatUsageBadge,
} from './formatters';
