/**
 * SshLauncherView — the ADR 0013 hub's host/server launcher, in the right
 * split pane (RightPanelFrame).
 *
 * Owner design (2026-09-28): a header "🖥 SSH" button, shown only when the
 * local server is a hub (`remote.hosts` set), opens this view beside the chat.
 * It lists the configured hosts and each host's announced ppxai servers, and
 * offers Open / Detach / Stop / New server. **Open opens the remote's own web
 * UI in a new browser tab** (`/h/<host>/<id>/`, one named tab per server, so a
 * second Open focuses the same tab). Leave in that tab detaches and comes back
 * here. Stopping a remote server is only possible from this view, and asks.
 *
 * Data comes from the hub's own API at the page ORIGIN (never a path prefix:
 * the launcher only ever runs on the local page): GET /hub/hosts,
 * GET /hub/hosts/<host>/servers, POST .../servers (launch),
 * POST .../servers/<id>/attach|detach|stop. The hub never returns a token.
 *
 * `renderSshLauncher(model, esc)` is a pure function of the fetched data so
 * tests can run it under node (tests/test_ssh_launcher_view.py).
 *
 * @version 1.19.4
 */

const SSH_LAUNCHER_REFRESH_MS = 10000;

/**
 * Sent on the launcher's session/run-count reads through the proxy: the hub
 * then never auto-attaches (ppxai/server/routes/remote_hub.py). Without it, a
 * refresh whose host list was fetched just before a Detach re-attached the
 * server (found in a live Playwright run, 2026-09-28).
 */
const SSH_LAUNCHER_NO_ATTACH = { 'X-Ppxai-Hub-Attach': 'no' };

/** Run statuses that no longer hold resources (ppxai/engine/agent_runs.py). */
const SSH_LAUNCHER_TERMINAL_RUNS = new Set(
    ['completed', 'completed_pending_ack', 'finalized', 'failed', 'cancelled', 'interrupted']);

/**
 * @param {{hosts: Array, loading?: boolean, error?: string|null,
 *          launching?: object, forms?: object}} model
 * @param {(s: string) => string} esc - HTML escaper
 * @returns {string} HTML
 */
function renderSshLauncher(model, esc) {
    const parts = ['<div class="ssh-launcher">',
        '<div class="ssh-launcher-toolbar">',
        '<span class="ssh-launcher-title">Remote ppxai servers</span>',
        '<button class="ssh-btn" data-action="refresh" title="Refresh">↻ Refresh</button>',
        '</div>'];
    if (model.error) {
        parts.push(`<div class="ssh-error">${esc(model.error)}</div>`);
    }
    if (model.loading && !(model.hosts || []).length) {
        parts.push('<div class="rpf-loading">Loading hosts…</div>');
    }
    for (const host of model.hosts || []) {
        const hostError = host.error || host.listError || null;
        const dot = hostError ? 'ssh-dot-bad' : (host.servers ? 'ssh-dot-ok' : 'ssh-dot-unknown');
        parts.push(`<section class="ssh-host" data-host="${esc(host.id)}">`,
            '<div class="ssh-host-head">',
            `<span class="ssh-dot ${dot}"></span>`,
            `<span class="ssh-host-id">${esc(host.id)}</span>`,
            `<span class="ssh-host-dest">${esc(host.ssh || '')}</span>`,
            `<button class="ssh-btn" data-action="new" data-host="${esc(host.id)}">+ New server</button>`,
            '</div>');
        if (hostError) {
            parts.push(`<pre class="ssh-error">${esc(hostError)}</pre>`);
        }
        const form = (model.forms || {})[host.id];
        if (form) {
            const busy = (model.launching || {})[host.id];
            parts.push(`<form class="ssh-new-form" data-host="${esc(host.id)}">`,
                `<input name="workdir" placeholder="Working directory (default: ~)" value="${esc(form.workdir || '')}">`,
                `<input name="label" placeholder="Label (optional)" value="${esc(form.label || '')}">`,
                `<button class="ssh-btn ssh-primary" type="submit"${busy ? ' disabled' : ''}>${busy ? 'Launching…' : 'Launch'}</button>`,
                `<button class="ssh-btn" type="button" data-action="cancel-new" data-host="${esc(host.id)}">Cancel</button>`,
                '</form>');
        }
        const attachments = {};
        for (const a of host.attachments || []) attachments[a.server_id] = a;
        const servers = host.servers || [];
        if (host.servers && !servers.length) {
            parts.push('<div class="ssh-empty">No ppxai servers running on this host.</div>');
        }
        for (const s of servers) {
            const att = attachments[s.id];
            const state = att ? att.state : 'not attached';
            const counts = (host.counts || {})[s.id];
            const label = s.label ? `“${esc(s.label)}” ` : '';
            parts.push(`<div class="ssh-server" data-server="${esc(s.id)}">`,
                '<div class="ssh-server-line">',
                `<span class="ssh-server-id" title="${esc(s.id)}">${esc(s.id.slice(0, 8))}</span> `,
                `${label}<span class="ssh-server-dir">${esc(s.workdir)}</span>`,
                ` <span class="ssh-server-ver">${esc(s.version)}</span>`,
                ` <span class="ssh-state ssh-state-${esc(state.replace(/ /g, '-'))}">${esc(state)}</span>`,
                '</div>');
            if (att && att.detail && state !== 'healthy') {
                parts.push(`<div class="ssh-detail">${esc(att.detail)}</div>`);
            }
            if (counts) {
                parts.push(`<div class="ssh-counts">${counts.sessions} session${counts.sessions === 1 ? '' : 's'}`
                    + ` · ${counts.activeRuns} run${counts.activeRuns === 1 ? '' : 's'} active</div>`);
            }
            parts.push('<div class="ssh-server-actions">',
                `<button class="ssh-btn ssh-primary" data-action="open" data-host="${esc(host.id)}" data-server="${esc(s.id)}">Open ↗</button>`,
                att ? `<button class="ssh-btn" data-action="detach" data-host="${esc(host.id)}" data-server="${esc(s.id)}">Detach</button>` : '',
                `<button class="ssh-btn ssh-danger" data-action="stop" data-host="${esc(host.id)}" data-server="${esc(s.id)}" data-label="${esc(s.label || s.id.slice(0, 8))}">Stop…</button>`,
                '</div></div>');
        }
        for (const refusal of host.refused || []) {
            parts.push(`<div class="ssh-error">${esc(refusal)}</div>`);
        }
        parts.push('</section>');
    }
    parts.push('</div>');
    return parts.join('');
}

