/**
 * AgentRunView — RightPanelFrame view for a /v1/agent/* background run.
 *
 * v1.19.0 Increment A (web): the experimental `/agentrun` command (the
 * tool-free oneshot tier, POST /v1/agent/run) renders its progress + result
 * HERE, in the right-side split panel, instead of the main chat — so the chat
 * prompt stays interactive while runs execute in the background. One view per
 * run, keyed by run_id via getPath(), so the existing stack chrome (dropdown /
 * back-forward / dedup) navigates between concurrent runs for free.
 *
 * The render state (status + body HTML) is held on the instance and rebuilt in
 * mount(), so the pane survives RightPanelFrame re-mounts — promote (clicking
 * "open"/a run row), back/forward, and focus all re-run mount(), which would
 * otherwise wipe the result back to "Waiting…". (Inc B fix.)
 *
 * Task-tier (POST /v1/agent/task) density — live events log, status badge,
 * cancel button — is a later design iteration. The seams here (setStatus + a
 * dedicated body container) are shaped for it but intentionally not built.
 *
 * @version 1.19.0
 */
class AgentRunView extends BaseView {
    /**
     * @param {string} runId     - The run's id (e.g. "run_909a5e5264aa").
     * @param {string} task      - The task text, used for the title + header.
     * @param {object} appState  - AppState singleton (unused for oneshot; kept
     *                             for parity with file views + future task tier).
     */
    constructor(runId, task, appState) {
        super();
        this._runId    = runId;
        this._task     = task || '';
        this._appState = appState;
        this._container = null;
        this._statusEl  = null;
        this._bodyEl    = null;
        // Render state, held independently of the DOM so a re-mount restores it.
        this._status   = 'running';
        this._bodyHtml = '<div class="rpf-loading">Waiting for result…</div>';
    }

    // ── BaseView protocol ─────────────────────────────────────────────────────

    getTitle() {
        const t = this._task.trim();
        const label = t ? (t.length > 30 ? t.slice(0, 30) + '…' : t) : this._runId;
        return `🤖 ${label}`;
    }

    /** Non-file path: unique per run so dedup gives one view per run_id. */
    getPath() { return `agent://run/${this._runId}`; }

    getIcon() { return '🤖'; }

    mount(container) {
        this._container = container;
        const esc = (typeof escapeHtml === 'function') ? escapeHtml : (s) => s;
        container.innerHTML =
            `<div class="agent-run-view">`
            + `<div class="agent-run-header">`
            +   `<span class="agent-run-id" title="${esc(this._runId)}">${esc(this._runId)}</span>`
            +   `<span class="agent-run-status" data-status="${esc(this._status)}">`
            +     `${esc(this._statusLabel(this._status))}</span>`
            + `</div>`
            + (this._task ? `<div class="agent-run-task">${esc(this._task)}</div>` : '')
            + `<div class="agent-run-body">${this._bodyHtml}</div>`
            + `</div>`;
        this._statusEl = container.querySelector('.agent-run-status');
        this._bodyEl   = container.querySelector('.agent-run-body');
    }

    unmount() {
        // Keep _status/_bodyHtml so a later re-mount restores the content;
        // only drop the DOM references.
        if (this._container) { this._container.innerHTML = ''; this._container = null; }
        this._statusEl = null;
        this._bodyEl   = null;
    }

    // ── Run updates (called by AgentRunController's detached watcher) ──────────

    _statusLabel(status) {
        return { completed: '✅ completed', failed: '❌ failed', running: 'running…' }[status]
            || status;
    }

    /** Update the status chip. Stored so re-mount restores it. @returns {boolean} */
    setStatus(status) {
        this._status = status;
        if (this._statusEl) {
            this._statusEl.textContent = this._statusLabel(status);
            this._statusEl.setAttribute('data-status', status);
        }
        return true;
    }

    /**
     * Render the final result markdown. Always stored (so a re-mount restores
     * it); returns whether it rendered to a LIVE DOM right now — false when the
     * view is unmounted, so a caller can decide on a fallback. Note: a stored
     * result still appears on the next mount as long as the view is on the stack.
     */
    setResult(markdown) {
        const text = markdown || '(empty result)';
        let html;
        try {
            if (typeof DOMPurify !== 'undefined' && typeof marked !== 'undefined') {
                html = DOMPurify.sanitize(marked.parse(text));
            } else if (window.ppxai?.renderMarkdown) {
                html = window.ppxai.renderMarkdown(text);
            } else {
                html = (typeof escapeHtml === 'function') ? escapeHtml(text) : text;
            }
        } catch (e) {
            html = (typeof escapeHtml === 'function') ? escapeHtml(text) : text;
        }
        this._bodyHtml = `<div class="agent-run-result message-content">${html}</div>`;
        if (this._bodyEl) { this._bodyEl.innerHTML = this._bodyHtml; return true; }
        return false;
    }

    /**
     * Render an error. Stored so re-mount restores it; returns whether it
     * rendered to a live DOM right now (false when unmounted).
     */
    setError(message) {
        const esc = (typeof escapeHtml === 'function') ? escapeHtml : (s) => s;
        this._bodyHtml = `<div class="rpf-error">${esc(message || 'Run failed')}</div>`;
        if (this._bodyEl) { this._bodyEl.innerHTML = this._bodyHtml; return true; }
        return false;
    }
}

// Browser global export
if (typeof window !== 'undefined') {
    window.AgentRunView = AgentRunView;
}
