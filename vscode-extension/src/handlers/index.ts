/**
 * Handlers module barrel export
 *
 * Phase 2 of chatPanel.ts refactoring - exports extracted command handlers
 * and the HandlerContext interface for dependency injection.
 */

export { HandlerContext, HandlerResult, DialogCallbacks, CommandHandler } from './types';
export { handleToolsCommand, handleCheckpointCommand } from './commands';
