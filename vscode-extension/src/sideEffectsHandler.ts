/**
 * SideEffectsHandler — v1.18.1 envelope side_effects → VSCode APIs.
 *
 * The factory emits side-effects with the user's intent named, not
 * the rendering. VSCode delegates to first-party APIs whenever
 * possible: createTerminal for `open_terminal` (so the user gets
 * their shell + profile + history), showTextDocument for
 * `open_editor` (so they inherit IntelliSense, debugging, multi-
 * cursor, breakpoints), executeCommand('vscode.open', uri) for
 * `show_image`/`show_pdf` (so installed extensions handle non-text
 * formats).
 *
 * Mirrors the web's ppxai/web/shared/side-effects.js — same kinds,
 * same payload shapes, different rendering. The cross-client kind
 * sentinel in tests/test_command_envelope.py and the audit table
 * in docs/TODO-v1.18.1-command-unification.md keep the two sides
 * in lockstep.
 *
 * The webview never invokes vscode.* APIs directly (sandboxed). It
 * forwards side_effects to the extension host via postMessage, and
 * this class on the host translates them to API calls.
 */

import * as vscode from 'vscode';
import * as pathModule from 'path';

import type { SideEffectEntry } from './httpClient';

/**
 * Minimal interface the side-effects handler needs from the panel.
 * Avoids importing the full ChatViewProvider class so this module
 * stays independently compileable. ChatViewProvider implements
 * this interface in chatPanel.ts (5b ties the wiring together).
 */
export interface SideEffectHost {
    getWorkingDirHint(): string | undefined;
    openHtmlPreviewFromSideEffect(filepath: string, url?: string): void;
    postToWebview(msg: Record<string, unknown>): void;
    dispatchCommandFromSideEffect(cmd: string, args: string): Promise<void>;
}

/** Kind names — keep in sync with ppxai/commands/results.py::SideEffectKind. */
export const KIND = {
    OPEN_EDITOR: 'open_editor',
    OPEN_VIEWER: 'open_viewer',
    SHOW_IMAGE: 'show_image',
    SHOW_PDF: 'show_pdf',
    REVEAL_IN_EXPLORER: 'reveal_in_explorer',
    OPEN_TERMINAL: 'open_terminal',
    RUN_SHELL: 'run_shell',
    OPEN_HTML_PREVIEW: 'open_html_preview',
    REFRESH_FILE_TREE: 'refresh_file_tree',
    SET_THEME: 'set_theme',
    COPY_TO_CLIPBOARD: 'copy_to_clipboard',
    ATTACH_FILE: 'attach_file',
    PROMPT_QUICK_PICK: 'prompt_quick_pick',
    NOTIFY: 'notify',
    VSCODE_DELEGATE: 'vscode_delegate',
} as const;


/**
 * Resolve a relpath against a working dir if not absolute. Used by
 * file-handling kinds (open_editor, open_viewer, show_image, etc.)
 * — the engine emits absolute paths usually, but we tolerate
 * relpaths for safety.
 */
function _resolvePath(filepath: string, workingDir?: string): string {
    if (pathModule.isAbsolute(filepath)) return filepath;
    if (workingDir) return pathModule.resolve(workingDir, filepath);
    return filepath;
}


export class SideEffectsHandler {
    private _provider: SideEffectHost;

    constructor(provider: SideEffectHost) {
        this._provider = provider;
    }

    /**
     * Apply an array of side-effects. Per-handler errors are
     * caught and logged; one bad effect (e.g. clipboard denied)
     * doesn't take down the rest of the batch.
     */
    async apply(sideEffects: SideEffectEntry[] | undefined): Promise<void> {
        if (!Array.isArray(sideEffects) || sideEffects.length === 0) return;
        for (const se of sideEffects) {
            if (!se || typeof se !== 'object' || !se.kind) continue;
            try {
                await this._applyOne(se);
            } catch (e) {
                console.warn('[ppxai sideEffects] handler failed for', se.kind, e);
            }
        }
    }

