/**
 * SideEffectsHandler — kind→DOM-action dispatcher (v1.18.1).
 *
 * The factory emits side-effects with the user's intent named, not
 * the rendering. Web translates each kind to a panel push, a
 * navigator.clipboard.writeText, a file-tree refresh, etc.
 *
 * Open enum: unknown kinds are silently ignored. That's how
 * `vscode_delegate` (VSCode-only) and any future client-specific
 * kinds stay non-breaking — web just sees one it doesn't know
 * and skips it.
 *
 * Usage:
 *   const handler = new SideEffectsHandler(app);
 *   handler.apply(envelope.side_effects);   // or events[] for live SSE
 */
class SideEffectsHandler {
    /** @param {PpxaiApp} app */
    constructor(app) {
        this.app = app;
    }

    /**
     * Apply an array of side-effects in order.
     *
     * Per-handler errors are caught + logged; one bad side-effect
     * shouldn't take down the whole batch (e.g. clipboard denied
     * by browser permissions shouldn't prevent the file-tree
     * refresh that came after it).
     */
    apply(sideEffects) {
        if (!Array.isArray(sideEffects)) return;
        for (const se of sideEffects) {
            if (!se || typeof se !== 'object') continue;
            const kind = se.kind;
            const handler = SideEffectsHandler._handlers[kind];
            if (!handler) {
                // Open enum — unknown kinds are intentional no-ops.
                console.debug('[SideEffects] ignoring unknown kind:', kind);
                continue;
            }
            try {
                handler.call(this, se);
            } catch (e) {
                console.warn('[SideEffects] handler failed for', kind, e);
            }
        }
    }
}

