/**
 * Shared Slash Command Definitions
 *
 * This module is the single source of truth for slash commands across:
 * - Desktop Web App (ppxai/web/app.js)
 * - VSCode Extension (vscode-extension/src/chatPanel.ts)
 *
 * When adding new commands, update this file and both UIs will have access.
 *
 * @version 1.17.1
 */

// Command categories for organization
const CommandCategory = {
    SESSION: 'session',
    PROVIDER: 'provider',
    TOOLS: 'tools',
    CHECKPOINT: 'checkpoint',
    USAGE: 'usage',
    FILE: 'file',
    CODING: 'coding',
    OTHER: 'other'
};

/**
 * Slash command definitions
 * Each command has: description, usage, category, and optional subcommands
 */
const SLASH_COMMANDS = {
    // === Session & Chat ===
    '/help': {
        description: 'Show available commands',
        usage: '/help',
        category: CommandCategory.SESSION
    },
    '/clear': {
        description: 'Clear conversation history',
        usage: '/clear',
        category: CommandCategory.SESSION
    },
    '/save': {
        description: 'Save session to JSON',
        usage: '/save',
        category: CommandCategory.SESSION
    },
    '/export': {
        description: 'Export last answer to markdown',
        usage: '/export [filename]',
        category: CommandCategory.SESSION
    },
    '/load': {
        description: 'Load a saved session',
        usage: '/load [session_name]',
        category: CommandCategory.SESSION
    },
    '/sessions': {
        description: 'List saved sessions',
        usage: '/sessions',
        category: CommandCategory.SESSION
    },

    // === Provider & Model ===
    '/provider': {
        description: 'Switch provider or list providers',
        usage: '/provider [provider_id|list]',
        category: CommandCategory.PROVIDER,
        subcommands: ['list']
    },
    '/model': {
        description: 'Switch model or list models',
        usage: '/model [model_id|list]',
        category: CommandCategory.PROVIDER,
        subcommands: ['list']
    },

    // === Tools & Agent ===
    '/tools': {
        description: 'Manage AI tools',
        usage: '/tools [enable|disable|status|list|config|set|auto|help]',
        category: CommandCategory.TOOLS,
        subcommands: ['enable', 'disable', 'status', 'list', 'config', 'set', 'auto', 'help']
    },
    '/auto': {
        description: 'Run autonomous in-session task (was /agent)',
        usage: '/auto [on|off|<task description>]',
        category: CommandCategory.TOOLS,
        subcommands: ['on', 'off']
    },
    // v1.19.0 agent platform (web-client-only, experimental). Distinct from
    // /auto above: these drive the /v1/agent/* background run registry.
    '/agentrun': {
        description: 'Start a background agent run (v1 platform, experimental)',
        usage: '/agentrun <task>',
        category: CommandCategory.TOOLS
    },
    '/agentruns': {
        description: 'List recent agent runs (experimental)',
        usage: '/agentruns',
        category: CommandCategory.TOOLS
    },
    '/task': {
        description: 'Tool-capable background runs — direct launch; ls|get|watch|respond|collect|resume|cancel (default-off tier)',
        usage: '/task "<desc>" --tools a,b,c [--allow host] [--budget iters=,time=,tokens=]',
        category: CommandCategory.TOOLS,
        subcommands: ['ls', 'get', 'watch', 'respond', 'collect', 'resume', 'cancel', 'help']
    },
    '/token': {
        description: 'Manage the bearer token attached to /v1 API calls (status|set|mint|clear)',
        usage: '/token [status|set|mint|clear]',
        category: CommandCategory.TOOLS
    },

    // === Checkpoint ===
    '/checkpoint': {
        description: 'Manage checkpoints',
        usage: '/checkpoint [status|list|undo|backend|clear|info]',
        category: CommandCategory.CHECKPOINT,
        subcommands: ['status', 'list', 'undo', 'backend', 'clear', 'info']
    },

    // === Usage & Status ===
    '/usage': {
        description: 'Show token usage stats',
        usage: '/usage [24h|week|month|year|all|show|reset]',
        category: CommandCategory.USAGE,
        subcommands: ['24h', 'week', 'month', 'year', 'all', 'show', 'reset']
    },
    '/status': {
        description: 'Show current status',
        usage: '/status',
        category: CommandCategory.USAGE
    },
    '/context': {
        description: 'Show context window usage and injected files',
        usage: '/context [clear|hints|show|reload]',
        category: CommandCategory.USAGE,
        subcommands: ['clear', 'hints', 'show', 'reload']
    },

    // === File Display ===
    '/show': {
        description: 'Display file contents locally (no LLM call)',
        usage: '/show <filepath>',
        category: CommandCategory.FILE
    },
    '/cat': {
        description: 'Alias for /show',
        usage: '/cat <filepath>',
        category: CommandCategory.FILE
    },
    '/edit': {
        description: 'Open file in editor (supports line:col)',
        usage: '/edit <filepath[:line[:col]]>',
        category: CommandCategory.FILE
    },
    '/cd': {
        description: 'Change working directory',
        usage: '/cd <path>',
        category: CommandCategory.FILE
    },
    '/pwd': {
        description: 'Print working directory',
        usage: '/pwd',
        category: CommandCategory.FILE
    },
    '/ls': {
        description: 'List directory contents',
        usage: '/ls [path] [-a]',
        category: CommandCategory.FILE
    },
    '/tree': {
        description: 'Show directory tree',
        usage: '/tree [path] [depth]',
        category: CommandCategory.FILE
    },
    '/preview': {
        description: 'Preview HTML — static, full-stack (--serve), or proxied (--proxy)',
        usage: '/preview <file.html> [--serve ["cmd"]] [--proxy port] [--port N]',
        category: CommandCategory.FILE,
        subcommands: ['close', 'help']
    },
    '/terminal': {
        description: 'Open interactive terminal in right panel',
        usage: '/terminal',
        category: CommandCategory.FILE
    },
    '/term': {
        description: 'Alias for /terminal',
        usage: '/term',
        category: CommandCategory.FILE
    },
    '/sh': {
        description: 'Alias for /terminal',
        usage: '/sh',
        category: CommandCategory.FILE
    },

    // === Coding Tasks (forwarded to AI) ===
    '/generate': {
        description: 'Generate code from description',
        usage: '/generate <description>',
        category: CommandCategory.CODING
    },
    '/explain': {
        description: 'Explain code or concept',
        usage: '/explain <code or question>',
        category: CommandCategory.CODING
    },
    '/test': {
        description: 'Generate tests for code',
        usage: '/test <code or @file>',
        category: CommandCategory.CODING
    },
    '/docs': {
        description: 'Generate documentation',
        usage: '/docs <code or @file>',
        category: CommandCategory.CODING
    },
    '/debug': {
        description: 'Debug an error message',
        usage: '/debug <error message>',
        category: CommandCategory.CODING
    },
    '/implement': {
        description: 'Implement from description',
        usage: '/implement <description>',
        category: CommandCategory.CODING
    },
    '/convert': {
        description: 'Convert code between languages',
        usage: '/convert <source-lang> <target-lang> <code or @file>',
        category: CommandCategory.CODING
    },
    '/spec': {
        description: 'Show specification templates',
        usage: '/spec [api|cli|lib|algo|ui]',
        category: CommandCategory.CODING,
        subcommands: ['api', 'cli', 'lib', 'algo', 'ui']
    },

    // === Other ===
    '/theme': {
        description: 'Switch theme',
        usage: '/theme [dark|light]',
        category: CommandCategory.OTHER,
        subcommands: ['dark', 'light']
    },
    '/config': {
        description: 'Show or reload configuration',
        usage: '/config [reload|path]',
        category: CommandCategory.OTHER,
        subcommands: ['reload', 'path']
    }
};

