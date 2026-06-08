/**
 * Shared API Client for ppxai HTTP Server
 *
 * Provides a unified interface for making API calls from:
 * - Desktop Web App (ppxai/web/app.js)
 * - VSCode Extension (vscode-extension/src/httpClient.ts)
 *
 * @version 1.14.0
 */

/**
 * Generate a UUID v4
 */
function generateUUID() {
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
        const r = Math.random() * 16 | 0;
        const v = c === 'x' ? r : (r & 0x3 | 0x8);
        return v.toString(16);
    });
}

/**
 * API Client class for ppxai server
 */
class ApiClient {
    constructor(serverUrl = 'http://127.0.0.1:54320', sessionId = null) {
        this.serverUrl = serverUrl;
        // Generate unique session ID for this client instance (v1.14.0)
        this.sessionId = sessionId || `webapp-${generateUUID()}`;
        console.log(`[ApiClient] Session ID: ${this.sessionId}`);
    }

    /**
     * Set the server URL
     */
    setServerUrl(url) {
        this.serverUrl = url;
    }

    /**
     * Get the session ID
     */
    getSessionId() {
        return this.sessionId;
    }

    /**
     * Get headers with session ID (v1.14.0)
     */
    getHeaders(includeContentType = false) {
        const headers = {
            'X-Session-Id': this.sessionId
        };
        if (includeContentType) {
            headers['Content-Type'] = 'application/json';
        }
        return headers;
    }

    /**
     * Throw a richer Error from a non-OK response. Keeps
     * `err.message` compatible with existing string-based handling
     * (`err.message.includes('404')` etc.) AND attaches `.status`
     * and `.body` so callers that care about structured errors —
     * notably the v1.18.1 cwd_anchor 409 path — can read them.
     */
    async _throwHttpError(response) {
        let body;
        try { body = await response.json(); }
        catch { body = { detail: response.statusText }; }
        // FastAPI wraps the response body in `detail` for HTTPException.
        // We attach BOTH the wrapped body (body.detail) AND the raw
        // body so callers can pick whichever shape is convenient.
        const detail = body && typeof body.detail === 'object' ? body.detail : body;
        const messageParts = [];
        if (typeof detail?.detail === 'string') messageParts.push(detail.detail);
        else if (typeof body.detail === 'string') messageParts.push(body.detail);
        else messageParts.push(`HTTP ${response.status}`);
        const err = new Error(messageParts.join(' '));
        err.status = response.status;
        err.body = body;
        // For 409 cwd-anchor mismatches, surface expected/actual + events
        // at the top level for caller convenience.
        if (detail && typeof detail === 'object') {
            err.expected = detail.expected;
            err.actual = detail.actual;
            err.events = detail.events;
        }
        throw err;
    }

    /**
     * Make a GET request
     */
    async get(endpoint) {
        const response = await fetch(`${this.serverUrl}${endpoint}`, {
            headers: this.getHeaders()
        });
        if (!response.ok) await this._throwHttpError(response);
        return response.json();
    }

    /**
     * Make a POST request
     */
    async post(endpoint, body = {}) {
        const response = await fetch(`${this.serverUrl}${endpoint}`, {
            method: 'POST',
            headers: this.getHeaders(true),
            body: JSON.stringify(body)
        });
        if (!response.ok) await this._throwHttpError(response);
        return response.json();
    }

    // === Health & Status ===

    async getHealth() {
        return this.get('/health');
    }

    async getStatus() {
        return this.get('/status');
    }

    // v1.18.0 Phase 2: snapshot of all SSE-synced AppState fields for
    // reconnect catch-up. Returns a snake_case dict shaped exactly
    // like an accumulated stream of `state_sync` events, so it can be
    // fed directly to `AppState.updateFromPython()`.
    async getState() {
        return this.get('/state');
    }

    // === Providers ===

    async getProviders() {
        return this.get('/providers');
    }

    async setProvider(providerId, resetContext = true) {
        return this.post('/providers', { provider: providerId, reset_context: resetContext });
    }

    // === Models ===

    async getModels() {
        return this.get('/models');
    }

    async setModel(modelId, resetContext = true) {
        return this.post('/models', { model: modelId, reset_context: resetContext });
    }

    // === Tools ===

    async getTools() {
        return this.get('/tools');
    }

    async setToolsEnabled(enabled) {
        return this.post('/tools', { enabled });
    }

    async setToolConfig(setting, value) {
        return this.post('/tools/config', { setting, value });
    }

    async getToolHelp(toolName) {
        return this.get(`/tools/help/${encodeURIComponent(toolName)}`);
    }

    // === Agent ===

    async getAgentStatus() {
        return this.get('/agent/status');
    }

    async getAgentConfig() {
        return this.get('/agent/config');
    }

    async enableAgent() {
        return this.post('/agent/enable');
    }

    async disableAgent() {
        return this.post('/agent/disable');
    }

    // === Checkpoint ===

    async getCheckpointStatus() {
        return this.get('/checkpoint/status');
    }

