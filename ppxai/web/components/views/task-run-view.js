/**
 * TaskRunView — RightPanelFrame pane for a tool-capable /v1/agent/task run.
 *
 * The dense variant of AgentRunView (v1.19.x build plan T1): on top of the
 * oneshot pane's status chip + result body it adds
 *   - a meta bar (provider/model, tool-grant chips, egress chips, budget),
 *   - a live events log (tool_call / tool_denied / network_* / spawn_*),
 *   - a Cancel button while the run is non-terminal.
 *
 * Render state (status, body, meta, events) is held on the instance and
 * rebuilt in mount(), so the pane survives RightPanelFrame re-mounts — the
 * same contract AgentRunView relies on.
 *
 * @version 1.19.0
 */
class TaskRunView extends AgentRunView {
    /**
     * @param {string} runId
     * @param {string} task
     * @param {object} appState
     * @param {object} [meta] - {tools[], network[], budget{}, provider, model, status}
     */
    constructor(runId, task, appState, meta) {
        super(runId, task, appState);
        this._meta = null;
        this._events = [];
        this._onCancel = null;
        this._metaEl = null;
        this._eventsEl = null;
        this._cancelBtn = null;
        if (meta) this._absorbMeta(meta);
        if (meta && meta.status) this._status = meta.status;
    }

    getIcon() { return '🛠️'; }

    getTitle() {
        const t = (this._task || '').trim();
        const label = t ? (t.length > 30 ? t.slice(0, 30) + '…' : t) : this._runId;
        return `🛠️ ${label}`;
    }

    // ── Status vocabulary (richer than the oneshot pane) ──────────────────────

    _statusLabel(status) {
        return {
            pending: 'pending', running: 'running…', cancelling: 'cancelling…',
            completed: '✅ completed', failed: '❌ failed',
            cancelled: '⏹️ cancelled', interrupted: '⏸️ interrupted',
        }[status] || status;
    }

    // ── BaseView protocol ─────────────────────────────────────────────────────

    mount(container) {
        this._container = container;
        const esc = (typeof escapeHtml === 'function') ? escapeHtml : (s) => s;
        container.innerHTML =
            `<div class="task-run-view">`
            + `<div class="agent-run-header">`
            +   `<span class="agent-run-id" title="${esc(this._runId)}">${esc(this._runId)}</span>`
            +   `<span class="agent-run-status" data-status="${esc(this._status)}">`
            +     `${esc(this._statusLabel(this._status))}</span>`
            +   `<button class="task-cancel-btn" type="button" title="Cancel this run">Cancel</button>`
            + `</div>`
            + (this._task ? `<div class="agent-run-task">${esc(this._task)}</div>` : '')
            + `<div class="task-run-meta"></div>`
            + `<div class="task-run-events" aria-label="Live events"></div>`
            + `<div class="agent-run-body">${this._bodyHtml}</div>`
            + `</div>`;
        this._statusEl = container.querySelector('.agent-run-status');
        this._bodyEl = container.querySelector('.agent-run-body');
        this._metaEl = container.querySelector('.task-run-meta');
        this._eventsEl = container.querySelector('.task-run-events');
        this._cancelBtn = container.querySelector('.task-cancel-btn');
        if (this._cancelBtn) {
            this._cancelBtn.addEventListener('click', () => { if (this._onCancel) this._onCancel(); });
        }
        this._renderMeta();
        this._renderEvents();
        this._syncCancelBtn();
    }

    unmount() {
        super.unmount();  // clears the DOM, keeps render state
        this._metaEl = null;
        this._eventsEl = null;
        this._cancelBtn = null;
    }

    // ── Controller hooks ──────────────────────────────────────────────────────

    /** Wire the Cancel button to the controller (idempotent). */
    setOnCancel(fn) { this._onCancel = fn; }

    /** Merge grant/egress/budget/provider/model (+ status) and re-render. */
    setMeta(meta) {
        if (!meta) return;
        this._absorbMeta(meta);
        if (meta.status) this.setStatus(meta.status);
        this._renderMeta();
    }

    /** Append one streamed run event to the live log. */
    appendEvent(ev) {
        if (!ev || !ev.type) return;
        // The log is a transcript of what the agent DID (tools, egress, spawns).
        // Heartbeats (agent_beat) would spam a long run, and run lifecycle is
        // already conveyed by the status badge — so drop both here.
        if (ev.type === 'agent_beat' || ev.type.startsWith('agent_run_')) return;
        this._events.push(ev);
        if (this._eventsEl) this._appendEventLine(ev);
        // Bound BOTH the backing array AND the DOM: a long run streaming
        // thousands of events would otherwise grow _eventsEl's node count
        // indefinitely and slow the browser (the shift() alone only capped the
        // array — Gemini review). Prune the oldest DOM line in lock-step.
        if (this._events.length > TaskRunView._MAX_LOG_EVENTS) {
            this._events.shift();
            if (this._eventsEl && this._eventsEl.firstChild) {
                this._eventsEl.removeChild(this._eventsEl.firstChild);
            }
        }
    }

