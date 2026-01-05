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
 * API Client class for ppxai server
 */
class ApiClient {
    constructor(serverUrl = 'http://127.0.0.1:54320') {
        this.serverUrl = serverUrl;
    }

    /**
     * Set the server URL
     */
    setServerUrl(url) {
        this.serverUrl = url;
    }

    /**
     * Make a GET request
     */
    async get(endpoint) {
        const response = await fetch(`${this.serverUrl}${endpoint}`);
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
            headers: { 'Content-Type': 'application/json' },
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

    async setProvider(providerId) {
        return this.post('/providers', { provider: providerId });
    }

    // === Models ===

    async getModels() {
        return this.get('/models');
    }

    async setModel(modelId) {
        return this.post('/models', { model: modelId });
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

    // === Interrupt ===

    async interrupt() {
        return this.post('/interrupt');
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
