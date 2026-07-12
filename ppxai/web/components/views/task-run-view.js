/**
 * TaskRunView — RightPanelFrame pane for a tool-capable /v1/agent/task run.
 *
 * The dense variant of AgentRunView (v1.19.x build plan T1): on top of the
 * oneshot pane's status chip + result body it adds
 *   - a meta bar (provider/model, tool-grant chips, egress chips, budget),
 *   - a live events log (tool_call / tool_denied / network_* / spawn_*),
 *   - a Cancel button while the run is non-terminal,
 *   - a consent card while the run is parked in `waiting` (T5): prompt +
 *     Approve/Deny + an optional note field, wired to POST .../respond via
 *     the controller (setOnRespond).
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
        this._onRespond = null;
        this._onAck = null;
        this._onResume = null;
        this._waiting = null;   // {kind, prompt, token, …} while parked (T5)
        this._resumable = false; // T7: server-judged clean checkpoint
        this._metaEl = null;
        this._eventsEl = null;
        this._consentEl = null;
        this._cancelBtn = null;
        this._ackBtn = null;
        this._resumeBtn = null;
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
            pending: 'pending', running: 'running…', waiting: '✋ waiting',
            cancelling: 'cancelling…',
            completed: '✅ completed',
            completed_pending_ack: '📬 result ready', finalized: '✅ collected',
            failed: '❌ failed',
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
            +   `<button class="task-ack-btn" type="button" title="Collect the held result (finalize this run)">Collect</button>`
            +   `<button class="task-resume-btn" type="button" title="Continue this run from its checkpoint">Resume</button>`
            +   `<button class="task-cancel-btn" type="button" title="Cancel this run">Cancel</button>`
            + `</div>`
            + (this._task ? `<div class="agent-run-task">${esc(this._task)}</div>` : '')
            + `<div class="task-run-meta"></div>`
            + `<div class="task-run-consent"></div>`
            + `<div class="task-run-events" aria-label="Live events"></div>`
            + `<div class="agent-run-body">${this._bodyHtml}</div>`
            + `</div>`;
        this._statusEl = container.querySelector('.agent-run-status');
        this._bodyEl = container.querySelector('.agent-run-body');
        this._metaEl = container.querySelector('.task-run-meta');
        this._consentEl = container.querySelector('.task-run-consent');
        this._eventsEl = container.querySelector('.task-run-events');
        this._cancelBtn = container.querySelector('.task-cancel-btn');
        if (this._cancelBtn) {
            this._cancelBtn.addEventListener('click', () => { if (this._onCancel) this._onCancel(); });
        }
        this._ackBtn = container.querySelector('.task-ack-btn');
        if (this._ackBtn) {
            this._ackBtn.addEventListener('click', () => { if (this._onAck) this._onAck(); });
        }
        this._resumeBtn = container.querySelector('.task-resume-btn');
        if (this._resumeBtn) {
            this._resumeBtn.addEventListener('click', () => { if (this._onResume) this._onResume(); });
        }
        this._renderMeta();
        this._renderConsent();
        this._renderEvents();
        this._syncCancelBtn();
        this._syncAckBtn();
        this._syncResumeBtn();
    }

    unmount() {
        super.unmount();  // clears the DOM, keeps render state
        this._metaEl = null;
        this._eventsEl = null;
        this._consentEl = null;
        this._cancelBtn = null;
        this._ackBtn = null;
        this._resumeBtn = null;
    }

    // ── Controller hooks ──────────────────────────────────────────────────────

    /** Wire the Cancel button to the controller (idempotent). */
    setOnCancel(fn) { this._onCancel = fn; }

    /** Wire the consent card's Approve/Deny to the controller (T5). */
    setOnRespond(fn) { this._onRespond = fn; }

    /** Wire the Collect button (T6: ack a held result) to the controller. */
    setOnAck(fn) { this._onAck = fn; }

    /** Wire the Resume button (T7: continue from checkpoint) to the controller. */
    setOnResume(fn) { this._onResume = fn; }

    /** Drop the consent card (park answered elsewhere / run resumed). */
    clearWaiting() {
        this._waiting = null;
        this._renderConsent();
    }

    /** Merge grant/egress/budget/provider/model (+ status + waiting + resumable)
     *  and re-render. */
    setMeta(meta) {
        if (!meta) return;
        this._absorbMeta(meta);
        // T7: the server-judged resumable flag gates the Resume button.
        if (Object.prototype.hasOwnProperty.call(meta, 'resumable')) {
            this._resumable = Boolean(meta.resumable);
            this._syncResumeBtn();
        }
        // T5: a registry meta always carries `waiting` (null unless parked);
        // only touch card state when the key is present so an optimistic
        // client-side paneInfo (no waiting key) can't wipe a live card.
        if (Object.prototype.hasOwnProperty.call(meta, 'waiting')) {
            this._waiting = meta.waiting || null;
            this._renderConsent();
        }
        if (meta.status) this.setStatus(meta.status);
        this._renderMeta();
    }

    /** Append one streamed run event to the live log. */
    appendEvent(ev) {
        if (!ev || !ev.type) return;
        // T5: the consent lifecycle drives the card as it streams by — a park
        // raises it (token rides in the event data), a resume drops it. Both
        // also fall through into the log as transcript lines.
        if (ev.type === 'agent_waiting') {
            this._waiting = ev.data || null;
            this._renderConsent();
        } else if (ev.type === 'agent_resumed'
                   || ev.type === 'agent_run_interrupted'
                   || ev.type === 'agent_run_cancelled'
                   || ev.type === 'agent_run_error') {
            // A park cannot outlive the run's in-memory future (registry
            // rule): an interrupt/cancel/error invalidates it just as a
            // respond does. Matters on RESUME — a run killed WHILE PARKED
            // has agent_waiting with no agent_resumed in its replayed
            // backlog; without this drop, the replay raises a card carrying
            // the DEAD pre-restart token and clicking it 409s (live
            // 2026-07-12). Replay order self-corrects: stale waiting raises,
            // the interrupted right behind it drops, the fresh live park
            // raises the valid card.
            this._waiting = null;
            this._renderConsent();
        }
        // The log is a transcript of what the agent DID (tools, egress, spawns).
        // Heartbeats (agent_beat) would spam a long run, and run lifecycle is
        // already conveyed by the status badge — so drop both here. Exceptions:
        // finalized (T6) and resume (T7) are one-shot USER actions worth a
        // transcript line, not chatter.
        const keep = ev.type === 'agent_run_finalized' || ev.type === 'agent_run_resume';
        if (!keep && (ev.type === 'agent_beat' || ev.type.startsWith('agent_run_'))) return;
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
        // Any move off `waiting` means the park is over — drop a stale card
        // (covers a poll/refresh observing the resume without the SSE event).
        if (status && status !== 'waiting' && this._waiting) {
            this._waiting = null;
            this._renderConsent();
        }
        this._syncCancelBtn();
        this._syncAckBtn();
        this._syncResumeBtn();
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

    /** Collect is visible ONLY while a result is held (T6). */
    _syncAckBtn() {
        if (!this._ackBtn) return;
        this._ackBtn.style.display =
            this._status === 'completed_pending_ack' ? '' : 'none';
    }

    /** Resume is visible ONLY for a resumable interrupted/cancelled run (T7). */
    _syncResumeBtn() {
        if (!this._resumeBtn) return;
        const eligible = this._resumable
            && (this._status === 'interrupted' || this._status === 'cancelled');
        this._resumeBtn.style.display = eligible ? '' : 'none';
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

    /** Render (or clear) the T5 consent card from `this._waiting`.
     * Built with DOM methods + textContent (never innerHTML): the prompt is
     * model-derived text (the spawn summary embeds the child task), so it is
     * UNTRUSTED and must not be interpreted as markup. */
    _renderConsent() {
        if (!this._consentEl) return;
        this._consentEl.textContent = '';
        if (!this._waiting) return;
        const w = this._waiting;
        const title = document.createElement('div');
        title.className = 'task-consent-title';
        title.textContent = `✋ ${w.kind || 'consent'} needed`;
        const prompt = document.createElement('div');
        prompt.className = 'task-consent-prompt';
        prompt.textContent = w.prompt || '';
        const actions = document.createElement('div');
        actions.className = 'task-consent-actions';
        const note = document.createElement('input');
        note.className = 'task-consent-note';
        note.type = 'text';
        note.placeholder = 'optional note…';
        const send = (approved) => {
            if (!this._onRespond) return;
            const payload = { token: w.token, approved };
            const txt = (note.value || '').trim();
            if (txt) payload.text = txt;
            this._onRespond(payload);
        };
        const mkBtn = (cls, label, approved) => {
            const b = document.createElement('button');
            b.className = cls;
            b.type = 'button';
            b.textContent = label;
            b.addEventListener('click', () => send(approved));
            return b;
        };
        actions.appendChild(note);
        actions.appendChild(mkBtn('task-consent-approve', 'Approve', true));
        actions.appendChild(mkBtn('task-consent-deny', 'Deny', false));
        this._consentEl.appendChild(title);
        this._consentEl.appendChild(prompt);
        this._consentEl.appendChild(actions);
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
            case 'agent_waiting':     return `✋ waiting (${d.kind || 'consent'}): ${TaskRunView._short(d.prompt, 80)}`;
            case 'agent_resumed':     return `▶ resumed — ${d.approved ? 'approved' : 'denied'}${d.via === 'timeout' ? ' (timed out)' : ''}`;
            case 'agent_result_ready':   return `📬 result ready (${d.chars || 0} chars) — collect via the button or /task ack`;
            case 'agent_run_finalized':  return `✅ collected${d.via === 'retention' ? ' (retention expired)' : ''}`;
            case 'agent_run_resume':     return `▶️ resumed (was ${d.from || 'interrupted'})`;
            case 'subagent_spawned':  return `⑂ sub-agent ${d.child_run_id || ''}`;
            case 'subagent_finished': return `⑂ sub-agent ${d.status || 'done'}`;
            default: return String(ev.type);
        }
    }
}

TaskRunView._TERMINAL = new Set([
    'completed', 'completed_pending_ack', 'finalized',
    'failed', 'cancelled', 'interrupted',
]);
// Max live-log lines kept in the array AND the DOM (bounded in lock-step).
TaskRunView._MAX_LOG_EVENTS = 200;

// Browser global export
if (typeof window !== 'undefined') {
    window.TaskRunView = TaskRunView;
}
