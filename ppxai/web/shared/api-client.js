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
     * Make a GET request
     */
    async get(endpoint) {
        const response = await fetch(`${this.serverUrl}${endpoint}`, {
            headers: this.getHeaders()
        });
        if (!response.ok) {
            const error = await response.json().catch(() => ({ detail: response.statusText }));
            throw new Error(error.detail || `HTTP ${response.status}`);
        }
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
        if (!response.ok) {
            const error = await response.json().catch(() => ({ detail: response.statusText }));
            throw new Error(error.detail || `HTTP ${response.status}`);
        }
        return response.json();
    }

    // === Health & Status ===

    async getHealth() {
        return this.get('/health');
    }

    async getStatus() {
        return this.get('/status');
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

    async readFile(filepath) {
        return this.post('/files/read', { path: filepath });
    }

    async searchFiles(query, limit = 20) {
        return this.post('/files/search', { query, limit });
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

    async writeFile(path, content) {
        return this.post('/files/write', { path, content });
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