    setStatus(status) {
        const ok = super.setStatus(status);
        this._syncCancelBtn();
        return ok;
    }

    // ── Internals ─────────────────────────────────────────────────────────────

    _absorbMeta(meta) {
        const prev = this._meta || {};
        this._meta = {
            tools: meta.tools || prev.tools || [],
            network: meta.network || meta.allow_outbound || prev.network || [],
            budget: meta.budget || prev.budget || {},
            provider: meta.provider || prev.provider || null,
            model: meta.model || prev.model || null,
        };
    }

    _syncCancelBtn() {
        if (!this._cancelBtn) return;
        const done = TaskRunView._TERMINAL.has(this._status) || this._status === 'cancelling';
        this._cancelBtn.style.display = done ? 'none' : '';
    }

    _egressLabel(n) {
        if (typeof n === 'string') return n;
        const paths = (n && n.paths && n.paths[0]) ? n.paths[0] : '';
        return (n && n.host ? n.host : '') + paths;
    }

    _renderMeta() {
        if (!this._metaEl) return;
        const esc = (typeof escapeHtml === 'function') ? escapeHtml : (s) => s;
        const m = this._meta || {};
        const chips = [];
        const modelLabel = [m.provider, m.model].filter(Boolean).join(' · ');
        if (modelLabel) chips.push(`<span class="task-chip task-chip-model">${esc(modelLabel)}</span>`);
        (m.tools || []).forEach((t) => chips.push(`<span class="task-chip task-chip-tool">${esc(t)}</span>`));
        (m.network || []).forEach((n) => chips.push(`<span class="task-chip task-chip-egress">↗ ${esc(this._egressLabel(n))}</span>`));
        const b = m.budget || {};
        const bp = [];
        if (b.iterations) bp.push(`${b.iterations} iters`);
        if (b.time_s) bp.push(`${b.time_s}s`);
        if (b.tokens) bp.push(`${b.tokens} tok`);
        if (bp.length) chips.push(`<span class="task-chip task-chip-budget">⏲ ${esc(bp.join(' · '))}</span>`);
        this._metaEl.innerHTML = chips.join('');
    }

    _renderEvents() {
        if (!this._eventsEl) return;
        this._eventsEl.innerHTML = '';
        this._events.forEach((ev) => this._appendEventLine(ev));
    }

    _appendEventLine(ev) {
        const esc = (typeof escapeHtml === 'function') ? escapeHtml : (s) => s;
        const line = document.createElement('div');
        line.className = `task-event task-event-${esc(String(ev.type || 'x'))}`;
        line.textContent = TaskRunView._eventText(ev);  // textContent → safe
        this._eventsEl.appendChild(line);
        this._eventsEl.scrollTop = this._eventsEl.scrollHeight;
    }

    static _short(s, n) {
        s = String(s == null ? '' : s);
        return s.length > (n || 60) ? s.slice(0, n || 60) + '…' : s;
    }

    static _eventText(ev) {
        const d = ev.data || {};
        switch (ev.type) {
            case 'tool_call':    return `→ ${d.tool || d.name || 'tool'}`;
            case 'tool_result':  return `✓ ${d.tool || 'tool'}  ${TaskRunView._short(d.result)}`;
            case 'tool_denied':  return `⛔ tool denied: ${d.tool || ''} (off-grant)`;
            case 'network_policy_allowed': return `↗ allow ${TaskRunView._short((d.target_host || '') + (d.target_path || ''), 80)}`;
            case 'network_policy_denied':  return `⛔ egress denied ${TaskRunView._short((d.target_host || '') + (d.target_path || ''), 80)}`;
            case 'path_denied':            return `⛔ fs denied (${d.mode || ''}) ${TaskRunView._short(d.target_path, 70)}`;
            case 'spawn_denied':      return `⛔ spawn denied: ${TaskRunView._short(d.reason, 80)}`;
            case 'subagent_spawned':  return `⑂ sub-agent ${d.child_run_id || ''}`;
            case 'subagent_finished': return `⑂ sub-agent ${d.status || 'done'}`;
            default: return String(ev.type);
        }
    }
}

TaskRunView._TERMINAL = new Set(['completed', 'failed', 'cancelled', 'interrupted']);
// Max live-log lines kept in the array AND the DOM (bounded in lock-step).
TaskRunView._MAX_LOG_EVENTS = 200;

// Browser global export
if (typeof window !== 'undefined') {
    window.TaskRunView = TaskRunView;
}