/**
 * Get all command names
 */
function getCommandNames() {
    return Object.keys(SLASH_COMMANDS);
}

/**
 * Get commands by category
 */
function getCommandsByCategory(category) {
    return Object.entries(SLASH_COMMANDS)
        .filter(([_, cmd]) => cmd.category === category)
        .map(([name, cmd]) => ({ name, ...cmd }));
}

/**
 * Check if input is a slash command
 */
function isSlashCommand(input) {
    if (!input || typeof input !== 'string') return false;
    const trimmed = input.trim();
    return trimmed.startsWith('/') && getCommandNames().some(cmd =>
        trimmed === cmd || trimmed.startsWith(cmd + ' ')
    );
}

/**
 * Parse slash command input
 * @returns {object} { command, args, subcommand }
 */
function parseCommand(input) {
    const parts = input.trim().split(/\s+/);
    const command = parts[0].toLowerCase();
    const args = parts.slice(1);

    // Check if first arg is a known subcommand
    const cmdDef = SLASH_COMMANDS[command];
    let subcommand = null;
    if (cmdDef?.subcommands && args.length > 0) {
        if (cmdDef.subcommands.includes(args[0].toLowerCase())) {
            subcommand = args[0].toLowerCase();
        }
    }

    return { command, args, subcommand, argsString: args.join(' ') };
}

/**
 * Generate help text for all commands
 */
function generateHelpText() {
    let text = '**Available Commands:**\n\n';

    // Group by category
    const categories = {
        [CommandCategory.SESSION]: 'Session & Chat',
        [CommandCategory.PROVIDER]: 'Provider & Model',
        [CommandCategory.TOOLS]: 'Tools & Agent',
        [CommandCategory.CHECKPOINT]: 'Checkpoint',
        [CommandCategory.USAGE]: 'Usage & Status',
        [CommandCategory.FILE]: 'File Display',
        [CommandCategory.CODING]: 'Coding Tasks',
        [CommandCategory.OTHER]: 'Other'
    };

    for (const [category, title] of Object.entries(categories)) {
        const cmds = getCommandsByCategory(category);
        if (cmds.length > 0) {
            text += `**${title}:**\n`;
            for (const cmd of cmds) {
                text += `\`${cmd.usage}\` - ${cmd.description}\n`;
            }
            text += '\n';
        }
    }

    return text;
}

/**
 * Commands that are forwarded to AI (not handled locally)
 */
const AI_FORWARDED_COMMANDS = [
    '/generate', '/explain', '/test', '/docs',
    '/debug', '/implement', '/convert', '/spec'
];

/**
 * Check if command should be forwarded to AI
 */
function isAIForwardedCommand(command) {
    return AI_FORWARDED_COMMANDS.includes(command.toLowerCase());
}

// Browser global export (for non-module scripts)
if (typeof window !== 'undefined') {
    window.SharedCommands = {
        CommandCategory,
        SLASH_COMMANDS,
        getCommandNames,
        getCommandsByCategory,
        isSlashCommand,
        parseCommand,
        generateHelpText,
        AI_FORWARDED_COMMANDS,
        isAIForwardedCommand
    };
}

// CommonJS export (for Node.js/bundlers)
if (typeof module !== 'undefined' && module.exports) {
    module.exports = {
        CommandCategory,
        SLASH_COMMANDS,
        getCommandNames,
        getCommandsByCategory,
        isSlashCommand,
        parseCommand,
        generateHelpText,
        AI_FORWARDED_COMMANDS,
        isAIForwardedCommand
    };
}