    async listCheckpoints(limit = 10) {
        return this.get(`/checkpoint/list?limit=${limit}`);
    }

    async getCheckpointInfo(checkpointId) {
        return this.get(`/checkpoint/info/${encodeURIComponent(checkpointId)}`);
    }

    async setCheckpointBackend(backend) {
        return this.post('/checkpoint/backend', { backend });
    }

    async clearCheckpoints(keepLast = 0) {
        return this.post('/checkpoint/clear', { keep_last: keepLast });
    }

    async undoCheckpoint() {
        return this.post('/checkpoint/undo');
    }

    // === Usage ===

    async getUsage() {
        return this.get('/usage');
    }

    async getUsageReport(period) {
        return this.get(`/usage/report?period=${period}`);
    }

    async setUsageDisplayMode(mode) {
        return this.post('/usage/display', { mode });
    }

    async getUsageDisplayMode() {
        return this.get('/usage/display');
    }

    async resetUsage() {
        return this.post('/usage/reset');
    }

    // === Sessions ===

    async getSessions() {
        return this.get('/sessions');
    }

    async saveSession() {
        return this.post('/sessions/save');
    }

    async loadSession(name) {
        return this.post(`/sessions/load/${encodeURIComponent(name)}`);
    }

    async clearSession() {
        return this.post('/sessions/clear');
    }

    // === Export ===

    async exportAnswer(filename) {
        return this.post('/export', { filename });
    }

    // === Files ===

    async readFile(filepath, cwdAnchor = null) {
        // v1.18.1 Phase D: optional cwd_anchor lets the server
        // detect drift between the client's idea of cwd (when the
        // relpath was captured) and the engine's current cwd. On
        // mismatch the server returns 409 + new cwd; the caller
        // refreshes its tree and retries.
        const body = { path: filepath };
        if (cwdAnchor) body.cwd_anchor = cwdAnchor;
        return this.post('/files/read', body);
    }

    async searchFiles(query, limit = 20) {
        return this.post('/files/search', { query, limit });
    }

    async complete(buffer, cursor = -1) {
        return this.post('/complete', { buffer, cursor });
    }

    // === Working Directory ===

    async getWorkingDir() {
        return this.get('/context/working_dir');
    }

    async setWorkingDir(path) {
        return this.post('/context/working_dir', { path });
    }

    // === Auto-Inject ===

    async getAutoInject() {
        return this.get('/context/auto_inject');
    }

    async setAutoInject(enabled) {
        return this.post('/context/auto_inject', { enabled });
    }

    // === Context Info (v1.13.9) ===

    async getContextInfo() {
        return this.get('/context/info');
    }

    async clearContextInjections() {
        return this.post('/context/clear');
    }

    // === Interrupt ===

    async interrupt() {
        return this.post('/interrupt');
    }

    // === Config ===

    async reloadConfig() {
        return this.post('/config/reload');
    }

    async getConfigPath() {
        return this.get('/config/path');
    }

    async shutdown() {
        return this.post('/shutdown');
    }

    // === Sessions (extended) ===

    async getLastSession() {
        return this.get('/sessions/last');
    }

    async restoreSession() {
        return this.post('/sessions/restore');
    }

    // === Context (extended) ===

    async reloadContext() {
        return this.post('/context/reload');
    }

    async getContextHints() {
        return this.get('/context/hints');
    }

    async getBootstrapContext() {
        return this.get('/context/bootstrap');
    }

    // === Files (extended) ===

    async listFiles(queryString = '') {
        return this.get(`/files/list${queryString ? '?' + queryString : ''}`);
    }

    async getFileTree(queryString = '') {
        return this.get(`/files/tree${queryString ? '?' + queryString : ''}`);
    }

    async writeFile(path, content, cwdAnchor = null) {
        // v1.18.1 Phase D: see readFile() for cwd_anchor semantics.
        const body = { path, content };
        if (cwdAnchor) body.cwd_anchor = cwdAnchor;
        return this.post('/files/write', body);
    }

    // === Office preview + download (v1.18.7) ===

    // Office preview metadata + slides go through the GET /files/preview
    // path-based endpoint added in v1.18.7. The PPTX raster path returns
    // image/png bytes (we read them as a blob URL for an <img> tag);
    // LibreOffice-missing fallbacks return JSON. Caller decides which
    // path to take based on `total=true` metadata + LibreOffice flag.

    async previewFileMetadata(filepath, cwdAnchor = null) {
        const params = new URLSearchParams({ path: filepath, total: 'true' });
        if (cwdAnchor) params.set('cwd_anchor', cwdAnchor);
        params.set('session', this.sessionId);
        return this.get(`/files/preview?${params.toString()}`);
    }

    previewFileSlideUrl(filepath, slide, cwdAnchor = null) {
        // Returns a URL suitable for <img src> / <embed src>. Used when
        // metadata reports LibreOffice-available (type=pdf|pptx, NOT
        // text_fallback). Session via query string because browsers don't
        // send custom headers on <img>/<embed>.
        const params = new URLSearchParams({ path: filepath, slide: String(slide) });
        if (cwdAnchor) params.set('cwd_anchor', cwdAnchor);
        params.set('session', this.sessionId);
        return `${this.serverUrl}/files/preview?${params.toString()}`;
    }

