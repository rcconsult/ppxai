/**
 * Shared Response Formatters
 *
 * Provides consistent markdown formatting for command responses across:
 * - Desktop Web App (ppxai/web/app.js)
 * - VSCode Extension (vscode-extension/src/chatPanel.ts)
 *
 * Uses standard markdown list syntax (-) for proper rendering with marked.js.
 *
 * @version 1.14.0
 */

/**
 * Format tools status response
 */
function formatToolsStatus(data) {
    let text = '**Tools Status:**\n\n';
    text += `- Enabled: ${data.enabled ? 'yes' : 'no'}  \n`;
    text += `- Tool count: ${data.tools?.length || 0}  \n`;
    text += `- Verbose: ${data.verbose ? 'on' : 'off'}  \n`;
    if (data.max_iterations) {
        text += `- Max iterations: ${data.max_iterations}  \n`;
    }
    if (data.consent_mode) {
        text += `- Consent mode: ${data.consent_mode}  \n`;
    }
    return text;
}

/**
 * Format tools list response
 */
function formatToolsList(tools) {
    if (!tools || tools.length === 0) {
        return '**Available Tools:**\n\nNo tools available. Use `/tools enable` first.';
    }
    let text = '**Available Tools:**\n\n';
    tools.forEach(t => {
        text += `- \`${t.name}\` - ${t.description}  \n`;
    });
    return text;
}

/**
 * Format tool config response
 */
function formatToolConfig(data) {
    let text = '**Tool Configuration:**\n\n';
    text += `- Enabled: ${data.enabled ? 'yes' : 'no'}  \n`;
    text += `- Max iterations: ${data.max_iterations || 15}  \n`;
    text += `- Verbose: ${data.verbose ? 'on' : 'off'}  \n`;
    text += `- Consent mode: ${data.consent_mode || 'default'}  \n`;
    text += `- Tool count: ${data.tools?.length || 0}  \n`;
    return text;
}

/**
 * Format tool help response
 */
function formatToolHelp(data) {
    let text = `**Tool: ${data.name}**\n\n`;
    text += `${data.description}\n\n`;
    if (data.parameters && data.parameters.properties) {
        text += '**Parameters:**\n\n';
        const required = data.parameters.required || [];
        Object.entries(data.parameters.properties).forEach(([name, prop]) => {
            const isRequired = required.includes(name) ? ' *(required)*' : '';
            text += `- \`${name}\`${isRequired}: ${prop.description || prop.type || 'no description'}  \n`;
        });
    }
    return text;
}

/**
 * Format agent status response
 */
function formatAgentStatus(data) {
    const status = data.agent_mode ? 'ON' : 'OFF';
    return `**Agent Mode:** ${status}\n\nUsage: \`/tools agent on|off\`\nOr use \`/agent <task>\` to run an autonomous task.`;
}

/**
 * Format checkpoint status response
 */
function formatCheckpointStatus(data) {
    let text = '**Checkpoint Status:**\n\n';
    if (data.checkpoint) {
        text += `- Backend: ${data.checkpoint.backend}  \n`;
        text += `- Enabled: ${data.checkpoint.enabled ? 'yes' : 'no'}  \n`;
        text += `- Last checkpoint: ${data.checkpoint.last_checkpoint || 'none'}  \n`;
        text += `- Valid: ${data.checkpoint.is_valid ? 'yes' : 'no'}  \n`;
        if (!data.checkpoint.is_valid && data.checkpoint.validity_reason) {
            text += `- Reason: ${data.checkpoint.validity_reason}  \n`;
        }
    } else {
        text += 'Checkpoint system not available.\n';
    }
    return text;
}

/**
 * Format checkpoint list response
 */
function formatCheckpointList(data) {
    let text = '**Recent Checkpoints:**\n\n';
    if (!data.checkpoints || data.checkpoints.length === 0) {
        text += 'No checkpoints found.\n';
    } else {
        data.checkpoints.forEach(cp => {
            text += `- \`${cp.id}\` - ${cp.description} (${cp.timestamp})  \n`;
        });
    }
    return text;
}

/**
 * Format checkpoint info response
 */