SideEffectsHandler._handlers = {
    // ─── File / editor / viewer ──────────────────────────────────────────
    open_editor({filepath, line, column}) {
        if (!this.app.rightPanelFrame) return;
        const opts = {mode: 'edit'};
        if (line) opts.line = line;
        if (column) opts.col = column;
        if (typeof CodeEditorView !== 'undefined') {
            this.app.rightPanelFrame.push(new CodeEditorView(filepath, this.app.state, opts));
            this.app.elements?.resizeHandle?.classList.remove('hidden');
        }
    },

    open_viewer({filepath}) {
        // displayFileFromEvent picks the right view by extension
        // (CodeEditor read-only, Markdown, Data, Image, PDF).
        if (typeof this.app.displayFileFromEvent === 'function') {
            this.app.displayFileFromEvent(filepath);
        }
    },

    show_image({filepath}) {
        if (typeof this.app.displayFileFromEvent === 'function') {
            this.app.displayFileFromEvent(filepath);
        }
    },

    show_pdf({filepath}) {
        if (typeof this.app.displayFileFromEvent === 'function') {
            this.app.displayFileFromEvent(filepath);
        }
    },

    reveal_in_explorer() {
        // Web's file tree doesn't support "scroll to entry" yet —
        // a simple refresh is the closest equivalent. VSCode honors
        // this kind natively via revealInExplorer.
        if (this.app._fileTree) this.app._fileTree.refresh(true);
    },

    // ─── Terminal ────────────────────────────────────────────────────────
    open_terminal() {
        if (!this.app.rightPanelFrame) {
            this.app.showError('Right panel not available');
            return;
        }
        if (typeof TerminalView === 'undefined') {
            this.app.showError('Terminal not available — xterm.js not loaded');
            return;
        }
        const view = new TerminalView(this.app.serverUrl, this.app.sessionId);
        this.app.rightPanelFrame.push(view);
        this.app.elements?.resizeHandle?.classList.remove('hidden');
    },

    run_shell({command, cwd}) {
        // Open a terminal with the command pre-typed. xterm.js
        // doesn't have a public "send text" API exposed via
        // TerminalView yet — for now, open the terminal and
        // surface the command so the user can re-run it.
        SideEffectsHandler._handlers.open_terminal.call(this, {});
        if (command) {
            this.app.showSystemMessage(`Run in terminal: \`${command}\``);
        }
    },

    // ─── HTML preview ────────────────────────────────────────────────────
    open_html_preview({filepath, url, served, proxied}) {
        if (typeof this.app.openHtmlPreview === 'function') {
            this.app.openHtmlPreview(filepath, url || null, !!proxied);
        }
    },

    // ─── File tree ───────────────────────────────────────────────────────
    refresh_file_tree() {
        if (this.app._fileTree) {
            this.app._fileTree.refresh(true);
        }
    },

    // ─── Theme ───────────────────────────────────────────────────────────
    set_theme({name}) {
        if (!['dark', 'light', 'system'].includes(name)) return;
        this.app.state.theme = name;
        if (typeof this.app.applyTheme === 'function') {
            this.app.applyTheme();
        }
        try {
            localStorage.setItem('ppxai-theme', name);
        } catch (_) {
            // private mode / quota — ignore
        }
    },

    // ─── Clipboard ───────────────────────────────────────────────────────
    copy_to_clipboard({text}) {
        if (text == null) return;
        if (navigator.clipboard?.writeText) {
            navigator.clipboard.writeText(text).catch(e => {
                console.warn('[SideEffects] clipboard write failed', e);
            });
        }
    },

    // ─── Attach (engine already attached; refresh UI indicator) ──────────
    attach_file() {
        if (typeof this.app.updateContextInfo === 'function') {
            this.app.updateContextInfo();
        }
    },

    // ─── Quick-pick prompt ───────────────────────────────────────────────
    prompt_quick_pick({title, items, command_to_resume}) {
        if (!Array.isArray(items) || !items.length) return;

        // Render as a chat message with clickable buttons. The
        // chosen value gets re-issued via dispatcher as
        // /<command_to_resume> <value>. Per ADR Q3 (b): no server
        // continuation state; the value IS the next args.
        const escaped = (s) => String(s).replace(/[&<>"']/g, c =>
            ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c])
        );
        const buttons = items.map((it, i) => {
            const label = escaped(it.label);
            const value = escaped(it.value);
            return (
                `<button class="qp-item" ` +
                `data-cmd="${escaped(command_to_resume)}" ` +
                `data-value="${value}">` +
                `${label}</button>`
            );
        }).join(' ');
        const html = `**${escaped(title || 'Pick one')}**\n\n${buttons}`;
        this.app.addMessage('system', html);

        // Wire click delegation once. Re-binding on every prompt
        // would leak listeners; check a sentinel.
        if (!SideEffectsHandler._quickPickWired) {
            SideEffectsHandler._quickPickWired = true;
            document.addEventListener('click', (e) => {
                const btn = e.target.closest('.qp-item');
                if (!btn) return;
                const cmd = btn.dataset.cmd;
                const value = btn.dataset.value;
                if (!cmd) return;
                // Resume the command with the chosen value as args.
                if (window.ppxai?.commandDispatcher?.dispatch) {
                    window.ppxai.commandDispatcher.dispatch(`/${cmd} ${value}`);
                }
            });
        }
    },

    // ─── Notify ──────────────────────────────────────────────────────────
    notify({level, message}) {
        if (!message) return;
        if (level === 'error') {
            this.app.showError(message);
        } else if (level === 'warn' || level === 'warning') {
            this.app.showSystemMessage(message, 'warning');
        } else {
            this.app.showSystemMessage(message);
        }
    },

    // ─── VSCode-only escape hatch — web ignores ──────────────────────────
    vscode_delegate() {
        // Intentional no-op. VSCode's side-effect handler maps
        // this to vscode.commands.executeCommand(payload.command,
        // ...payload.args); web has no equivalent.
    },
};

// Sentinel so the click listener is bound exactly once.
SideEffectsHandler._quickPickWired = false;


// CommonJS export for tests; window-global for browser.
if (typeof module !== 'undefined' && module.exports) {
    module.exports = { SideEffectsHandler };
} else if (typeof window !== 'undefined') {
    window.SideEffectsHandler = SideEffectsHandler;
}
