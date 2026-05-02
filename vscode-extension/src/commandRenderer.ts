/**
 * CommandRenderer — type-based dispatch for v1.18.1 envelope `result`.
 *
 * Mirrors ppxai/web/shared/result-renderer.js. Same coverage choice:
 * the seven types most-used by current commands get explicit
 * handlers (Notification, Confirmation, Error, Markdown, Table,
 * Tree, KeyValue). Long-tail types (FileView, Image, Preview)
 * are intentionally light — the side-effect dispatch handles the
 * actual panel/editor opening, the chat just shows a brief notice.
 *
 * Unknown types fall through to `result.message` as a system
 * message so future server-side type additions don't break the
 * client.
 *
 * Why a host-side renderer (not webview-side)?
 *   - The webview is a sandboxed iframe-like context. The host
 *     already owns all backend interaction (executeCommand,
 *     side-effects → vscode.* APIs). Centralising rendering on the
 *     host means one place to add a new result type, one place to
 *     debug, one place where the JS/TS formatters can be reused.
 *   - The webview stays a thin display: receives postMessage with
 *     pre-formatted content, renders to DOM. Same as today.
 */

import type { CommandResultPayload } from './httpClient';


/** Minimal interface the renderer needs from the panel host. */
export interface RendererHost {
    /** Post a `{type: 'systemMessage' | 'error', content}` message. */
    postSystemMessage(content: string, level?: 'info' | 'warning' | 'error'): void;
    /** Post an arbitrary message to the webview (for non-text results). */
    postToWebview(msg: Record<string, unknown>): void;
}


/**
 * Render a CommandResult envelope payload by sending the appropriate
 * messages to the webview. The webview already knows how to display
 * `systemMessage` / `error` / etc. — this class just translates
 * `result.type` → the right shape.
 */
export class CommandRenderer {
    private _host: RendererHost;

    constructor(host: RendererHost) {
        this._host = host;
    }

    render(result: CommandResultPayload | null | undefined): void {
        if (!result || typeof result !== 'object') return;
        const type = result.type || 'TextResult';
        try {
            this._dispatch(type, result);
        } catch (e) {
            console.warn('[ppxai commandRenderer] dispatch failed for', type, e);
            this._host.postSystemMessage(
                result.message || `(unhandled result: ${type})`,
            );
        }
    }

    private _dispatch(type: string, result: CommandResultPayload): void {
        switch (type) {
            case 'NotificationResult': {
                const level =
                    result.status === 'error' ? 'error'
                    : result.status === 'warning' ? 'warning'
                    : 'info';
                this._host.postSystemMessage(result.message || '', level);
                return;
            }

            case 'ConfirmationResult':
                this._host.postSystemMessage(result.message || '');
                return;

            case 'ErrorResult': {
                const lines = [result.message || 'Error'];
                if (Array.isArray(result.suggestions) && result.suggestions.length) {
                    lines.push(...result.suggestions);
                }
                this._host.postSystemMessage(lines.join('\n'), 'error');
                return;
            }

            case 'MarkdownResult': {
                const body = (result.content as string) || result.message || '';
                this._host.postSystemMessage(body);
                return;
            }

            case 'TextResult': {
                // Strip Rich console markup tags (the TUI variant).
                // Factory's HTTP-aware handlers return MarkdownResult
                // instead, but if a TextResult slips through we
                // sanitize so [bold] / [cyan] don't render literally.
                const text = (result.message || '').replace(/\[\/?[^\]]+\]/g, '');
                this._host.postSystemMessage(text);
                return;
            }

            case 'TableResult':
                this._host.postSystemMessage(this._formatTable(result));
                return;

            case 'TreeResult':
                this._host.postSystemMessage(this._formatTree(result));
                return;

            case 'KeyValueResult':
                this._host.postSystemMessage(this._formatKeyValue(result));
                return;

            case 'ListResult': {
                const lines = [`**${result.message}**`, ''];
                const items = (result.items as Array<Record<string, unknown>>) || [];
                for (const item of items) {
                    const text = (item.text || item.label || '') as string;
                    const icon = item.icon ? `${item.icon} ` : '';
                    lines.push(`- ${icon}${text}`);
                }
                this._host.postSystemMessage(lines.join('\n'));
                return;
            }

            // Types whose payload is rendered by their side-effect.
            // The chat just shows a brief notice; the open_viewer /
            // open_editor / show_image / open_html_preview side-effect
            // does the actual panel/editor opening.
            case 'FileViewResult':
            case 'ImageResult':
            case 'PreviewResult':
                if (result.message) {
                    this._host.postSystemMessage(result.message);
                }
                return;

            case 'CompositeResult': {
                // v1.18.3 Item 16: /usage returns CompositeResult when
                // provider throttle counters are non-empty (usage table
                // + errors table). Render top-level message (if any)
                // then recurse into each sub-result through the same
                // dispatch — matches Rich + Textual + web behaviour.
                if (result.message) {
                    this._host.postSystemMessage(result.message);
                }
                const subs = Array.isArray(result.results)
                    ? (result.results as CommandResultPayload[])
                    : [];
                for (const sub of subs) {
                    this.render(sub);
                }
                return;
            }

            default:
                // Unknown type — open enum, ignore gracefully.
                if (result.message) {
                    this._host.postSystemMessage(result.message);
                }
        }
    }

    private _formatTable(result: CommandResultPayload): string {
        const cols = (result.columns as string[]) || [];
        const rows = (result.rows as string[][]) || [];
        if (!cols.length) {
            return result.message || '(empty table)';
        }
        const lines: string[] = [];
        if (result.message) lines.push(`**${result.message}**`, '');
        // Markdown table
        lines.push('| ' + cols.join(' | ') + ' |');
        lines.push('|' + cols.map(() => '---').join('|') + '|');
        for (const row of rows) {
            lines.push('| ' + row.map(c => String(c ?? '')).join(' | ') + ' |');
        }
        return lines.join('\n');
    }

    private _formatTree(result: CommandResultPayload): string {
        const root = result.root as { label?: string; children?: any[] } | undefined;
        if (!root) return result.message || '';
        const lines: string[] = [];
        if (result.message) lines.push(`**${result.message}**`, '');
        const walk = (node: { label?: string; children?: any[] }, depth: number) => {
            const indent = '  '.repeat(depth);
            lines.push(`${indent}- ${node.label || ''}`);
            for (const child of (node.children || [])) walk(child, depth + 1);
        };
        walk(root, 0);
        return lines.join('\n');
    }

    private _formatKeyValue(result: CommandResultPayload): string {
        const pairs = (result.pairs as Record<string, string>) || {};
        const lines: string[] = [];
        if (result.message) lines.push(`**${result.message}**`, '');
        for (const [k, v] of Object.entries(pairs)) {
            lines.push(`- **${k}:** ${v}`);
        }
        return lines.join('\n');
    }
}