function formatCheckpointInfo(data) {
    let text = '**Checkpoint Details:**\n\n';
    text += `- ID: \`${data.id}\`  \n`;
    text += `- Description: ${data.description}  \n`;
    text += `- Timestamp: ${data.timestamp}  \n`;
    const statusText = data.is_current
        ? (data.is_valid ? 'Current (can undo)' : 'Stale (cannot undo)')
        : 'Historical';
    text += `- Status: ${statusText}  \n`;
    return text;
}

/**
 * Format checkpoint backend help
 */
function formatCheckpointBackendHelp() {
    return `**Checkpoint Backend**

Usage: \`/checkpoint backend <git|file|auto|none>\`

- \`git\`: Use git commits (recommended for git repos)
- \`file\`: Use file snapshots (~/.ppxai/checkpoints/)
- \`auto\`: Auto-detect best backend
- \`none\`: Disable checkpoints`;
}

/**
 * Format usage statistics response (legacy — kept for backward compatibility)
 */
function formatUsageStats(data, period = null) {
    let text = '**Usage Statistics:**\n\n';

    if (period) {
        text += `**Period:** ${data.period}  \n`;
        text += `**Sessions:** ${data.session_count}\n\n`;
    }

    text += `- Prompt tokens: ${data.prompt_tokens || 0}  \n`;
    text += `- Completion tokens: ${data.completion_tokens || 0}  \n`;
    text += `- Total tokens: ${data.total_tokens || 0}  \n`;
    text += `- Estimated cost: $${(data.estimated_cost || data.total_cost || 0).toFixed(4)}  \n`;

    if (data.by_model && Object.keys(data.by_model).length > 0) {
        text += '\n**By Model:**\n\n';
        Object.entries(data.by_model).forEach(([model, stats]) => {
            text += `- ${model}: ${stats.total_tokens} tokens, $${stats.estimated_cost.toFixed(4)}  \n`;
        });
    }

    return text;
}

// ============================================================================
// Generic CommandResult Formatters (v1.16.1)
// Used by renderCommandResult() to display server-side command results.
// These work for ANY command, not just /usage.
// ============================================================================

/**
 * Format a TableResult as markdown table.
 *
 * When metadata contains usage report fields (report_type, total_tokens, etc.),
 * renders a rich summary with bullet points above the table — matching the
 * VSCode extension's formatUsageStats() style.
 */
function formatTableResult(result) {
    const meta = result.metadata || {};

    // Usage report: render rich summary + table
    if (meta.report_type) {
        return _formatUsageTableResult(result, meta);
    }

    // Generic table
    let text = `**${result.message}**\n\n`;
    text += _renderMarkdownTable(result.columns, result.rows);
    return text;
}

/**
 * Format a usage-specific TableResult with bullet-point summary.
 */
function _formatUsageTableResult(result, meta) {
    let text = `**${meta.title || result.message}**\n\n`;

    // Period report header
    if (meta.report_type === 'period') {
        if (meta.period) {
            text += `**Period:** ${meta.period}  \n`;
        }
        if (meta.start_date && meta.end_date) {
            text += `**Range:** ${meta.start_date} to ${meta.end_date}  \n`;
        }
        if (meta.session_count !== undefined) {
            text += `**Sessions:** ${meta.session_count}  \n`;
        }
        text += '\n';
    }

    // Token summary bullets
    const totalTokens = meta.total_tokens || 0;
    const promptTokens = meta.prompt_tokens || 0;
    const completionTokens = meta.completion_tokens || 0;
    const cost = meta.estimated_cost || 0;

    text += `• Total tokens: ${totalTokens.toLocaleString()} (${promptTokens.toLocaleString()}↓ / ${completionTokens.toLocaleString()}↑)  \n`;
    text += `• Estimated cost: $${cost.toFixed(4)}  \n`;

    // Display mode (session reports only)
    if (meta.display_mode) {
        text += `• Display mode: \`${meta.display_mode}\`  \n`;
        text += `• Use \`/usage show <session|provider|model|off>\` to change.  \n`;
    }

    // Table
    if (result.rows && result.rows.length > 0) {
        text += '\n**Usage by Model:**\n\n';
        text += _renderMarkdownTable(result.columns, result.rows);
    }

    return text;
}

