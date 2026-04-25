/**
 * ResultRenderer — type-based rendering for CommandResult envelope payloads (v1.18.1).
 *
 * Maps `result.type` (set by `CommandResult.to_dict()` server-side)
 * to a DOM action on the chat. Web/VSCode share this contract; the
 * VSCode extension has a parallel renderer in its webview that
 * follows the same dispatch shape.
 *
 * Coverage choice: the seven types most-used by current commands
 * get explicit handlers (Notification, Confirmation, Error,
 * Markdown, Table, Tree, KeyValue). The long tail (FileView, Image,
 * Preview, etc.) is intentionally a no-op here — those types ride
 * with a side-effect kind (`open_viewer`, `show_image`,
 * `open_html_preview`) that the side-effects dispatcher handles
 * separately. The chat-message rendering for those types is
 * already done by the side-effect's panel/inline view.
 *
 * Unknown types fall through to `result.message` as plain system
 * text, so a future server-side type addition doesn't break the
 * client.
 *
 * Usage:
 *   const renderer = new ResultRenderer(app);
 *   renderer.render(envelope.result);
 */
class ResultRenderer {
    /** @param {PpxaiApp} app */
    constructor(app) {
        this.app = app;
    }

    /**
     * Render a CommandResult dict from the v1.18.1 envelope.
     * Pass `envelope.result`, NOT the whole envelope.
     */
    render(result) {
        if (!result) return;
        if (typeof result !== 'object') return;
        const type = result.type || 'TextResult';
        const handler = ResultRenderer._handlers[type] || ResultRenderer._handlers._default;
        try {
            handler.call(this, result);
        } catch (e) {
            console.warn('[ResultRenderer] handler failed for', type, e);
            this._fallback(result);
        }
    }

    _fallback(result) {
        const msg = result.message || `(unhandled result: ${result.type})`;
        this.app.showSystemMessage(msg);
    }

    _formatTree(result) {
        // TreeResult.root → markdown nested list
        const root = result.root;
        if (!root) return result.message || '';
        const lines = [`**${result.message}**`, ''];
        const walk = (node, depth) => {
            const indent = '  '.repeat(depth);
            lines.push(`${indent}- ${node.label || ''}`);
            for (const child of (node.children || [])) walk(child, depth + 1);
        };
        walk(root, 0);
        return lines.join('\n');
    }
}

ResultRenderer._handlers = {
    NotificationResult(result) {
        const level = result.status === 'error'
            ? 'error'
            : result.status === 'warning' ? 'warning' : 'info';
        this.app.showSystemMessage(result.message, level);
    },

    ConfirmationResult(result) {
        this.app.showSystemMessage(result.message);
    },

    ErrorResult(result) {
        const lines = [result.message];
        if (Array.isArray(result.suggestions) && result.suggestions.length) {
            lines.push(...result.suggestions);
        }
        this.app.showError(lines.join('\n'));
    },

    MarkdownResult(result) {
        // MarkdownResult.content has the rendered markdown body;
        // result.message is a short label/title. Prefer content,
        // fall back to message so empty-content edge cases still
        // surface something.
        const body = result.content || result.message || '';
        this.app.addMessage('system', body);
    },

    TextResult(result) {
        // TextResult is the Rich-markup variant from TUI handlers.
        // For HTTP clients the rich tags would render literally.
        // The factory's HTTP-aware handlers return MarkdownResult
        // instead — but if a TextResult slips through, render
        // plain so we don't show `[bold]` etc. as visible characters.
        const text = (result.message || '').replace(/\[\/?[^\]]+\]/g, '');
        this.app.showSystemMessage(text);
    },

    TableResult(result) {
        if (typeof window.SharedFormatters?.formatTableResult === 'function') {
            this.app.addMessage('system', window.SharedFormatters.formatTableResult(result));
        } else {
            // Fallback if the shared formatter isn't loaded
            this.app.showSystemMessage(result.message);
        }
    },

    TreeResult(result) {
        this.app.addMessage('system', this._formatTree(result));
    },

    KeyValueResult(result) {
        if (typeof window.SharedFormatters?.formatKeyValueResult === 'function') {
            this.app.addMessage('system', window.SharedFormatters.formatKeyValueResult(result));
        } else {
            const lines = [`**${result.message}**`];
            for (const [k, v] of Object.entries(result.pairs || {})) {
                lines.push(`- **${k}:** ${v}`);
            }
            this.app.addMessage('system', lines.join('\n'));
        }
    },

    ListResult(result) {
        // Same shape as a markdown bullet list.
        const lines = [`**${result.message}**`, ''];
        for (const item of (result.items || [])) {
            const text = typeof item === 'string' ? item : (item.text || item.label || '');
            const icon = item.icon ? `${item.icon} ` : '';
            lines.push(`- ${icon}${text}`);
        }
        this.app.addMessage('system', lines.join('\n'));
    },

    // Types whose payload is rendered by their side-effect, not
    // by the chat. The side-effects dispatcher opens the panel /
    // image / preview; the chat doesn't need to duplicate that.
    FileViewResult(result) {
        // Optional brief notice; the open_viewer/open_editor
        // side-effect already opens the panel.
        if (result.message) this.app.showSystemMessage(result.message);
    },
    ImageResult(result) {
        if (result.message) this.app.showSystemMessage(result.message);
    },
    PreviewResult(result) {
        if (result.message) this.app.showSystemMessage(result.message);
    },

    _default(result) {
        // Unknown type — open enum, ignore gracefully.
        this._fallback(result);
    },
};


// CommonJS export for tests; window-global for browser.
if (typeof module !== 'undefined' && module.exports) {
    module.exports = { ResultRenderer };
} else if (typeof window !== 'undefined') {
    window.ResultRenderer = ResultRenderer;
}