/** Fallback escaper when shared/formatters.js is not loaded (tests). */
function sshLauncherEscape(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

/** The browser tab name for a remote server: one tab per server. */
function sshLauncherTabName(host, serverId) {
    return `ppxai-${host}-${serverId}`;
}

class SshLauncherView extends BaseView {
    constructor(appState, fetchImpl) {
        super();
        this._appState = appState;
        this._fetch = fetchImpl || ((...a) => window.fetch(...a));
        this._origin = window.location.origin;
        this._container = null;
        this._timer = null;
        this._model = { hosts: [], loading: true, error: null, launching: {}, forms: {} };
        this._refreshing = null;
        this._refreshAgain = false;
        this._onClick = (e) => this._handleClick(e);
        this._onSubmit = (e) => this._handleSubmit(e);
    }

    // ── BaseView protocol ─────────────────────────────────────────────────

    getTitle() { return '🖥 SSH Launcher'; }
    getPath() { return 'ssh://launcher'; }
    getIcon() { return '🖥'; }

    mount(container) {
        this._container = container;
        container.addEventListener('click', this._onClick);
        container.addEventListener('submit', this._onSubmit);
        this._render();
        this.refresh();
        this._startTimer();
    }

    unmount() {
        this._stopTimer();
        if (this._container) {
            this._container.removeEventListener('click', this._onClick);
            this._container.removeEventListener('submit', this._onSubmit);
            this._container.innerHTML = '';
        }
        this._container = null;
    }

    onActivate() { this._startTimer(); this.refresh(); }
    onDeactivate() { this._stopTimer(); }

    // ── data ──────────────────────────────────────────────────────────────

    async _api(method, path, body, headers) {
        const init = { method, headers: { ...(headers || {}) } };
        if (body !== undefined) {
            init.headers['Content-Type'] = 'application/json';
            init.body = JSON.stringify(body);
        }
        const resp = await this._fetch(`${this._origin}${path}`, init);
        let data = null;
        try { data = await resp.json(); } catch (_) { /* empty body */ }
        if (!resp.ok) {
            const detail = (data && (data.detail || data.error)) || `HTTP ${resp.status}`;
            throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail));
        }
        return data;
    }

    async refresh() {
        // One refresh at a time; a request made meanwhile runs once after it,
        // so an older snapshot never renders over a newer one.
        if (this._refreshing) { this._refreshAgain = true; return this._refreshing; }
        this._refreshing = this._refreshOnce();
        try { await this._refreshing; } finally { this._refreshing = null; }
        if (this._refreshAgain) { this._refreshAgain = false; await this.refresh(); }
    }

    async _refreshOnce() {
        try {
            const { hosts } = await this._api('GET', '/hub/hosts');
            const byId = {};
            for (const h of this._model.hosts) byId[h.id] = h;
            this._model.hosts = hosts.map(h => ({ ...byId[h.id], ...h }));
            this._model.error = null;
        } catch (err) {
            this._model.error = `The hub did not answer: ${err.message}`;
        }
        this._model.loading = false;
        this._render();
        await Promise.all(this._model.hosts.map(h => this._loadServers(h)));
        this._render();
    }

    async _loadServers(host) {
        try {
            const listing = await this._api('GET', `/hub/hosts/${encodeURIComponent(host.id)}/servers`);
            host.servers = listing.servers;
            host.refused = listing.refused;
            host.listError = null;
        } catch (err) {
            host.servers = null;
            host.listError = err.message;
            return;
        }
        // Session/run counts only for healthy attachments: reading them
        // through the proxy would otherwise attach (open an SSH forward to)
        // every server just because the launcher is open.
        host.counts = {};
        const healthy = (host.attachments || []).filter(a => a.state === 'healthy');
        await Promise.all(healthy.map(async (a) => {
            const base = `/h/${encodeURIComponent(host.id)}/${encodeURIComponent(a.server_id)}`;
            try {
                // Observe, never attach: this list may predate a Detach.
                const sessions = await this._api('GET', `${base}/sessions/list`, undefined, SSH_LAUNCHER_NO_ATTACH);
                const runs = await this._api('GET', `${base}/v1/agent/runs`, undefined, SSH_LAUNCHER_NO_ATTACH);
                const active = ((runs && runs.runs) || [])
                    .filter(r => !SSH_LAUNCHER_TERMINAL_RUNS.has(r.status)).length;
                host.counts[a.server_id] = { sessions: (sessions && sessions.count) || 0,
                                             activeRuns: active };
            } catch (_) { /* counts are decoration; the row stays */ }
        }));
    }

    // ── actions ───────────────────────────────────────────────────────────

    _handleClick(e) {
        const btn = e.target.closest('button[data-action]');
        if (!btn || !this._container || !this._container.contains(btn)) return;
        const { action, host, server, label } = btn.dataset;
        if (action === 'refresh') this.refresh();
        else if (action === 'new') { this._model.forms[host] = this._model.forms[host] || {}; this._render(); }
        else if (action === 'cancel-new') { delete this._model.forms[host]; this._render(); }
        else if (action === 'open') this.open(host, server);
        else if (action === 'detach') this._act(host, server, 'detach');
        else if (action === 'stop') {
            if (confirm(`Stop the ppxai server "${label}" on ${host}? Its sessions and running tasks end.`)) {
                this._act(host, server, 'stop');
            }
        }
    }

    open(host, serverId) {
        const url = `${this._origin}/h/${encodeURIComponent(host)}/${encodeURIComponent(serverId)}/`;
        window.open(url, sshLauncherTabName(host, serverId));
        // The proxy attaches on the tab's first request; show it once it has.
        setTimeout(() => this.refresh(), 3000);
    }

    async _act(host, serverId, action) {
        try {
            await this._api('POST', `/hub/hosts/${encodeURIComponent(host)}/servers/${encodeURIComponent(serverId)}/${action}`, {});
            this._model.error = null;
        } catch (err) {
            this._model.error = `${action} ${host}/${serverId.slice(0, 8)}: ${err.message}`;
        }
        this.refresh();
    }

    async _handleSubmit(e) {
        const form = e.target.closest('form.ssh-new-form');
        if (!form) return;
        e.preventDefault();
        const host = form.dataset.host;
        const workdir = form.elements.workdir.value.trim();
        const label = form.elements.label.value.trim();
        this._model.forms[host] = { workdir, label };
        this._model.launching[host] = true;
        this._render();
        try {
            await this._api('POST', `/hub/hosts/${encodeURIComponent(host)}/servers`,
                { workdir: workdir || null, label: label || null });
            delete this._model.forms[host];
            this._model.error = null;
        } catch (err) {
            this._model.error = `Launch on ${host}: ${err.message}`;
        }
        delete this._model.launching[host];
        this.refresh();
    }

    // ── internals ─────────────────────────────────────────────────────────

    _render() {
        if (!this._container) return;
        // Keep what the user is typing: a periodic refresh re-renders the pane.
        for (const form of this._container.querySelectorAll('form.ssh-new-form')) {
            if (this._model.forms[form.dataset.host]) {
                this._model.forms[form.dataset.host] = {
                    workdir: form.elements.workdir.value, label: form.elements.label.value };
            }
        }
        const esc = (typeof escapeHtml === 'function') ? escapeHtml : sshLauncherEscape;
        this._container.innerHTML = renderSshLauncher(this._model, esc);
    }

    _startTimer() {
        if (this._timer) return;
        // No automatic refresh while a New-server form is open: re-rendering
        // would take the focus out of the field being typed in.
        this._timer = setInterval(() => {
            if (!Object.keys(this._model.forms).length) this.refresh();
        }, SSH_LAUNCHER_REFRESH_MS);
    }

    _stopTimer() {
        if (this._timer) clearInterval(this._timer);
        this._timer = null;
    }
}