/**
 * Render columns + rows as a markdown table string.
 */
function _renderMarkdownTable(columns, rows) {
    if (!columns || columns.length === 0 || !rows || rows.length === 0) {
        return '';
    }
    let text = '| ' + columns.join(' | ') + ' |\n';
    text += '|' + columns.map(() => '---').join('|') + '|\n';
    rows.forEach(row => {
        text += '| ' + row.join(' | ') + ' |\n';
    });
    return text;
}

/**
 * Format a KeyValueResult as markdown list
 */
function formatKeyValueResult(result) {
    let text = `**${result.message}**\n\n`;
    if (result.pairs) {
        Object.entries(result.pairs).forEach(([k, v]) => {
            text += `- ${k}: \`${v}\`\n`;
        });
    }
    return text;
}

/**
 * Format usage display mode help
 */
function formatUsageDisplayHelp() {
    return `**Usage Display Mode**

Usage: \`/usage show <mode>\`

**Modes:**

- \`session\`: Show session totals
- \`provider\`: Show by provider
- \`model\`: Show by model
- \`off\`: Hide usage display`;
}

/**
 * Format status response
 */
function formatStatus(data) {
    let text = '**Current Status:**\n\n';
    text += `- Provider: ${data.provider}  \n`;
    text += `- Model: ${data.model}  \n`;
    text += `- Tools: ${data.tools_enabled ? 'enabled' : 'disabled'}  \n`;
    if (data.auto_inject_context !== undefined) {
        text += `- Auto-inject context: ${data.auto_inject_context ? 'yes' : 'no'}  \n`;
    }
    if (data.message_count !== undefined) {
        text += `- Messages: ${data.message_count}  \n`;
    }
    return text;
}

/**
 * Format providers list response
 */
function formatProvidersList(providers, currentProvider = null) {
    let text = '**Available Providers:**\n\n';
    providers.forEach(p => {
        const current = p.id === currentProvider ? ' *(current)*' : '';
        const apiKey = p.has_api_key ? '' : ' (no API key)';
        text += `- \`${p.id}\`${current} - ${p.name}${apiKey}  \n`;
    });
    return text;
}

/**
 * Format models list response
 */
function formatModelsList(models, currentModel = null) {
    let text = '**Available Models:**\n\n';
    models.forEach(m => {
        const current = m.id === currentModel ? ' *(current)*' : '';
        text += `- \`${m.id}\`${current} - ${m.name || m.description}  \n`;
    });
    return text;
}

/**
 * Format sessions list response
 */
function formatSessionsList(sessions) {
    if (!sessions || sessions.length === 0) {
        return '**Saved Sessions:**\n\nNo saved sessions.';
    }
    let text = '**Saved Sessions:**\n\n';
    text += '| Session | Messages | Provider/Model | Created | Last Saved |\n';
    text += '|:--------|:--------:|:---------------|:--------|:-----------|\n';
    sessions.forEach(s => {
        const created = s.created_at ? s.created_at.slice(0, 16).replace('T', ' ') : 'unknown';
        const saved = s.saved_at ? s.saved_at.slice(0, 16).replace('T', ' ') : '-';
        text += `| \`${s.name}\` | ${s.message_count} | ${s.provider}/${s.model} | ${created} | ${saved} |\n`;
    });
    return text;
}

/**
 * Format file contents for /show command
 */
function formatFileContents(filepath, content, language = null) {
    const ext = filepath.split('.').pop() || '';
    const lang = language || ext || 'text';
    return `**File: ${filepath}**\n\n\`\`\`${lang}\n${content}\n\`\`\``;
}

/**
 * Format error message
 */
function formatError(message) {
    return `**Error:** ${message}`;
}

/**
 * Format success message
 */
function formatSuccess(message) {
    return `✓ ${message}`;
}

// Browser global export (for non-module scripts)
if (typeof window !== 'undefined') {
    window.SharedFormatters = {
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
        formatTableResult,
        formatKeyValueResult
    };
}

// CommonJS export (for Node.js/bundlers)
if (typeof module !== 'undefined' && module.exports) {
    module.exports = {
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
        formatTableResult,
        formatKeyValueResult
    };
}