    private async _applyOne(se: SideEffectEntry): Promise<void> {
        const workingDir = this._provider.getWorkingDirHint();
        switch (se.kind) {
            case KIND.OPEN_EDITOR: {
                // User wants to edit this file. Open in primary
                // editor column, NOT preview mode (so it doesn't
                // get replaced by the next click).
                const filepath = _resolvePath(se.filepath as string, workingDir);
                const uri = vscode.Uri.file(filepath);
                const doc = await vscode.workspace.openTextDocument(uri);
                const editor = await vscode.window.showTextDocument(doc, {
                    viewColumn: vscode.ViewColumn.One,
                    preview: false,
                });
                const line = (se.line as number) ?? 0;
                const col = (se.column as number) ?? 0;
                if (line > 0) {
                    const pos = new vscode.Position(
                        Math.max(0, line - 1),
                        Math.max(0, col - 1)
                    );
                    editor.selection = new vscode.Selection(pos, pos);
                    editor.revealRange(
                        new vscode.Range(pos, pos),
                        vscode.TextEditorRevealType.InCenter
                    );
                }
                return;
            }

            case KIND.OPEN_VIEWER: {
                // Read-only view: preview mode, beside column, so
                // installed PDF / CSV / image extensions can take
                // over for non-text files.
                const filepath = _resolvePath(se.filepath as string, workingDir);
                const uri = vscode.Uri.file(filepath);
                await vscode.commands.executeCommand('vscode.open', uri, {
                    preview: true,
                    viewColumn: vscode.ViewColumn.Beside,
                });
                return;
            }

            case KIND.SHOW_IMAGE:
            case KIND.SHOW_PDF: {
                // Same delegation: vscode.open → user's installed
                // image/PDF extension handles the rendering.
                const filepath = _resolvePath(se.filepath as string, workingDir);
                const uri = vscode.Uri.file(filepath);
                await vscode.commands.executeCommand('vscode.open', uri, {
                    preview: true,
                    viewColumn: vscode.ViewColumn.Beside,
                });
                return;
            }

            case KIND.REVEAL_IN_EXPLORER: {
                const filepath = _resolvePath(se.filepath as string, workingDir);
                const uri = vscode.Uri.file(filepath);
                await vscode.commands.executeCommand('revealInExplorer', uri);
                return;
            }

            case KIND.OPEN_TERMINAL: {
                const cwd = (se.cwd as string) || workingDir;
                const term = vscode.window.createTerminal({
                    name: 'ppxai',
                    cwd: cwd && cwd !== '.' ? cwd : undefined,
                    iconPath: new vscode.ThemeIcon('terminal'),
                });
                term.show();
                return;
            }

            case KIND.RUN_SHELL: {
                // open_terminal AND pre-type a command. Mirrors the
                // existing chatPanel.ts:runCommandInTerminal pattern
                // (preserved through the migration per the audit
                // table in docs/TODO-v1.18.1-command-unification.md).
                const cwd = (se.cwd as string) || workingDir;
                const cmd = se.command as string;
                if (!cmd) return;
                const shortCmd = cmd.length > 30 ? cmd.substring(0, 30) + '...' : cmd;
                const term = vscode.window.createTerminal({
                    name: `ppxai: ${shortCmd}`,
                    cwd: cwd && cwd !== '.' ? cwd : undefined,
                    iconPath: new vscode.ThemeIcon('terminal'),
                });
                term.show();
                term.sendText(cmd);
                return;
            }

            case KIND.OPEN_HTML_PREVIEW: {
                // Existing previewPanel.ts WebviewPanel handles this.
                // Keep the existing surface; don't re-wire here.
                const filepath = se.filepath as string;
                const url = se.url as string | undefined;
                this._provider.openHtmlPreviewFromSideEffect(filepath, url);
                return;
            }

            case KIND.REFRESH_FILE_TREE: {
                // VSCode's file watcher usually catches changes
                // automatically. The explicit refresh covers cases
                // where the watcher lags (e.g. cd to a dir VSCode
                // doesn't have a workspace folder for).
                await vscode.commands.executeCommand(
                    'workbench.files.action.refreshFilesExplorer'
                );
                return;
            }

            case KIND.SET_THEME: {
                // Webview-only theme (the chat panel's CSS class).
                // VSCode's editor theme is independent of this and
                // controlled via the user's settings — we don't
                // touch it. Forward to the webview.
                this._provider.postToWebview({
                    type: 'setTheme',
                    name: se.name,
                });
                return;
            }

            case KIND.COPY_TO_CLIPBOARD: {
                const text = se.text as string;
                if (text != null) {
                    await vscode.env.clipboard.writeText(text);
                }
                return;
            }

            case KIND.ATTACH_FILE: {
                // Engine has already taken ownership of the file
                // (factory's /attach handler does the read + queue).
                // Tell the webview to refresh its attachment chip
                // strip so the user sees the new file in the UI.
                this._provider.postToWebview({
                    type: 'attachmentAdded',
                    filepath: se.filepath,
                    file_kind: se.file_kind,
                });
                return;
            }

            case KIND.PROMPT_QUICK_PICK: {
                // Native QuickPick. Per ADR Q3 (b): the chosen
                // value IS the literal next args. Re-issue the
                // command via the dispatcher.
                const items = (se.items as Array<{label: string; value: string}>) || [];
                if (items.length === 0) return;
                const picked = await vscode.window.showQuickPick(
                    items.map(it => ({
                        label: it.label,
                        // Cache the resume value on description so
                        // the .label match is unambiguous; we read
                        // it back below.
                        description: '',
                        _value: it.value,
                    } as vscode.QuickPickItem & { _value: string })),
                    { placeHolder: (se.title as string) || 'Pick one' }
                );
                if (!picked) return;
                const value = (picked as any)._value;
                const cmd = se.command_to_resume as string;
                if (cmd && value != null) {
                    await this._provider.dispatchCommandFromSideEffect(cmd, value);
                }
                return;
            }

            case KIND.NOTIFY: {
                const message = (se.message as string) || '';
                if (!message) return;
                const level = (se.level as string) || 'info';
                if (level === 'error') vscode.window.showErrorMessage(message);
                else if (level === 'warn' || level === 'warning')
                    vscode.window.showWarningMessage(message);
                else vscode.window.showInformationMessage(message);
                return;
            }

            case KIND.VSCODE_DELEGATE: {
                // Escape hatch: invoke an arbitrary VSCode command.
                // Use sparingly; prefer adding a stable kind when
                // web has parity.
                const command = se.command as string;
                const args = (se.args as unknown[]) || [];
                if (!command) return;
                await vscode.commands.executeCommand(command, ...args);
                return;
            }

            default:
                // Open enum — unknown kinds are intentional no-ops.
                console.debug('[ppxai sideEffects] ignoring unknown kind:', se.kind);
        }
    }
}