    async previewFileSlideJson(filepath, slide, cwdAnchor = null) {
        // For text_fallback responses — we need to read the JSON body
        // (which carries `content` markdown). Caller uses metadata
        // first to know which method to call.
        const params = new URLSearchParams({ path: filepath, slide: String(slide) });
        if (cwdAnchor) params.set('cwd_anchor', cwdAnchor);
        params.set('session', this.sessionId);
        return this.get(`/files/preview?${params.toString()}`);
    }

    downloadFileUrl(filepath, cwdAnchor = null) {
        // Returns the URL the browser navigates to (or that we click
        // via a hidden <a download>) to trigger the native download
        // dialog. Server sets Content-Disposition: attachment.
        const params = new URLSearchParams({ path: filepath });
        if (cwdAnchor) params.set('cwd_anchor', cwdAnchor);
        params.set('session', this.sessionId);
        return `${this.serverUrl}/files/download?${params.toString()}`;
    }

    /**
     * Upload a single file to a directory in the workspace (v1.18.7).
     *
     * POST multipart/form-data to /files/upload?path=<destRelPath>. The
     * server writes the file at <destRelPath>/<file.name>. Throws an
     * Error whose `.status` carries the HTTP code so callers can
     * branch on 409 (conflict — prompt for overwrite) and 413 (too
     * large).
     *
     * @param {string} destRelPath  Destination directory; empty string = working_dir root
     * @param {File} file           Browser File object
     * @param {boolean} overwrite   When true, server replaces existing file at the name
     * @param {string|null} cwdAnchor  cwd at the time of the click, for 409 drift detection
     * @returns {Promise<Object>}   {path, name, size, overwrote}
     */
    async uploadFile(destRelPath, file, overwrite = false, cwdAnchor = null) {
        const params = new URLSearchParams({ path: destRelPath || '.' });
        if (overwrite) params.set('overwrite', 'true');
        if (cwdAnchor) params.set('cwd_anchor', cwdAnchor);
        params.set('session', this.sessionId);

        const form = new FormData();
        form.append('file', file, file.name);

        // We can't use `this.post` here because it always JSON-encodes
        // the body. Use fetch directly and replicate the session-headers
        // contract (which lives in `this.headers`).
        const headers = { ...this.headers };
        // DON'T set Content-Type — FormData picks its own boundary;
        // overriding it here breaks multipart parsing on the server.
        delete headers['Content-Type'];

        const res = await fetch(`${this.serverUrl}/files/upload?${params.toString()}`, {
            method: 'POST',
            headers,
            body: form,
        });
        if (!res.ok) {
            let detail = '';
            try { const j = await res.json(); detail = j.detail || ''; } catch { /* not JSON */ }
            const err = new Error(detail || `HTTP ${res.status}`);
            err.status = res.status;
            throw err;
        }
        return res.json();
    }

    // === Commands ===

    async executeCommand(name, args = '') {
        return this.post(`/command/${encodeURIComponent(name)}`, { args });
    }

    // === Consent ===

    async submitConsent(filePath, consentResponse) {
        return this.post('/consent', { file_path: filePath, response: consentResponse });
    }

    async submitShellConsent(command, workingDir, consentResponse) {
        return this.post('/shell-consent', { command, working_dir: workingDir, response: consentResponse });
    }

    // === Debug Log ===

    async getDebugLogStatus() {
        return this.get('/debug-log');
    }

    async setDebugLog(enabled) {
        return this.post('/debug-log', { enabled });
    }

    // === Preview Serve (v1.17.1) ===

    async startPreviewServe(filepath, command = null, port = null) {
        const body = { filepath };
        if (command) body.command = command;
        if (port) body.port = port;
        return this.post('/preview/serve', body);
    }

    async stopPreviewServe() {
        return this.post('/preview/serve/stop');
    }

    async getPreviewServeStatus() {
        return this.get('/preview/serve/status');
    }

    // === Preview Proxy (v1.17.1 — K8s) ===

    async startPreviewProxy(port) {
        return this.post('/preview/proxy/start', { port });
    }

    async stopPreviewProxy() {
        return this.post('/preview/proxy/stop');
    }
}

/**
 * Create a singleton instance
 */
let defaultClient = null;

function getApiClient(serverUrl) {
    if (!defaultClient) {
        defaultClient = new ApiClient(serverUrl);
    } else if (serverUrl) {
        defaultClient.setServerUrl(serverUrl);
    }
    return defaultClient;
}

// Browser global export (for non-module scripts)
if (typeof window !== 'undefined') {
    window.ApiClient = ApiClient;
    window.getApiClient = getApiClient;
}

// CommonJS export (for Node.js/bundlers)
if (typeof module !== 'undefined' && module.exports) {
    module.exports = { ApiClient, getApiClient };
}
