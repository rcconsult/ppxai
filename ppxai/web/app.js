/**
 * ppxai Web UI Application
 *
 * v1.14.2 - Standalone web-based chat interface
 *
 * Uses shared modules for command definitions and formatters to maintain
 * parity with VSCode extension.
 *
 * v1.14.2 Changes:
 * - Added session ID support for server session isolation
 * - Each browser tab gets unique session ID via sessionStorage
 * - All API requests now include X-Session-Id header
 *
 * v1.14.1 Changes:
 * - Added /edit command with CodeMirror 6 editor (lazy-loaded by extension)
 * - Added /context reload command to reload AGENTS.md from disk
 * - CodeMirror bundles: markdown, yaml, json, python, javascript
 * - Editor panel with save/discard toolbar, Ctrl+S support
 * - File position support: /edit filepath:line:col
 * - Path validation via POST /files/write endpoint
 *
 * v1.14.0 Changes:
 * - Fixed markdown rendering with proper list syntax (- instead of •)
 * - Added table format for /usage command (matching VSCode extension)
 * - Updated marked.js to v11.1.1
 */

// Import shared modules (loaded via script tags in index.html)
// These are available as globals: SharedCommands, SharedFormatters
// Or when using ES modules: import from './shared/index.js'

class PpxaiApp {
    constructor() {
        // Configuration
        // Use current page origin as server URL (since server serves the web UI)
        // Fall back to localStorage or default only if origin is file:// or about:
        const pageOrigin = window.location.origin;
        const usePageOrigin = pageOrigin && !pageOrigin.startsWith('file:') && pageOrigin !== 'null';
        this.serverUrl = usePageOrigin ? pageOrigin : (localStorage.getItem('ppxai-server-url') || 'http://127.0.0.1:54320');
        this.theme = localStorage.getItem('ppxai-theme') || 'dark';

        // Session ID for server session isolation (v1.14.0)
        // Each browser tab/window gets its own session ID
        this.sessionId = sessionStorage.getItem('ppxai-session-id');
        if (!this.sessionId) {
            this.sessionId = `webapp-${generateUUID()}`;
            sessionStorage.setItem('ppxai-session-id', this.sessionId);
        }
        console.log(`[PpxaiApp] Session ID: ${this.sessionId}`);

        // State
        this.currentProvider = '';
        this.currentModel = '';
        this.toolsEnabled = false;
        this.agentMode = false;
        this.isStreaming = false;
        this.currentAbortController = null;
        this.commandHistory = JSON.parse(localStorage.getItem('ppxai-history') || '[]');
        this.historyIndex = -1;
        this.debugLogEnabled = false;
        this.verbose = false;
        this.lastCheckpoint = null;

        // Preview panel state (v1.13.8)
        this.previewViewMode = 'rendered';  // 'rendered' or 'source'
        this.previewContent = null;         // Raw file content
        this.previewFilename = null;        // Current filename
        this.previewDataFormat = null;      // Detected data format
        this.currentDataViewer = null;      // Current viewer instance

        // Track current assistant message for correct ordering
        this.currentAssistantMessage = null;

        // Debounce flag for message sending
        this.isSending = false;

        // Guard for slash command handling
        this.isHandlingCommand = false;

        // Usage tracking
        this.usage = { prompt: 0, completion: 0, cost: 0 };

        // Autocomplete state
        this.autocompleteVisible = false;
        this.autocompleteItems = [];
        this.autocompleteIndex = 0;
        this.autocompleteType = null; // 'command' or 'file'

        // DOM elements
        this.elements = {};

        // Use shared slash commands if available, otherwise use local copy
        // This ensures backwards compatibility while enabling shared definitions
        this.slashCommands = (typeof SharedCommands !== 'undefined' && SharedCommands.SLASH_COMMANDS)
            ? SharedCommands.SLASH_COMMANDS
            : {
                '/help': { description: 'Show available commands', usage: '/help' },
                '/clear': { description: 'Clear conversation history', usage: '/clear' },
                '/save': { description: 'Save session to JSON', usage: '/save' },
                '/export': { description: 'Export last answer to markdown', usage: '/export [filename]' },
                '/load': { description: 'Load a saved session', usage: '/load <session_name>' },
                '/sessions': { description: 'List saved sessions', usage: '/sessions' },
                '/model': { description: 'Switch model or list models', usage: '/model [model_id|list]' },
                '/provider': { description: 'Switch provider or list providers', usage: '/provider [provider_id|list]' },
                '/tools': { description: 'Manage AI tools', usage: '/tools [enable|disable|status|list|config|set|agent|help]' },
                '/agent': { description: 'Run autonomous agent task', usage: '/agent [on|off|<task description>]' },
                '/checkpoint': { description: 'Manage checkpoints', usage: '/checkpoint [status|list|undo|backend|clear|info]' },
                '/usage': { description: 'Show token usage stats', usage: '/usage [24h|week|month|all|show|reset]' },
                '/status': { description: 'Show current status', usage: '/status' },
                '/show': { description: 'Display file contents', usage: '/show <filepath>' },
                '/cat': { description: 'Alias for /show', usage: '/cat <filepath>' },
                '/edit': { description: 'Edit file in CodeMirror editor', usage: '/edit <filepath[:line[:col]]>' },
                '/context': { description: 'Manage context', usage: '/context [clear|hints|show|reload]' },
                '/cd': { description: 'Change working directory', usage: '/cd <path>' },
                '/pwd': { description: 'Print working directory', usage: '/pwd' },
                '/generate': { description: 'Generate code from description', usage: '/generate <description>' },
                '/explain': { description: 'Explain code or concept', usage: '/explain <code or question>' },
                '/test': { description: 'Generate tests for code', usage: '/test <code or @file>' },
                '/docs': { description: 'Generate documentation', usage: '/docs <code or @file>' },
                '/debug': { description: 'Debug an error message', usage: '/debug <error message>' },
                '/implement': { description: 'Implement from specification', usage: '/implement <specification>' },
                '/convert': { description: 'Convert code between languages', usage: '/convert <src> <dest> <code>' },
                '/spec': { description: 'Show specification templates', usage: '/spec [api|cli|lib|algo|ui]' },
                '/theme': { description: 'Switch theme', usage: '/theme [dark|light]' },
            };

        // Initialize
        this.init();
    }

    async init() {
        this.cacheElements();
        this.setupEventListeners();
        this.applyTheme();
        this.setupMarkdown();
        await this.connectToServer();
    }

    cacheElements() {
        this.elements = {
            // Header
            versionBadge: document.getElementById('versionBadge'),
            serverBadge: document.getElementById('serverBadge'),
            serverStatus: document.getElementById('serverStatus'),
            folderBadge: document.getElementById('folderBadge'),
            folderPath: document.getElementById('folderPath'),
            providerSelect: document.getElementById('providerSelect'),
            modelSelect: document.getElementById('modelSelect'),
            toolsBadge: document.getElementById('toolsBadge'),
            toolsStatus: document.getElementById('toolsStatus'),
            agentBadge: document.getElementById('agentBadge'),
            agentStatus: document.getElementById('agentStatus'),
            undoBadge: document.getElementById('undoBadge'),
            streamingBadge: document.getElementById('streamingBadge'),
            usageBadge: document.getElementById('usageBadge'),
            clearBtn: document.getElementById('clearBtn'),
            quitBtn: document.getElementById('quitBtn'),
            reloadConfigBtn: document.getElementById('reloadConfigBtn'),
            themeBtn: document.getElementById('themeBtn'),
            menuBtn: document.getElementById('menuBtn'),
            menuDropdown: document.getElementById('menuDropdown'),
            saveSessionBtn: document.getElementById('saveSessionBtn'),
            exportBtn: document.getElementById('exportBtn'),
            debugLogBtn: document.getElementById('debugLogBtn'),
            debugIndicator: document.getElementById('debugIndicator'),
            settingsBtn: document.getElementById('settingsBtn'),
            contextBadge: document.getElementById('contextBadge'),
            contextUsage: document.getElementById('contextUsage'),
            clearContextBtn: document.getElementById('clearContextBtn'),

            // Messages
            messagesContainer: document.getElementById('messagesContainer'),

            // Input
            messageInput: document.getElementById('messageInput'),
            sendBtn: document.getElementById('sendBtn'),
            autocompleteDropdown: document.getElementById('autocompleteDropdown'),

            // Preview panel
            previewPanel: document.getElementById('previewPanel'),
            previewFilename: document.getElementById('previewFilename'),
            previewInfo: document.getElementById('previewInfo'),
            previewClose: document.getElementById('previewClose'),
            previewCode: document.getElementById('previewCode'),
            previewMarkdown: document.getElementById('previewMarkdown'),
            previewDataViewer: document.getElementById('previewDataViewer'),
            previewViewToggle: document.getElementById('previewViewToggle'),
            resizeHandle: document.getElementById('resizeHandle'),

            // Modals
            consentModal: document.getElementById('consentModal'),
            consentTitle: document.getElementById('consentTitle'),
            consentMessage: document.getElementById('consentMessage'),
            consentDetails: document.getElementById('consentDetails'),
            consentYes: document.getElementById('consentYes'),
            consentNo: document.getElementById('consentNo'),
            consentAlways: document.getElementById('consentAlways'),
            consentNever: document.getElementById('consentNever'),
            settingsModal: document.getElementById('settingsModal'),
            closeSettings: document.getElementById('closeSettings'),
            themeSetting: document.getElementById('themeSetting'),
            serverUrlSetting: document.getElementById('serverUrl'),
        };
    }

    setupEventListeners() {
        // Input handling
        this.elements.messageInput.addEventListener('keydown', (e) => this.handleInputKeydown(e));
        this.elements.messageInput.addEventListener('input', () => this.handleInputChange());
        this.elements.sendBtn.addEventListener('click', () => this.sendMessage());

        // Auto-resize textarea
        this.elements.messageInput.addEventListener('input', () => {
            this.elements.messageInput.style.height = 'auto';
            this.elements.messageInput.style.height = Math.min(this.elements.messageInput.scrollHeight, 200) + 'px';
        });

        // Header controls
        this.elements.providerSelect.addEventListener('change', () => this.handleProviderChange());
        this.elements.modelSelect.addEventListener('change', () => this.handleModelChange());
        this.elements.toolsBadge.addEventListener('click', () => this.toggleTools());
        this.elements.agentBadge.addEventListener('click', () => this.toggleAgent());
        this.elements.undoBadge.addEventListener('click', () => this.undoCheckpoint());
        this.elements.clearBtn.addEventListener('click', () => this.clearConversation());
        this.elements.quitBtn.addEventListener('click', () => this.handleQuit());
        this.elements.themeBtn.addEventListener('click', () => this.cycleTheme());

        // Folder badge click to change working directory
        this.elements.folderBadge.addEventListener('click', () => this.handleFolderBadgeClick());

        // Menu
        this.elements.menuBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            this.elements.menuDropdown.classList.toggle('hidden');
        });
        document.addEventListener('click', () => {
            this.elements.menuDropdown.classList.add('hidden');
        });
        this.elements.saveSessionBtn.addEventListener('click', () => this.saveSession());
        this.elements.exportBtn.addEventListener('click', () => this.exportAnswer());
        this.elements.debugLogBtn.addEventListener('click', () => this.toggleDebugLog());
        this.elements.reloadConfigBtn.addEventListener('click', () => this.reloadConfig());
        this.elements.settingsBtn.addEventListener('click', () => this.showSettings());
        this.elements.contextBadge.addEventListener('click', () => this.clearContextInjections());
        this.elements.clearContextBtn.addEventListener('click', () => this.clearContextInjections());

        // Settings modal
        this.elements.closeSettings.addEventListener('click', () => this.hideSettings());
        this.elements.settingsModal.addEventListener('click', (e) => {
            if (e.target === this.elements.settingsModal) this.hideSettings();
        });
        this.elements.themeSetting.addEventListener('change', () => {
            this.theme = this.elements.themeSetting.value;
            this.applyTheme();
            localStorage.setItem('ppxai-theme', this.theme);
        });
        this.elements.serverUrlSetting.addEventListener('change', () => {
            this.serverUrl = this.elements.serverUrlSetting.value;
            localStorage.setItem('ppxai-server-url', this.serverUrl);
            this.connectToServer();
        });

        // Preview panel close button
        this.elements.previewClose.addEventListener('click', () => this.hidePreviewPanel());

        // Preview panel view toggle (v1.13.8)
        if (this.elements.previewViewToggle) {
            this.elements.previewViewToggle.addEventListener('click', () => this.togglePreviewViewMode());
        }

        // Preview panel resize handle
        this.initResizeHandle();

        // Quick commands - use event delegation on container
        this.elements.messagesContainer.addEventListener('click', (e) => {
            const btn = e.target.closest('.quick-cmd');
            if (btn && btn.dataset.cmd) {
                e.stopPropagation();
                this.elements.messageInput.value = btn.dataset.cmd;
                this.sendMessage();
            }
        });

        // Keyboard shortcuts
        document.addEventListener('keydown', (e) => {
            // Escape to stop streaming or close modals
            if (e.key === 'Escape') {
                if (this.isStreaming) {
                    this.interrupt();
                } else if (!this.elements.consentModal.classList.contains('hidden')) {
                    // Don't close consent modal with Escape
                } else if (!this.elements.settingsModal.classList.contains('hidden')) {
                    this.hideSettings();
                }
            }
        });
    }

    setupMarkdown() {
        // Configure marked.js v11+
        if (typeof marked !== 'undefined') {
            marked.setOptions({
                breaks: true,
                gfm: true  // GitHub Flavored Markdown (tables, strikethrough, etc.)
            });
        }
    }

    // === Server Connection ===

    /**
     * Connect to the server with circuit breaker pattern (v1.13.6)
     *
     * @param {boolean} withRetry - If true, retry with exponential backoff
     */
    async connectToServer(withRetry = false) {
        this.updateServerStatus('connecting');

        // Circuit breaker pattern: retry with exponential backoff (v1.13.6)
        const retryDelays = withRetry ? [1000, 2000, 3000, 5000] : [0];

        for (let i = 0; i < retryDelays.length; i++) {
            if (i > 0) {
                await new Promise(resolve => setTimeout(resolve, retryDelays[i]));
            }

            try {
                const response = await fetch(`${this.serverUrl}/health`, {
                    signal: AbortSignal.timeout(3000)
                });

                if (response.ok) {
                    const health = await response.json();
                    this.elements.versionBadge.textContent = `v${health.version}`;
                    this.updateServerStatus('connected');

                    // Show idle timeout info if configured (v1.13.6)
                    if (health.idle_timeout && health.idle_timeout > 0) {
                        console.log(`[PpxaiApp] Server idle timeout: ${health.idle_timeout}s`);
                    }

                    await this.loadInitialState();
                    return true;
                }
            } catch (error) {
                // Continue to next retry
                console.log(`[PpxaiApp] Connection attempt ${i + 1}/${retryDelays.length} failed`);
            }
        }

        // All retries failed
        this.updateServerStatus('disconnected');
        if (!withRetry) {
            this.showError('Could not connect to server. Start with: ppxai-server');
        }
        return false;
    }

    updateServerStatus(status) {
        const badge = this.elements.serverBadge;
        badge.classList.remove('connected', 'disconnected', 'connecting');

        switch (status) {
            case 'connected':
                badge.classList.add('connected');
                this.elements.serverStatus.textContent = 'Connected';
                badge.title = 'Server connected. Click to stop server.';
                break;
            case 'disconnected':
                badge.classList.add('disconnected');
                this.elements.serverStatus.textContent = 'Disconnected';
                badge.title = 'Server not running. Click to retry connection.\nStart server with: ppxai-server';
                break;
            case 'connecting':
                badge.classList.add('connecting');
                this.elements.serverStatus.textContent = 'Connecting...';
                badge.title = 'Connecting to server...';
                break;
        }
    }

    /**
     * Handle Quit button - shutdown server and close tab (v1.13.6)
     */
    async handleQuit() {
        const confirmed = confirm('Stop the ppxai server and close this tab?');
        if (!confirmed) return;

        try {
            this.updateServerStatus('connecting');
            this.elements.serverStatus.textContent = 'Stopping...';

            await fetch(`${this.serverUrl}/shutdown`, {
                method: 'POST',
                headers: this.getSessionHeaders(),
                signal: AbortSignal.timeout(5000)
            });
        } catch (error) {
            // Expected - server shuts down before responding
            console.log('Server shutdown (connection closed as expected)');
        }

        // Close the tab
        window.close();

        // If window.close() didn't work (not opened by script), show message
        this.updateServerStatus('disconnected');
        this.showSystemMessage('Server stopped. You can close this tab.');
    }

    /**
     * Reload configuration from file without restarting server
     */
    async reloadConfig() {
        try {
            const resp = await fetch(`${this.serverUrl}/config/reload`, {
                method: 'POST',
                headers: this.getSessionHeaders()
            });
            if (resp.ok) {
                const result = await resp.json();
                this.showSystemMessage(`Configuration reloaded from ${result.config_path || 'defaults'}`);
            } else {
                this.showSystemMessage('Failed to reload configuration', 'error');
            }
        } catch (error) {
            console.error('Failed to reload config:', error);
            this.showSystemMessage('Failed to reload configuration', 'error');
        }
    }

    async handleFolderBadgeClick() {
        const currentPath = this.elements.folderPath.textContent || '';
        const newPath = prompt('Enter working directory path:', currentPath === 'No folder' ? '' : currentPath);
        if (newPath !== null && newPath.trim()) {
            await this.setWorkingDir(newPath.trim());
        }
    }

    async loadWorkingDir() {
        try {
            const resp = await fetch(`${this.serverUrl}/context/working_dir`, {
                headers: this.getSessionHeaders()
            });
            if (resp.ok) {
                const data = await resp.json();
                this.updateFolderBadge(data.path);
            }
        } catch (e) {
            console.error('Failed to load working directory:', e);
        }
    }

    async setWorkingDir(path) {
        try {
            const resp = await fetch(`${this.serverUrl}/context/working_dir`, {
                method: 'POST',
                headers: this.getSessionHeaders(true),
                body: JSON.stringify({ path })
            });
            if (resp.ok) {
                const data = await resp.json();
                this.updateFolderBadge(data.path);
                this.showSystemMessage(`Working directory set to: ${data.path}`);
            } else {
                const error = await resp.json();
                this.showError(`Failed to set working directory: ${error.detail}`);
            }
        } catch (e) {
            this.showError(`Failed to set working directory: ${e.message}`);
        }
    }

    updateFolderBadge(path) {
        if (!path) {
            this.elements.folderPath.textContent = 'No folder';
            return;
        }
        // Show just the last component for brevity
        const parts = path.split('/');
        const shortName = parts[parts.length - 1] || parts[parts.length - 2] || path;
        this.elements.folderPath.textContent = shortName;
        this.elements.folderBadge.title = `Working directory: ${path}\nClick to change`;
    }

    async loadInitialState() {
        try {
            // Load providers
            const providersResp = await fetch(`${this.serverUrl}/providers`, {
                headers: this.getSessionHeaders()
            });
            const providersData = await providersResp.json();
            this.populateProviders(providersData.providers);

            // Load status
            const statusResp = await fetch(`${this.serverUrl}/status`, {
                headers: this.getSessionHeaders()
            });
            const status = await statusResp.json();
            this.currentProvider = status.provider;
            this.currentModel = status.model;
            this.toolsEnabled = status.tools_enabled;

            // Select current provider/model
            this.elements.providerSelect.value = this.currentProvider;
            await this.loadModels();
            this.elements.modelSelect.value = this.currentModel;

            // Update badges
            this.updateToolsBadge();

            // Load working directory
            await this.loadWorkingDir();

            // Load tools status
            const toolsResp = await fetch(`${this.serverUrl}/tools`, {
                headers: this.getSessionHeaders()
            });
            const toolsData = await toolsResp.json();
            this.verbose = toolsData.verbose || false;

            // Load agent status
            try {
                const agentResp = await fetch(`${this.serverUrl}/agent/status`, {
                    headers: this.getSessionHeaders()
                });
                const agentData = await agentResp.json();
                this.agentMode = agentData.agent_mode;
                this.updateAgentBadge();

                // Update undo badge
                if (agentData.checkpoint && agentData.checkpoint.last_checkpoint) {
                    this.lastCheckpoint = agentData.checkpoint.last_checkpoint;
                    this.elements.undoBadge.classList.remove('hidden');
                    this.elements.undoBadge.disabled = !agentData.checkpoint.is_valid;
                } else {
                    this.elements.undoBadge.classList.add('hidden');
                }
            } catch {}

            // Load usage and context info
            await this.updateUsage();
            await this.updateContextInfo();

            // Load debug log status
            try {
                const debugResp = await fetch(`${this.serverUrl}/debug-log`, {
                    headers: this.getSessionHeaders()
                });
                const debugData = await debugResp.json();
                this.debugLogEnabled = debugData.enabled;
                this.updateDebugIndicator();
            } catch {}

            // v1.13.9: Check for last session to restore
            await this.checkSessionRestore();

        } catch (error) {
            this.showError(`Failed to load initial state: ${error.message}`);
        }
    }

    /**
     * Check if there's a last session to restore (v1.13.9)
     */
    async checkSessionRestore() {
        try {
            const response = await fetch(`${this.serverUrl}/sessions/last`, {
                headers: this.getSessionHeaders()
            });
            const data = await response.json();

            if (data.last_session && data.last_session.name) {
                const session = data.last_session;
                const msgCount = session.message_count || 0;

                // Prompt user to restore
                const restorePrompt = session.dirty
                    ? `Restore interrupted session "${session.name}" (${msgCount} messages)?`
                    : `Restore last session "${session.name}" (${msgCount} messages)?`;

                if (confirm(restorePrompt)) {
                    await this.restoreLastSession();
                }
            }
        } catch (error) {
            console.log('[PpxaiApp] No session to restore:', error.message);
        }
    }

    /**
     * Restore the last session (v1.13.9)
     * v1.15.3: Now restores provider and model from session metadata
     */
    async restoreLastSession() {
        try {
            const response = await fetch(`${this.serverUrl}/sessions/restore`, {
                method: 'POST',
                headers: this.getSessionHeaders()
            });

            if (response.ok) {
                const data = await response.json();
                this.showSystemMessage(`✓ Session restored: ${data.name} (${data.message_count} messages)`);

                // Update state from restored session
                if (data.working_dir) {
                    this.elements.folderPath.textContent = data.working_dir;
                }
                if (data.tools_enabled) {
                    this.toolsEnabled = true;
                    this.updateToolsBadge();
                }

                // Restore provider and model (v1.15.3)
                if (data.provider) {
                    this.currentProvider = data.provider;
                    this.elements.providerSelect.value = data.provider;
                    console.log(`[PpxaiApp] Restored provider: ${data.provider}`);
                }
                if (data.model) {
                    this.currentModel = data.model;
                    // Reload models for the restored provider
                    await this.loadModels();
                    this.elements.modelSelect.value = data.model;
                    console.log(`[PpxaiApp] Restored model: ${data.model}`);
                }

                // Reload working dir badge
                await this.loadWorkingDir();
            } else {
                const error = await response.json();
                this.showSystemMessage(`Failed to restore session: ${error.detail}`, 'error');
            }
        } catch (error) {
            console.error('[PpxaiApp] Failed to restore session:', error);
            this.showSystemMessage('Failed to restore session', 'error');
        }
    }

    populateProviders(providers) {
        this.elements.providerSelect.innerHTML = '';
        providers.forEach(p => {
            const option = document.createElement('option');
            option.value = p.id;
            option.textContent = p.name;
            if (!p.has_api_key) option.disabled = true;
            this.elements.providerSelect.appendChild(option);
        });
    }

    async loadModels() {
        try {
            const response = await fetch(`${this.serverUrl}/models`, {
                headers: this.getSessionHeaders()
            });
            const data = await response.json();

            this.elements.modelSelect.innerHTML = '';
            data.models.forEach(m => {
                const option = document.createElement('option');
                option.value = m.id;
                option.textContent = m.name;
                option.title = m.description;
                this.elements.modelSelect.appendChild(option);
            });
        } catch (error) {
            console.error('Failed to load models:', error);
        }
    }

    async handleProviderChange() {
        const providerId = this.elements.providerSelect.value;
        try {
            const resp = await fetch(`${this.serverUrl}/providers`, {
                method: 'POST',
                headers: this.getSessionHeaders(true),
                body: JSON.stringify({ provider: providerId })
            });
            const data = await resp.json();
            this.currentProvider = providerId;
            await this.loadModels();

            // Get new default model
            const statusResp = await fetch(`${this.serverUrl}/status`, {
                headers: this.getSessionHeaders()
            });
            const status = await statusResp.json();
            this.currentModel = status.model;
            this.elements.modelSelect.value = this.currentModel;

            let msg = `Switched to provider: ${providerId}`;
            if (data.context_reset) {
                msg += ` (${data.context_reset} messages cleared from context)`;
            }
            this.showSystemMessage(msg);
        } catch (error) {
            this.showError(`Failed to switch provider: ${error.message}`);
        }
    }

    async handleModelChange() {
        const modelId = this.elements.modelSelect.value;
        try {
            const resp = await fetch(`${this.serverUrl}/models`, {
                method: 'POST',
                headers: this.getSessionHeaders(true),
                body: JSON.stringify({ model: modelId })
            });
            const data = await resp.json();
            this.currentModel = modelId;
            let msg = `Switched to model: ${modelId}`;
            if (data.context_reset) {
                msg += ` (${data.context_reset} messages cleared from context)`;
            }
            this.showSystemMessage(msg);
        } catch (error) {
            this.showError(`Failed to switch model: ${error.message}`);
        }
    }

    // === Tools & Agent ===

    async toggleTools() {
        try {
            const newState = !this.toolsEnabled;
            await fetch(`${this.serverUrl}/tools`, {
                method: 'POST',
                headers: this.getSessionHeaders(true),
                body: JSON.stringify({ enabled: newState })
            });
            this.toolsEnabled = newState;
            this.updateToolsBadge();
            this.showSystemMessage(`Tools ${newState ? 'enabled' : 'disabled'}`);
        } catch (error) {
            this.showError(`Failed to toggle tools: ${error.message}`);
        }
    }

    updateToolsBadge() {
        this.elements.toolsStatus.textContent = `Tools: ${this.toolsEnabled ? 'on' : 'off'}`;
        this.elements.toolsBadge.classList.toggle('enabled', this.toolsEnabled);
    }

    async toggleAgent() {
        try {
            const newState = !this.agentMode;
            const endpoint = newState ? '/agent/enable' : '/agent/disable';

            const response = await fetch(`${this.serverUrl}${endpoint}`, {
                method: 'POST',
                headers: this.getSessionHeaders(true)
            });

            if (response.ok) {
                const data = await response.json();
                this.agentMode = data.agent_mode;
                this.toolsEnabled = data.tools_enabled || this.toolsEnabled;
                this.updateAgentBadge();
                this.updateToolsBadge();
                this.showSystemMessage(`Agent mode ${this.agentMode ? 'enabled' : 'disabled'}`);
            }
        } catch (error) {
            this.showError(`Failed to toggle agent: ${error.message}`);
        }
    }

    updateAgentBadge() {
        this.elements.agentStatus.textContent = `Agent: ${this.agentMode ? 'on' : 'off'}`;
        this.elements.agentBadge.classList.toggle('enabled', this.agentMode);
    }

    async undoCheckpoint() {
        try {
            const response = await fetch(`${this.serverUrl}/checkpoint/undo`, {
                method: 'POST',
                headers: this.getSessionHeaders(true)
            });

            if (response.ok) {
                const data = await response.json();
                this.showSystemMessage(data.message || 'Checkpoint restored');
                this.elements.undoBadge.classList.add('hidden');
                this.lastCheckpoint = null;
            } else {
                const error = await response.text();
                this.showError(`Undo failed: ${error}`);
            }
        } catch (error) {
            this.showError(`Failed to undo: ${error.message}`);
        }
    }

    // === Chat ===

    async sendMessage() {
        const content = this.elements.messageInput.value.trim();
        if (!content || this.isStreaming || this.isSending) return;

        // Debounce guard to prevent rapid-fire
        this.isSending = true;

        // Save to history
        if (content !== this.commandHistory[0]) {
            this.commandHistory.unshift(content);
            if (this.commandHistory.length > 100) this.commandHistory.pop();
            localStorage.setItem('ppxai-history', JSON.stringify(this.commandHistory));
        }
        this.historyIndex = -1;

        // Clear input
        this.elements.messageInput.value = '';
        this.elements.messageInput.style.height = 'auto';
        this.hideAutocomplete();

        // Hide welcome message
        const welcome = this.elements.messagesContainer.querySelector('.welcome-message');
        if (welcome) welcome.remove();

        // Handle slash commands
        if (content.startsWith('/')) {
            try {
                await this.handleSlashCommand(content);
            } finally {
                this.isSending = false;
            }
            return;
        }

        // Show user message
        this.addMessage('user', content);

        // Start streaming (isSending will be reset by streamChat's finally block)
        await this.streamChat(content);
    }

    async streamChat(message) {
        this.isStreaming = true;
        this.elements.streamingBadge.classList.remove('hidden');
        this.currentAbortController = new AbortController();

        // Create assistant message container
        const msgEl = this.addMessage('assistant', '', true);
        const contentEl = msgEl.querySelector('.message-content');
        let fullContent = '';

        // Track this as the current assistant message for correct tool call ordering
        this.currentAssistantMessage = msgEl;

        try {
            const response = await fetch(`${this.serverUrl}/chat`, {
                method: 'POST',
                headers: this.getSessionHeaders(true),
                body: JSON.stringify({ message }),
                signal: this.currentAbortController.signal
            });

            if (!response.ok) {
                throw new Error(`Server error: ${response.statusText}`);
            }

            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            let buffer = '';

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;

                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split('\n');
                buffer = lines.pop() || '';

                for (const line of lines) {
                    if (line.startsWith('data: ')) {
                        try {
                            const event = JSON.parse(line.slice(6));
                            fullContent = this.handleStreamEvent(event, contentEl, fullContent);
                        } catch (e) {
                            if (!(e instanceof SyntaxError)) throw e;
                        }
                    }
                }
            }

            // Final render
            if (fullContent) {
                contentEl.innerHTML = this.renderMarkdown(fullContent);
            }

        } catch (error) {
            if (error.name === 'AbortError') {
                this.showSystemMessage('*Interrupted*');
            } else {
                this.showError(`Chat error: ${error.message}`);
            }
        } finally {
            this.isStreaming = false;
            this.isSending = false;
            this.elements.streamingBadge.classList.add('hidden');
            this.currentAbortController = null;
            this.currentAssistantMessage = null;
            await this.updateUsage();
            await this.updateContextInfo();
            this.scrollToBottom();
        }
    }

    handleStreamEvent(event, contentEl, fullContent) {
        switch (event.type) {
            case 'reasoning_chunk':
                // v1.13.9: Reasoning tokens from DeepSeek R1, GPT-OSS 120B
                // Show in collapsible thinking section
                this.appendReasoningChunk(contentEl, event.data);
                break;

            case 'stream_chunk':
                // v1.13.2: Clear thinking indicator when first content arrives
                if (!fullContent && event.data) {
                    this.clearThinkingIndicator(contentEl);
                    // v1.13.9: Close reasoning section when content starts
                    this.closeReasoningSection(contentEl);
                }
                fullContent += event.data || '';
                // Throttle markdown rendering
                if (fullContent.length % 50 === 0 || fullContent.length < 100) {
                    contentEl.innerHTML = this.renderMarkdown(fullContent);
                    this.scrollToBottom();
                }
                break;

            case 'stream_end':
                // v1.13.2: Clear thinking indicator on stream end
                this.clearThinkingIndicator(contentEl);
                // Full response (especially when tools are used)
                if (event.data && event.data.trim()) {
                    fullContent = event.data;
                    contentEl.innerHTML = this.renderMarkdown(fullContent);
                } else if (!fullContent) {
                    // v1.13.2: Handle empty responses from AI (common with GPT-OSS 120B after tool iterations)
                    contentEl.innerHTML = '<em class="empty-response">Task completed. (No additional response from AI)</em>';
                }
                break;

            case 'tool_group_start':
                this.onToolGroupStart(event.data);
                break;

            case 'tool_group_end':
                this.onToolGroupEnd(event.data);
                break;

            case 'tool_call':
                this.showToolCall(event.data);
                break;

            case 'tool_result':
                this.showToolResult(event.data);
                break;

            case 'tool_error':
                // event.data is {tool: "...", error: "..."} object
                const toolErr = event.data;
                const toolErrMsg = toolErr?.error || (typeof toolErr === 'string' ? toolErr : JSON.stringify(toolErr));
                this.showError(`Tool error (${toolErr?.tool || 'unknown'}): ${toolErrMsg}`);
                break;

            case 'consent_request':
                this.handleConsentRequest(event.data);
                break;

            case 'context_injected':
                this.showContextInjected(event.data);
                break;

            case 'status':
                // v1.16.0: Suppress individual checkpoint/snapshot bubbles — the
                // final "Changes committed: <hash>" message provides sufficient context.
                if (typeof event.data === 'string' && (event.data.startsWith('✓ Checkpoint created:') || event.data.startsWith('✓ Snapshot saved:'))) {
                    this._checkpointCount = (this._checkpointCount || 0) + 1;
                } else {
                    let msg = event.data;
                    // Enrich commit message with checkpoint count
                    if (this._checkpointCount > 0 && typeof msg === 'string' && msg.startsWith('✓ Changes committed:')) {
                        msg += ` (${this._checkpointCount} file${this._checkpointCount !== 1 ? 's' : ''} checkpointed)`;
                        this._checkpointCount = 0;
                    }
                    this.showSystemMessage(msg);
                }
                break;

            case 'working_dir_changed':
                // Update folder badge when working directory changes (v1.13.2)
                if (event.data && event.data.path) {
                    this.updateFolderBadge(event.data.path);
                }
                break;

            case 'agent_iteration':
                const iter = event.data;
                this.showSystemMessage(`━━━ Iteration ${iter.iteration || 0}/${iter.max || 10} ━━━`);
                break;

            case 'agent_complete':
                this.showSystemMessage('✅ Task completed!');
                // Only show undo badge if a commit was made (checkpoint exists)
                if (event.data && event.data.commit) {
                    this.elements.undoBadge.classList.remove('hidden');
                }
                break;

            case 'agent_max_iterations':
                this.showSystemMessage('⚠️ Max iterations reached. Task may be incomplete.');
                break;

            case 'info':
                // v1.13.2: Display processing/iteration info messages
                // These are emitted during tool iterations to show progress
                const infoMsg = typeof event.data === 'string' ? event.data : (event.data?.message || '');
                if (infoMsg) {
                    this.updateThinkingIndicator(infoMsg, contentEl);
                }
                break;

            case 'error':
                this.showError(event.data);
                break;

            case 'display_file':
                // v1.15.2: Handle display_file event from AI tool
                if (event.data && event.data.filepath) {
                    this.displayFileFromEvent(event.data.filepath);
                }
                break;

            case 'warning':
                // v1.15.2: Handle validation warnings (hallucination detection)
                if (event.data) {
                    this.showValidationWarning(event.data);
                }
                break;
        }

        return fullContent;
    }

    async interrupt() {
        try {
            await fetch(`${this.serverUrl}/interrupt`, {
                method: 'POST',
                headers: this.getSessionHeaders(),
                signal: AbortSignal.timeout(1000)
            });
        } catch {}

        if (this.currentAbortController) {
            this.currentAbortController.abort();
        }
    }

    // === Slash Commands ===

    async handleSlashCommand(input) {
        // Prevent recursive/repeated calls
        if (this.isHandlingCommand) {
            console.warn('handleSlashCommand called while already handling:', input);
            return;
        }
        this.isHandlingCommand = true;

        try {
            const parts = input.trim().split(/\s+/);
            const cmd = parts[0].toLowerCase();
            const args = parts.slice(1).join(' ');

            this.showSystemMessage(`> ${input}`);

        switch (cmd) {
            case '/help':
                this.showHelp();
                break;

            case '/clear':
                await this.clearConversation();
                break;

            case '/save':
                await this.saveSession(args);
                break;

            case '/export':
                await this.exportAnswer(args);
                break;

            case '/load':
                await this.loadSession(args);
                break;

            case '/sessions':
                await this.listSessions();
                break;

            case '/model':
                await this.handleModelCommand(args);
                break;

            case '/provider':
                await this.handleProviderCommand(args);
                break;

            case '/tools':
                await this.handleToolsCommand(args);
                break;

            case '/agent':
                if (args === 'on') {
                    if (!this.agentMode) await this.toggleAgent();
                } else if (args === 'off') {
                    if (this.agentMode) await this.toggleAgent();
                } else if (args) {
                    // Run agent task
                    this.addMessage('user', input);
                    await this.streamChat(`/agent ${args}`);
                } else {
                    this.showSystemMessage(`Agent mode: ${this.agentMode ? 'on' : 'off'}`);
                }
                break;

            case '/checkpoint':
                await this.handleCheckpointCommand(args);
                break;

            case '/usage':
                await this.handleUsageCommand(args);
                break;

            case '/status':
                await this.showStatus();
                break;

            case '/context':
                await this.handleContextCommand(args);
                break;

            case '/theme':
                this.handleThemeCommand(args);
                break;

            case '/show':
            case '/cat':
                await this.handleShowCommand(args);
                break;

            case '/edit':
                await this.handleEditCommand(args);
                break;

            case '/cd':
                await this.handleCdCommand(args);
                break;

            case '/pwd':
                await this.handlePwdCommand();
                break;

            case '/ls':
                await this.handleLsCommand(args);
                break;

            case '/tree':
                await this.handleTreeCommand(args);
                break;

            case '/preview':
                await this.handlePreviewCommand(args);
                break;

            case '/config':
                await this.handleConfigCommand(args);
                break;

            case '/generate':
            case '/explain':
            case '/test':
            case '/docs':
            case '/debug':
            case '/implement':
            case '/convert':
            case '/spec':
                // Send as regular message - server handles these
                this.addMessage('user', input);
                await this.streamChat(input);
                break;

            default:
                this.showError(`Unknown command: ${cmd}. Type /help for available commands.`);
        }
        } finally {
            this.isHandlingCommand = false;
        }
    }

    showHelp() {
        // Use shared help generator if available
        let helpText;
        if (typeof SharedCommands !== 'undefined' && SharedCommands.generateHelpText) {
            helpText = SharedCommands.generateHelpText();
        } else {
            helpText = '**Available Commands:**\n\n';
            Object.entries(this.slashCommands).forEach(([cmd, info]) => {
                helpText += `\`${info.usage}\` - ${info.description}\n`;
            });
        }

        helpText += '\n**Keyboard Shortcuts:**\n';
        helpText += '- `Esc` - Stop streaming\n';
        helpText += '- `↑/↓` - Command history\n';
        helpText += '- `@file` - Reference a file\n';
        helpText += '- `@git` - Include git diff\n';
        helpText += '- `@tree` - Include project structure\n';

        this.addMessage('system', helpText);
    }

    async handleModelCommand(args) {
        if (!args || args === 'list') {
            try {
                const response = await fetch(`${this.serverUrl}/models`, {
                    headers: this.getSessionHeaders()
                });
                const data = await response.json();
                let text = '**Available Models:**\n\n';
                data.models.forEach(m => {
                    const current = m.id === this.currentModel ? ' *(current)*' : '';
                    text += `- \`${m.id}\`${current} - ${m.name}\n`;
                });
                this.addMessage('system', text);
            } catch (error) {
                this.showError(`Failed to list models: ${error.message}`);
            }
        } else {
            this.elements.modelSelect.value = args;
            await this.handleModelChange();
        }
    }

    async handleProviderCommand(args) {
        if (!args || args === 'list') {
            try {
                const response = await fetch(`${this.serverUrl}/providers`, {
                    headers: this.getSessionHeaders()
                });
                const data = await response.json();
                let text = '**Available Providers:**\n\n';
                data.providers.forEach(p => {
                    const current = p.id === this.currentProvider ? ' *(current)*' : '';
                    const status = p.has_api_key ? '✓' : '✗';
                    text += `- \`${p.id}\`${current} [${status}] - ${p.name}\n`;
                });
                this.addMessage('system', text);
            } catch (error) {
                this.showError(`Failed to list providers: ${error.message}`);
            }
        } else {
            this.elements.providerSelect.value = args;
            await this.handleProviderChange();
        }
    }

    async handleToolsCommand(args) {
        const subCmd = args.split(/\s+/)[0];

        switch (subCmd) {
            case 'enable':
            case 'on':
                if (!this.toolsEnabled) await this.toggleTools();
                break;

            case 'disable':
            case 'off':
                if (this.toolsEnabled) await this.toggleTools();
                break;

            case 'status':
            case '':
                try {
                    const response = await fetch(`${this.serverUrl}/tools`, {
                        headers: this.getSessionHeaders()
                    });
                    const data = await response.json();
                    let text = '**Tools Status:**\n\n';
                    text += `- Enabled: ${data.enabled ? 'yes' : 'no'}\n`;
                    text += `- Tool count: ${data.tools.length}\n`;
                    text += `- Verbose: ${data.verbose ? 'on' : 'off'}\n`;
                    this.addMessage('system', text);
                } catch (error) {
                    this.showError(`Failed to get tools status: ${error.message}`);
                }
                break;

            case 'list':
                try {
                    const response = await fetch(`${this.serverUrl}/tools`, {
                        headers: this.getSessionHeaders()
                    });
                    const data = await response.json();
                    let text = '**Available Tools:**\n\n';
                    data.tools.forEach(t => {
                        text += `- \`${t.name}\` - ${t.description}\n`;
                    });
                    this.addMessage('system', text);
                } catch (error) {
                    this.showError(`Failed to list tools: ${error.message}`);
                }
                break;

            case 'set':
                const setParts = args.split(/\s+/).slice(1);
                if (setParts[0] === 'verbose') {
                    const value = setParts[1] === 'on' || setParts[1] === 'true';
                    try {
                        await fetch(`${this.serverUrl}/tools/config`, {
                            method: 'POST',
                            headers: this.getSessionHeaders(true),
                            body: JSON.stringify({ setting: 'verbose', value: value ? 'on' : 'off' })
                        });
                        this.verbose = value;
                        this.showSystemMessage(`Verbose mode ${value ? 'enabled' : 'disabled'}`);
                    } catch (error) {
                        this.showError(`Failed to set verbose: ${error.message}`);
                    }
                } else {
                    this.showError('Usage: /tools set verbose on|off');
                }
                break;

            case 'config':
                try {
                    const response = await fetch(`${this.serverUrl}/tools`, {
                        headers: this.getSessionHeaders()
                    });
                    const data = await response.json();
                    let text = '**Tool Configuration:**\n\n';
                    text += `- Enabled: ${data.enabled ? 'yes' : 'no'}\n`;
                    text += `- Max iterations: ${data.max_iterations || 15}\n`;
                    text += `- Verbose: ${data.verbose ? 'on' : 'off'}\n`;
                    text += `- Consent mode: ${data.consent_mode || 'default'}\n`;
                    text += `- Tool count: ${data.tools.length}\n`;
                    this.addMessage('system', text);
                } catch (error) {
                    this.showError(`Failed to get tool config: ${error.message}`);
                }
                break;

            case 'agent':
                const agentArg = args.split(/\s+/)[1];
                if (agentArg === 'on' || agentArg === 'enable') {
                    if (!this.agentMode) await this.toggleAgent();
                    this.showSystemMessage('Agent mode enabled. Tools auto-enabled.');
                } else if (agentArg === 'off' || agentArg === 'disable') {
                    if (this.agentMode) await this.toggleAgent();
                    this.showSystemMessage('Agent mode disabled.');
                } else {
                    const status = this.agentMode ? 'ON' : 'OFF';
                    this.addMessage('system', `**Agent Mode:** ${status}\n\nUsage: \`/tools agent on|off\`\nOr use \`/agent <task>\` to run an autonomous task.`);
                }
                break;

            case 'help':
                const toolName = args.split(/\s+/)[1];
                if (toolName) {
                    try {
                        const response = await fetch(`${this.serverUrl}/tools/help/${encodeURIComponent(toolName)}`, {
                            headers: this.getSessionHeaders()
                        });
                        if (!response.ok) {
                            const err = await response.json();
                            this.showError(err.detail || `Tool not found: ${toolName}`);
                            return;
                        }
                        const data = await response.json();
                        let text = `**Tool: ${data.name}**\n\n`;
                        text += `${data.description}\n\n`;
                        if (data.parameters && data.parameters.properties) {
                            text += '**Parameters:**\n';
                            Object.entries(data.parameters.properties).forEach(([name, prop]) => {
                                const required = data.parameters.required?.includes(name) ? ' *(required)*' : '';
                                text += `- \`${name}\`${required}: ${prop.description || prop.type || 'no description'}\n`;
                            });
                        }
                        this.addMessage('system', text);
                    } catch (error) {
                        this.showError(`Failed to get tool help: ${error.message}`);
                    }
                } else {
                    this.addMessage('system', '**Tool Help**\n\nUsage: `/tools help <tool-name>` - Show help for a specific tool\n\nUse `/tools list` to see available tools.');
                }
                break;

            default:
                this.showError(`Unknown /tools subcommand: ${subCmd}. Available: enable, disable, status, list, config, set, agent, help`);
        }
    }

    async handleCheckpointCommand(args) {
        const subCmd = args.split(/\s+/)[0];

        switch (subCmd) {
            case 'status':
            case '':
                try {
                    const response = await fetch(`${this.serverUrl}/agent/status`, {
                        headers: this.getSessionHeaders()
                    });
                    const data = await response.json();
                    let text = '**Checkpoint Status:**\n\n';
                    if (data.checkpoint) {
                        text += `- Backend: ${data.checkpoint.backend}\n`;
                        text += `- Enabled: ${data.checkpoint.enabled ? 'yes' : 'no'}\n`;
                        text += `- Last checkpoint: ${data.checkpoint.last_checkpoint || 'none'}\n`;
                        text += `- Valid: ${data.checkpoint.is_valid ? 'yes' : 'no'}\n`;
                        if (!data.checkpoint.is_valid) {
                            text += `- Reason: ${data.checkpoint.validity_reason}\n`;
                        }
                    } else {
                        text += 'Checkpoint system not available.\n';
                    }
                    this.addMessage('system', text);
                } catch (error) {
                    this.showError(`Failed to get checkpoint status: ${error.message}`);
                }
                break;

            case 'list':
                try {
                    const response = await fetch(`${this.serverUrl}/checkpoint/list`, {
                        headers: this.getSessionHeaders()
                    });
                    const data = await response.json();
                    let text = '**Recent Checkpoints:**\n\n';
                    if (data.checkpoints.length === 0) {
                        text += 'No checkpoints found.\n';
                    } else {
                        data.checkpoints.forEach(cp => {
                            text += `- \`${cp.id}\` - ${cp.description} (${cp.timestamp})\n`;
                        });
                    }
                    this.addMessage('system', text);
                } catch (error) {
                    this.showError(`Failed to list checkpoints: ${error.message}`);
                }
                break;

            case 'undo':
                await this.undoCheckpoint();
                break;

            case 'backend':
                const backendArg = args.split(/\s+/)[1];
                if (backendArg) {
                    const validBackends = ['git', 'file', 'auto', 'none'];
                    if (!validBackends.includes(backendArg)) {
                        this.showError(`Invalid backend: ${backendArg}. Valid options: ${validBackends.join(', ')}`);
                        return;
                    }
                    try {
                        const response = await fetch(`${this.serverUrl}/checkpoint/backend`, {
                            method: 'POST',
                            headers: this.getSessionHeaders(true),
                            body: JSON.stringify({ backend: backendArg })
                        });
                        if (!response.ok) {
                            const err = await response.json();
                            this.showError(err.detail || 'Failed to set backend');
                            return;
                        }
                        const data = await response.json();
                        this.showSystemMessage(`Checkpoint backend set to: ${data.backend}`);
                    } catch (error) {
                        this.showError(`Failed to set backend: ${error.message}`);
                    }
                } else {
                    this.addMessage('system', '**Checkpoint Backend**\n\nUsage: `/checkpoint backend <git|file|auto|none>`\n\n- `git`: Use git commits (recommended for git repos)\n- `file`: Use file snapshots (~/.ppxai/checkpoints/)\n- `auto`: Auto-detect best backend\n- `none`: Disable checkpoints');
                }
                break;

            case 'clear':
                try {
                    const response = await fetch(`${this.serverUrl}/checkpoint/clear`, {
                        method: 'POST',
                        headers: this.getSessionHeaders(true),
                        body: JSON.stringify({ keep_last: 0 })
                    });
                    if (!response.ok) {
                        const err = await response.json();
                        this.showError(err.detail || 'Failed to clear checkpoints');
                        return;
                    }
                    const data = await response.json();
                    this.showSystemMessage(data.message || `Cleared ${data.removed} checkpoint(s)`);
                } catch (error) {
                    this.showError(`Failed to clear checkpoints: ${error.message}`);
                }
                break;

            case 'info':
                const checkpointId = args.split(/\s+/)[1];
                if (checkpointId) {
                    try {
                        const response = await fetch(`${this.serverUrl}/checkpoint/info/${encodeURIComponent(checkpointId)}`, {
                            headers: this.getSessionHeaders()
                        });
                        if (!response.ok) {
                            const err = await response.json();
                            this.showError(err.detail || `Checkpoint not found: ${checkpointId}`);
                            return;
                        }
                        const data = await response.json();
                        let text = '**Checkpoint Details:**\n\n';
                        text += `- ID: \`${data.id}\`\n`;
                        text += `- Description: ${data.description}\n`;
                        text += `- Timestamp: ${data.timestamp}\n`;
                        text += `- Status: ${data.is_current ? (data.is_valid ? 'Current (can undo)' : 'Stale (cannot undo)') : 'Historical'}\n`;
                        this.addMessage('system', text);
                    } catch (error) {
                        this.showError(`Failed to get checkpoint info: ${error.message}`);
                    }
                } else {
                    this.addMessage('system', '**Checkpoint Info**\n\nUsage: `/checkpoint info <checkpoint_id>`\n\nUse `/checkpoint list` to see available checkpoints.');
                }
                break;

            default:
                this.showError(`Unknown /checkpoint subcommand: ${subCmd}. Available: status, list, undo, backend, clear, info`);
        }
    }

    async handleUsageCommand(args) {
        // v1.16.1: Delegate to shared command handler via POST /command/usage
        try {
            const response = await fetch(`${this.serverUrl}/command/usage`, {
                method: 'POST',
                headers: this.getSessionHeaders(true),
                body: JSON.stringify({ args: args.trim() })
            });
            if (!response.ok) {
                const detail = await response.text();
                this.showError(`Usage command failed (${response.status}): ${detail}`);
                return;
            }
            const result = await response.json();
            this.renderCommandResult(result);
        } catch (error) {
            this.showError(`Failed to get usage: ${error.message}`);
        }
    }

    /**
     * Render a server-side CommandResult as markdown in the chat.
     *
     * Generic dispatcher for all command result types returned by
     * POST /command/{name}. Works for any command, not just /usage.
     *
     * v1.16.1: Added for CommandFactory server-side execution.
     */
    renderCommandResult(result) {
        switch (result.type) {
            case 'TableResult':
            case 'DirectoryListingResult':
                this.addMessage('system', window.SharedFormatters.formatTableResult(result));
                break;
            case 'ConfirmationResult':
            case 'NotificationResult':
                this.showSystemMessage(result.message);
                break;
            case 'ErrorResult':
                this.showError(result.message +
                    (result.suggestions && result.suggestions.length
                        ? '\n' + result.suggestions.join('\n') : ''));
                break;
            case 'KeyValueResult':
                this.addMessage('system', window.SharedFormatters.formatKeyValueResult(result));
                break;
            default:
                this.showSystemMessage(result.message);
        }
    }

    /**
     * Handle /context command - show context usage and injected files (v1.13.9)
     * v1.14.0: Added 'hints' subcommand for bootstrap context
     */
    async handleContextCommand(args) {
        const subCmd = args.trim().toLowerCase();

        try {
            if (subCmd === 'clear') {
                // Clear injected contexts
                const response = await fetch(`${this.serverUrl}/context/clear`, {
                    method: 'POST',
                    headers: this.getSessionHeaders(true)
                });
                const data = await response.json();

                if (data.removed_count > 0) {
                    this.showSystemMessage(`Cleared ${data.removed_count} injected context(s) from conversation.`);
                } else {
                    this.showSystemMessage('No injected contexts to clear.');
                }
                // Update badge
                await this.updateContextInfo();
            } else if (subCmd === 'reload') {
                // Reload bootstrap context (v1.14.1)
                const response = await fetch(`${this.serverUrl}/context/reload`, {
                    method: 'POST',
                    headers: this.getSessionHeaders(true)
                });
                const data = await response.json();

                if (data.success) {
                    // v1.15.2: Server returns flat structure, not nested under 'status'
                    if (data.loaded) {
                        const sources = data.sources || [];
                        const sourceCount = sources.length;
                        const charCount = data.char_count || 0;
                        if (sourceCount > 1) {
                            this.showSystemMessage(`✓ Bootstrap context reloaded (merged ${sourceCount} files, ${charCount} chars)`);
                        } else if (sourceCount === 1) {
                            this.showSystemMessage(`✓ Bootstrap context reloaded from \`${sources[0].path}\` (${charCount} chars)`);
                        } else {
                            this.showSystemMessage(`✓ Bootstrap context reloaded (${charCount} chars)`);
                        }
                    } else {
                        this.showSystemMessage('Bootstrap context reloaded (no AGENTS.md/CLAUDE.md found in any scope).');
                    }
                } else {
                    this.showError(`Failed to reload context: ${data.error || 'Unknown error'}`);
                }
            } else if (subCmd === 'hints') {
                // Show active bootstrap hints (v1.14.0)
                const response = await fetch(`${this.serverUrl}/context/hints`, {
                    headers: this.getSessionHeaders()
                });
                const hints = await response.json();

                if (!hints.loaded) {
                    // Get working directory for context
                    let workingDir = 'unknown';
                    try {
                        const wdResp = await fetch(`${this.serverUrl}/context/working_dir`, {
                            headers: this.getSessionHeaders()
                        });
                        const wdData = await wdResp.json();
                        workingDir = wdData.path || 'unknown';
                    } catch (e) { /* ignore */ }

                    let msg = '**No bootstrap context loaded.**\n';
                    msg += `Working directory: \`${workingDir}\`\n`;
                    msg += '\n*Create AGENTS.md or CLAUDE.md in your project directory,*\n';
                    msg += '*or use `/wd <path>` to navigate to a directory with one.*';
                    this.addMessage('system', msg);
                    return;
                }

                let msg = '**Active Bootstrap Hints**\n';
                msg += `  Source: \`${hints.source}\`\n`;
                msg += `  Provider: ${hints.provider}\n`;
                msg += `  Model: ${hints.model}\n`;

                // Provider hints
                if (hints.provider_hints && hints.provider_hints.length > 0) {
                    msg += `\n**Provider Hints:** (${hints.provider_hints.length} active)`;
                    if (hints.inherited_local) {
                        msg += ' *(includes inherited "local" hints)*';
                    }
                    msg += '\n';
                    for (const [source, hint] of hints.provider_hints) {
                        const displayHint = hint.length > 80 ? hint.substring(0, 80) + '...' : hint;
                        msg += `  • [${source}] ${displayHint}\n`;
                    }
                } else {
                    msg += '\n**Provider Hints:** *none active*';
                    if (hints.all_provider_keys && hints.all_provider_keys.length > 0) {
                        msg += `\n  Available: ${hints.all_provider_keys.join(', ')}`;
                    }
                    msg += '\n';
                }

                // Model hints
                if (hints.model_hints && hints.model_hints.length > 0) {
                    msg += `\n**Model Hints:** (${hints.model_hints.length} active)`;
                    msg += `\n  Matched patterns: ${hints.matched_patterns.join(', ')}\n`;
                    for (const [pattern, hint] of hints.model_hints) {
                        const displayHint = hint.length > 80 ? hint.substring(0, 80) + '...' : hint;
                        msg += `  • [${pattern}] ${displayHint}\n`;
                    }
                } else {
                    msg += '\n**Model Hints:** *none active*';
                    if (hints.all_model_patterns && hints.all_model_patterns.length > 0) {
                        msg += `\n  Available patterns: ${hints.all_model_patterns.join(', ')}`;
                    }
                    msg += '\n';
                }

                this.addMessage('system', msg);
            } else if (subCmd === 'show') {
                // Show bootstrap context hierarchy (v1.14.2)
                const response = await fetch(`${this.serverUrl}/context/bootstrap`, {
                    headers: this.getSessionHeaders()
                });
                const status = await response.json();

                if (!status.loaded) {
                    let workingDir = 'unknown';
                    try {
                        const wdResp = await fetch(`${this.serverUrl}/context/working_dir`, {
                            headers: this.getSessionHeaders()
                        });
                        const wdData = await wdResp.json();
                        workingDir = wdData.path || 'unknown';
                    } catch (e) { /* ignore */ }

                    let msg = '**No bootstrap context loaded.**\n';
                    msg += `Working directory: \`${workingDir}\`\n\n`;
                    msg += '*Scope search order:*\n';
                    msg += '1. `~/.ppxai/AGENTS.md` (global)\n';
                    msg += '2. `{git_root}/AGENTS.md` (project)\n';
                    msg += '3. `{cwd}/AGENTS.md` (subdir)\n\n';
                    msg += '*Create AGENTS.md or CLAUDE.md in any of these locations.*';
                    this.addMessage('system', msg);
                    return;
                }

                const sources = status.sources || [];
                const totalSize = status.total_size || 0;
                const charCount = status.char_count || 0;
                const estimatedTokens = Math.floor(charCount / 4);

                let msg = '**Bootstrap Context**\n\n';
                msg += `**Sources:** (${sources.length} file${sources.length !== 1 ? 's' : ''})\n`;

                for (let i = 0; i < sources.length; i++) {
                    const src = sources[i];
                    const sizeKb = (src.size / 1024).toFixed(1);
                    const scopeBadge = {
                        'global': '🌐 global',
                        'project': '📁 project',
                        'subdir': '📂 subdir'
                    }[src.scope] || src.scope;
                    msg += `${i + 1}. \`${src.path}\`\n`;
                    msg += `   [${scopeBadge}] ${sizeKb} KB\n`;
                }

                const totalKb = (totalSize / 1024).toFixed(1);
                msg += `\n**Total:** ${totalKb} KB (~${estimatedTokens.toLocaleString()} tokens)\n`;

                // Hints summary
                if (status.has_hints) {
                    msg += '\n**Hints Defined:**\n';
                    if (status.provider_hints && status.provider_hints.length > 0) {
                        msg += `  Provider: ${status.provider_hints.join(', ')}\n`;
                    }
                    if (status.model_hints && status.model_hints.length > 0) {
                        msg += `  Model: ${status.model_hints.join(', ')}\n`;
                    }
                } else {
                    msg += '\n**Hints:** *none defined*\n';
                }

                msg += '\n*Tip: `/context hints` shows active hints for current provider/model*';
                this.addMessage('system', msg);
            } else {
                // Show context usage info
                const response = await fetch(`${this.serverUrl}/context/info`, {
                    headers: this.getSessionHeaders()
                });
                const info = await response.json();

                // Build progress bar
                const percent = info.usage_percent || 0;
                const barLength = 30;
                const filled = Math.min(barLength, Math.round(barLength * Math.min(percent, 100) / 100));
                const bar = '█'.repeat(filled) + '░'.repeat(barLength - filled);

                // Color indicator
                let colorIcon = '🟢';
                if (percent >= 100) { colorIcon = '🔴'; }
                else if (percent >= 80) { colorIcon = '🟡'; }

                let contextMsg = '**Context Usage:**\n';
                contextMsg += `  Estimated: ~${(info.estimated_tokens || 0).toLocaleString()} / ${(info.context_limit || 0).toLocaleString()} tokens (${percent.toFixed(1)}%)\n`;
                contextMsg += `  Model: ${info.model || 'unknown'} (${info.provider || 'unknown'})\n`;
                contextMsg += `  Messages: ${info.message_count || 0}\n`;
                contextMsg += `  ${colorIcon} [${bar}] ${percent.toFixed(0)}%\n`;

                // Show injected files
                const injected = info.injected_contexts || [];
                if (injected.length > 0) {
                    contextMsg += `\n**Injected Contexts:** (${(info.injected_tokens || 0).toLocaleString()} tokens)\n`;
                    injected.forEach(ctx => {
                        const sizeKB = (ctx.size / 1024).toFixed(1);
                        const truncated = ctx.truncated ? ' ⚠ truncated' : '';
                        contextMsg += `  • ${ctx.source} (${sizeKB} KB${truncated})\n`;
                    });
                    contextMsg += '\n*Tip: `/context clear` removes injected files, keeps chat*';
                }

                // Show tips if over limit
                if (percent >= 100) {
                    contextMsg += '\n\n**⚠ Over context limit!** Tips:\n';
                    contextMsg += '  • `/clear` - Start fresh session\n';
                    contextMsg += '  • `/save` - Save session before clearing\n';
                    contextMsg += '  • Consider a model with larger context\n';
                }

                this.addMessage('system', contextMsg);
            }
        } catch (error) {
            this.showError(`Failed to get context info: ${error.message}`);
        }
    }

    async showStatus() {
        try {
            const response = await fetch(`${this.serverUrl}/status`, {
                headers: this.getSessionHeaders()
            });
            const data = await response.json();

            let text = '**Current Status:**\n\n';
            text += `- Provider: ${data.provider}\n`;
            text += `- Model: ${data.model}\n`;
            text += `- Tools: ${data.tools_enabled ? 'enabled' : 'disabled'}\n`;
            text += `- Auto-inject context: ${data.auto_inject_context ? 'yes' : 'no'}\n`;

            this.addMessage('system', text);
        } catch (error) {
            this.showError(`Failed to get status: ${error.message}`);
        }
    }

    handleThemeCommand(args) {
        if (!args) {
            this.showSystemMessage(`Current theme: ${this.theme}`);
        } else if (['dark', 'light', 'system'].includes(args)) {
            this.theme = args;
            this.applyTheme();
            localStorage.setItem('ppxai-theme', this.theme);
            this.showSystemMessage(`Theme set to: ${this.theme}`);
        } else {
            this.showError(`Unknown theme: ${args}. Available: dark, light, system`);
        }
    }

    // === Messages ===

    addMessage(role, content, streaming = false) {
        const msgEl = document.createElement('div');
        msgEl.className = `message ${role}-message`;

        const timestamp = new Date().toLocaleTimeString();

        // v1.13.2: Show thinking indicator for streaming assistant messages
        const thinkingHtml = streaming && role === 'assistant'
            ? '<div class="thinking-indicator"><span class="thinking-dots"></span><span class="thinking-text">Thinking...</span></div>'
            : '';

        // Add copy button for assistant messages
        const copyButton = role === 'assistant'
            ? '<button class="copy-btn" title="Copy to clipboard" onclick="window.ppxai.copyMessageToClipboard(this)">📋</button>'
            : '';

        msgEl.innerHTML = `
            <div class="message-header">
                <span class="message-role">${role === 'user' ? 'You' : role === 'assistant' ? 'Assistant' : 'System'}</span>
                <span class="message-time">${timestamp}</span>
                ${copyButton}
            </div>
            <div class="message-content">${streaming ? thinkingHtml : this.renderMarkdown(content)}</div>
        `;

        this.elements.messagesContainer.appendChild(msgEl);
        this.scrollToBottom();

        return msgEl;
    }

    // v1.15.0: Copy message content to clipboard
    // v1.15.2: Added fallback for non-secure contexts
    copyMessageToClipboard(button) {
        const msgEl = button.closest('.message');
        if (!msgEl) return;

        const contentEl = msgEl.querySelector('.message-content');
        if (!contentEl) return;

        // Get text content (strips HTML but preserves text)
        const text = contentEl.innerText || contentEl.textContent;

        // Try modern Clipboard API first, then fallback
        this.copyTextToClipboard(text).then(success => {
            if (success) {
                // Visual feedback
                const originalText = button.textContent;
                button.textContent = '✓';
                button.classList.add('copied');
                setTimeout(() => {
                    button.textContent = originalText;
                    button.classList.remove('copied');
                }, 1500);
            } else {
                this.showError('Failed to copy to clipboard');
            }
        });
    }

    // v1.15.2: Copy text with fallback for non-secure contexts
    async copyTextToClipboard(text) {
        // Try modern Clipboard API first
        if (navigator.clipboard && navigator.clipboard.writeText) {
            try {
                await navigator.clipboard.writeText(text);
                return true;
            } catch (err) {
                console.warn('Clipboard API failed, trying fallback:', err);
            }
        }

        // Fallback: Create temporary textarea and use execCommand
        try {
            const textarea = document.createElement('textarea');
            textarea.value = text;
            textarea.style.position = 'fixed';
            textarea.style.left = '-9999px';
            textarea.style.top = '-9999px';
            document.body.appendChild(textarea);
            textarea.focus();
            textarea.select();

            const success = document.execCommand('copy');
            document.body.removeChild(textarea);

            if (!success) {
                console.error('execCommand copy failed');
            }
            return success;
        } catch (err) {
            console.error('Fallback copy failed:', err);
            return false;
        }
    }

    // v1.13.2: Update thinking indicator with processing status
    updateThinkingIndicator(status, contentEl) {
        if (!contentEl) return;

        // Check if we have a thinking indicator
        let indicator = contentEl.querySelector('.thinking-indicator');
        if (!indicator) {
            // Create one if content is empty
            if (!contentEl.textContent.trim()) {
                indicator = document.createElement('div');
                indicator.className = 'thinking-indicator';
                indicator.innerHTML = '<span class="thinking-dots"></span><span class="thinking-text"></span>';
                contentEl.appendChild(indicator);
            } else {
                return; // Content already present, don't overlay
            }
        }

        // Update the status text
        const textEl = indicator.querySelector('.thinking-text');
        if (textEl) {
            textEl.textContent = status;
        }
        this.scrollToBottom();
    }

    // v1.13.2: Clear thinking indicator when content arrives
    clearThinkingIndicator(contentEl) {
        if (!contentEl) return;
        const indicator = contentEl.querySelector('.thinking-indicator');
        if (indicator) {
            indicator.remove();
        }
    }

    // v1.13.9: Append reasoning chunk to collapsible section
    appendReasoningChunk(contentEl, chunk) {
        if (!contentEl || !chunk) return;

        // Clear thinking indicator when reasoning starts
        this.clearThinkingIndicator(contentEl);

        // Find or create reasoning section
        let reasoningSection = contentEl.querySelector('.reasoning-section');
        if (!reasoningSection) {
            reasoningSection = document.createElement('details');
            reasoningSection.className = 'reasoning-section';
            reasoningSection.open = true; // Start open while streaming
            reasoningSection.innerHTML = `
                <summary class="reasoning-header">
                    <span class="reasoning-icon">💭</span>
                    <span class="reasoning-title">Thinking...</span>
                </summary>
                <div class="reasoning-content"></div>
            `;
            contentEl.appendChild(reasoningSection);
        }

        // Append chunk to reasoning content
        const reasoningContent = reasoningSection.querySelector('.reasoning-content');
        if (reasoningContent) {
            reasoningContent.textContent += chunk;
        }
        this.scrollToBottom();
    }

    // v1.13.9: Close reasoning section when main content starts
    closeReasoningSection(contentEl) {
        if (!contentEl) return;
        const reasoningSection = contentEl.querySelector('.reasoning-section');
        if (reasoningSection) {
            // Update title to show it's complete
            const title = reasoningSection.querySelector('.reasoning-title');
            if (title) {
                title.textContent = 'Thought process';
            }
            // Collapse the section
            reasoningSection.open = false;
        }
    }

    showSystemMessage(content) {
        this.addMessage('system', content);
    }

    showError(message) {
        const msgEl = document.createElement('div');
        msgEl.className = 'message error-message';
        msgEl.innerHTML = `
            <div class="message-content">${escapeHtml(message)}</div>
        `;
        this.elements.messagesContainer.appendChild(msgEl);
        this.scrollToBottom();
    }

    /**
     * Show a validation warning (v1.15.2 - hallucination detection)
     * @param {Object} data - Warning data with type, severity, message, details, suggested_action
     */
    showValidationWarning(data) {
        const msgEl = document.createElement('div');
        msgEl.className = `message warning-message severity-${data.severity || 'warning'}`;

        // Build warning message
        let warningIcon = '⚠️';
        if (data.severity === 'error') {
            warningIcon = '🚨';
        }

        let content = `<div class="warning-header">
            <span class="warning-icon">${warningIcon}</span>
            <span class="warning-type">${escapeHtml(data.type || 'validation_warning')}</span>
        </div>`;

        content += `<div class="warning-message-text">${escapeHtml(data.message || 'Validation warning')}</div>`;

        if (data.details) {
            content += `<div class="warning-details">${escapeHtml(data.details)}</div>`;
        }

        if (data.suggested_action) {
            content += `<div class="warning-action"><strong>Suggestion:</strong> ${escapeHtml(data.suggested_action)}</div>`;
        }

        msgEl.innerHTML = content;
        this.elements.messagesContainer.appendChild(msgEl);
        this.scrollToBottom();

        // Log to console for debugging
        console.warn('[Validation Warning]', data);
    }

    onToolGroupStart(data) {
        const iteration = data?.iteration || 0;
        const count = data?.count || 0;
        const groupEl = document.createElement('div');
        groupEl.className = 'tool-group collapsed';

        const header = document.createElement('div');
        header.className = 'tool-group-header';
        header.innerHTML = `
            <span class="tool-group-toggle">▶</span>
            <span class="tool-group-label">Iteration ${iteration}: ${count} tool${count !== 1 ? 's' : ''}</span>
            <span class="tool-group-status"></span>
        `;
        header.addEventListener('click', () => {
            groupEl.classList.toggle('collapsed');
        });
        groupEl.appendChild(header);

        const body = document.createElement('div');
        body.className = 'tool-group-body';
        groupEl.appendChild(body);

        // Insert before current assistant message
        if (this.currentAssistantMessage) {
            this.elements.messagesContainer.insertBefore(groupEl, this.currentAssistantMessage);
        } else {
            this.elements.messagesContainer.appendChild(groupEl);
        }
        this._currentToolGroup = groupEl;
        this.scrollToBottom();
    }

    onToolGroupEnd(data) {
        if (!this._currentToolGroup) return;
        const allOk = data?.all_succeeded !== false;
        const tools = data?.tools || [];
        const status = allOk ? '✓' : '✗';
        const statusClass = allOk ? 'success' : 'failure';

        // Update header with tool names and status
        const label = this._currentToolGroup.querySelector('.tool-group-label');
        const statusEl = this._currentToolGroup.querySelector('.tool-group-status');
        if (label && tools.length) {
            label.textContent = `Iteration ${data?.iteration || 0}: ${tools.join(', ')}`;
        }
        if (statusEl) {
            statusEl.textContent = status;
            statusEl.className = `tool-group-status ${statusClass}`;
        }

        this._currentToolGroup = null;
        this.scrollToBottom();
    }

    showToolCall(data) {
        const msgEl = document.createElement('div');
        msgEl.className = 'message tool-message';

        let content = `<div class="tool-header" onclick="this.parentElement.classList.toggle('expanded')">
            <span class="tool-icon">🔧</span>
            <span class="tool-name">${escapeHtml(data.tool || 'Unknown tool')}</span>
            <span class="tool-expand">▶</span>
        </div>`;

        if (this.verbose && data.arguments) {
            content += `<div class="tool-details">
                <pre>${escapeHtml(typeof data.arguments === 'string' ? data.arguments : JSON.stringify(data.arguments, null, 2))}</pre>
            </div>`;
        }

        msgEl.innerHTML = content;

        // v1.16.0: Append inside tool group if active, otherwise insert before assistant message
        if (this._currentToolGroup) {
            this._currentToolGroup.querySelector('.tool-group-body').appendChild(msgEl);
        } else if (this.currentAssistantMessage) {
            this.elements.messagesContainer.insertBefore(msgEl, this.currentAssistantMessage);
        } else {
            this.elements.messagesContainer.appendChild(msgEl);
        }
        this.scrollToBottom();
    }

    showToolResult(data) {
        const msgEl = document.createElement('div');
        msgEl.className = 'message tool-message tool-result';

        let content = `<div class="tool-header" onclick="this.parentElement.classList.toggle('expanded')">
            <span class="tool-icon">📋</span>
            <span class="tool-name">${escapeHtml(data.tool || 'Result')}</span>
            <span class="tool-expand">▶</span>
        </div>`;

        if (this.verbose && data.result) {
            const result = typeof data.result === 'string' ? data.result : JSON.stringify(data.result, null, 2);
            content += `<div class="tool-details">
                <pre>${escapeHtml(result.slice(0, 2000))}${result.length > 2000 ? '\n...(truncated)' : ''}</pre>
            </div>`;
        }

        msgEl.innerHTML = content;

        // v1.16.0: Append inside tool group if active
        if (this._currentToolGroup) {
            this._currentToolGroup.querySelector('.tool-group-body').appendChild(msgEl);
        } else if (this.currentAssistantMessage) {
            this.elements.messagesContainer.insertBefore(msgEl, this.currentAssistantMessage);
        } else {
            this.elements.messagesContainer.appendChild(msgEl);
        }
        this.scrollToBottom();
    }

    showContextInjected(data) {
        const msgEl = document.createElement('div');
        msgEl.className = 'message context-message';
        msgEl.innerHTML = `
            <div class="context-badge">
                <span class="context-icon">📎</span>
                <span class="context-source">${escapeHtml(data.source || 'Context')}</span>
                ${data.language ? `<span class="context-lang">${data.language}</span>` : ''}
                ${data.size ? `<span class="context-size">${data.size} chars</span>` : ''}
                ${data.truncated ? '<span class="context-truncated">(truncated)</span>' : ''}
            </div>
        `;

        // Insert before current assistant message
        if (this.currentAssistantMessage) {
            this.elements.messagesContainer.insertBefore(msgEl, this.currentAssistantMessage);
        } else {
            this.elements.messagesContainer.appendChild(msgEl);
        }
        this.scrollToBottom();
    }

    // === Consent ===

    handleConsentRequest(data) {
        this.elements.consentModal.classList.remove('hidden');

        if (data.type === 'shell') {
            this.elements.consentTitle.textContent = 'Shell Command';
            this.elements.consentMessage.textContent = 'The AI wants to run the following command:';
            this.elements.consentDetails.textContent = data.command || '';

            this.setupConsentButtons((response) => {
                this.sendShellConsent(data.command, data.working_dir || '.', response);
            });
        } else {
            // File edit consent
            this.elements.consentTitle.textContent = 'File Edit';
            this.elements.consentMessage.textContent = `The AI wants to edit: ${data.file_path || 'unknown file'}`;

            let details = '';
            if (data.operation) details += `Operation: ${data.operation}\n`;
            if (data.preview) details += `\n${data.preview}`;
            this.elements.consentDetails.textContent = details;

            this.setupConsentButtons((response) => {
                this.sendFileConsent(data.file_path, response);
            });
        }
    }

    setupConsentButtons(callback) {
        const cleanup = () => {
            this.elements.consentModal.classList.add('hidden');
        };

        this.elements.consentYes.onclick = () => { callback('y'); cleanup(); };
        this.elements.consentNo.onclick = () => { callback('n'); cleanup(); };
        this.elements.consentAlways.onclick = () => { callback('always'); cleanup(); };
        this.elements.consentNever.onclick = () => { callback('never'); cleanup(); };
    }

    async sendFileConsent(filePath, response) {
        try {
            await fetch(`${this.serverUrl}/consent`, {
                method: 'POST',
                headers: this.getSessionHeaders(true),
                body: JSON.stringify({ file_path: filePath, response })
            });
        } catch (error) {
            this.showError(`Failed to send consent: ${error.message}`);
        }
    }

    async sendShellConsent(command, workingDir, response) {
        try {
            await fetch(`${this.serverUrl}/shell-consent`, {
                method: 'POST',
                headers: this.getSessionHeaders(true),
                body: JSON.stringify({ command, working_dir: workingDir, response })
            });
        } catch (error) {
            this.showError(`Failed to send consent: ${error.message}`);
        }
    }

    // === Autocomplete ===

    handleInputKeydown(e) {
        // Handle autocomplete navigation
        if (this.autocompleteVisible) {
            if (e.key === 'ArrowDown') {
                e.preventDefault();
                this.autocompleteIndex = Math.min(this.autocompleteIndex + 1, this.autocompleteItems.length - 1);
                this.renderAutocomplete();
                return;
            } else if (e.key === 'ArrowUp') {
                e.preventDefault();
                this.autocompleteIndex = Math.max(this.autocompleteIndex - 1, 0);
                this.renderAutocomplete();
                return;
            } else if (e.key === 'Tab' || e.key === 'Enter') {
                if (this.autocompleteItems.length > 0) {
                    e.preventDefault();
                    this.selectAutocompleteItem(this.autocompleteIndex);
                    return;
                }
            } else if (e.key === 'Escape') {
                this.hideAutocomplete();
                return;
            }
        }

        // Command history
        if (e.key === 'ArrowUp' && !this.autocompleteVisible) {
            if (this.elements.messageInput.selectionStart === 0) {
                e.preventDefault();
                if (this.historyIndex < this.commandHistory.length - 1) {
                    this.historyIndex++;
                    this.elements.messageInput.value = this.commandHistory[this.historyIndex];
                }
            }
        } else if (e.key === 'ArrowDown' && !this.autocompleteVisible) {
            if (this.elements.messageInput.selectionStart === this.elements.messageInput.value.length) {
                e.preventDefault();
                if (this.historyIndex > 0) {
                    this.historyIndex--;
                    this.elements.messageInput.value = this.commandHistory[this.historyIndex];
                } else if (this.historyIndex === 0) {
                    this.historyIndex = -1;
                    this.elements.messageInput.value = '';
                }
            }
        }

        // Send on Enter (but allow Shift+Enter for newlines)
        if (e.key === 'Enter' && !e.shiftKey && !this.autocompleteVisible) {
            e.preventDefault();
            this.sendMessage();
        }
    }

    handleInputChange() {
        const value = this.elements.messageInput.value;
        const cursorPos = this.elements.messageInput.selectionStart;

        // Check for slash command autocomplete
        if (value.startsWith('/') && !value.includes(' ')) {
            const query = value.toLowerCase();
            this.autocompleteItems = Object.keys(this.slashCommands)
                .filter(cmd => cmd.startsWith(query))
                .map(cmd => ({
                    label: cmd,
                    description: this.slashCommands[cmd].description,
                    value: cmd
                }));
            this.autocompleteType = 'command';
            this.autocompleteIndex = 0;
            this.showAutocomplete();
            return;
        }

        // Check for file reference autocomplete (@)
        const beforeCursor = value.slice(0, cursorPos);
        const atMatch = beforeCursor.match(/@([\w.\-\/]*)$/);
        if (atMatch) {
            const query = atMatch[1];
            this.searchFilesForAutocomplete(query);
            return;
        }

        this.hideAutocomplete();
    }

    async searchFilesForAutocomplete(query) {
        // v1.13.8: Use server endpoint for file search
        this.autocompleteType = 'file';

        try {
            const response = await fetch(`${this.serverUrl}/files/search`, {
                method: 'POST',
                headers: this.getSessionHeaders(true),
                body: JSON.stringify({ query: query || '', max_results: 20 })
            });

            if (response.ok) {
                const data = await response.json();
                this.autocompleteItems = data.files.map(file => ({
                    label: file.name.startsWith('@') ? file.name : `@${file.name}`,
                    description: file.path,
                    value: file.name.startsWith('@') ? file.name : `@${file.name}`
                }));
            } else {
                // Fallback to special refs only
                this.autocompleteItems = [
                    { label: '@git', description: 'Include git diff', value: '@git' },
                    { label: '@tree', description: 'Include project structure', value: '@tree' },
                ];
                if (query) {
                    this.autocompleteItems = this.autocompleteItems.filter(item =>
                        item.label.toLowerCase().includes(query.toLowerCase())
                    );
                }
            }
        } catch (error) {
            // Fallback to special refs on error
            this.autocompleteItems = [
                { label: '@git', description: 'Include git diff', value: '@git' },
                { label: '@tree', description: 'Include project structure', value: '@tree' },
            ];
            if (query) {
                this.autocompleteItems = this.autocompleteItems.filter(item =>
                    item.label.toLowerCase().includes(query.toLowerCase())
                );
            }
        }

        this.autocompleteIndex = 0;
        // v1.13.8: Don't show if input was cleared (message sent during async request)
        if (!this.elements.messageInput.value.includes('@')) {
            return;
        }
        this.showAutocomplete();
    }

    showAutocomplete() {
        if (this.autocompleteItems.length === 0) {
            this.hideAutocomplete();
            return;
        }

        this.autocompleteVisible = true;
        this.renderAutocomplete();
        this.elements.autocompleteDropdown.classList.remove('hidden');
    }

    hideAutocomplete() {
        this.autocompleteVisible = false;
        this.elements.autocompleteDropdown.classList.add('hidden');
    }

    renderAutocomplete() {
        this.elements.autocompleteDropdown.innerHTML = this.autocompleteItems.map((item, i) => `
            <div class="autocomplete-item ${i === this.autocompleteIndex ? 'selected' : ''}"
                 data-index="${i}">
                <span class="autocomplete-label">${escapeHtml(item.label)}</span>
                <span class="autocomplete-desc">${escapeHtml(item.description)}</span>
            </div>
        `).join('');

        // Add click handlers
        this.elements.autocompleteDropdown.querySelectorAll('.autocomplete-item').forEach(el => {
            el.addEventListener('click', () => {
                this.selectAutocompleteItem(parseInt(el.dataset.index));
            });
        });
    }

    selectAutocompleteItem(index) {
        const item = this.autocompleteItems[index];
        if (!item) return;

        const input = this.elements.messageInput;
        const value = input.value;

        if (this.autocompleteType === 'command') {
            input.value = item.value + ' ';
        } else if (this.autocompleteType === 'file') {
            // Replace @query with @filename
            const beforeCursor = value.slice(0, input.selectionStart);
            const afterCursor = value.slice(input.selectionStart);
            const atPos = beforeCursor.lastIndexOf('@');
            input.value = beforeCursor.slice(0, atPos) + item.value + ' ' + afterCursor;
        }

        this.hideAutocomplete();
        input.focus();
    }

    // === Session Management ===

    async clearConversation() {
        try {
            await fetch(`${this.serverUrl}/sessions/clear`, {
                method: 'POST',
                headers: this.getSessionHeaders()
            });
            this.elements.messagesContainer.innerHTML = `
                <div class="welcome-message">
                    <h2>Welcome to ppxai</h2>
                    <p>AI-powered chat with multiple providers</p>
                    <div class="quick-commands">
                        <button class="quick-cmd" data-cmd="/help">📖 Help</button>
                        <button class="quick-cmd" data-cmd="/tools enable">🛠 Enable Tools</button>
                        <button class="quick-cmd" data-cmd="/provider list">🔄 Providers</button>
                        <button class="quick-cmd" data-cmd="/model list">📋 Models</button>
                    </div>
                </div>
            `;
            // Quick command handlers use event delegation, no need to re-attach
            this.showSystemMessage('Conversation cleared');
        } catch (error) {
            this.showError(`Failed to clear: ${error.message}`);
        }
    }

    async saveSession(name) {
        try {
            const response = await fetch(`${this.serverUrl}/sessions/save`, {
                method: 'POST',
                headers: this.getSessionHeaders(true),
                body: name ? JSON.stringify({ name }) : '{}'
            });
            const data = await response.json();
            this.showSystemMessage(`Session saved: ${data.name}`);
        } catch (error) {
            this.showError(`Failed to save session: ${error.message}`);
        }
    }

    async exportAnswer(filename) {
        try {
            const response = await fetch(`${this.serverUrl}/export`, {
                method: 'POST',
                headers: this.getSessionHeaders(true),
                body: filename ? JSON.stringify({ filename }) : '{}'
            });
            const data = await response.json();
            this.showSystemMessage(`Exported to: ${data.filepath}`);
        } catch (error) {
            this.showError(`Failed to export: ${error.message}`);
        }
    }

    async loadSession(name) {
        if (!name) {
            this.showError('Usage: /load <session_name>');
            await this.listSessions();
            return;
        }

        try {
            const sessionName = encodeURIComponent(name.trim());
            const response = await fetch(`${this.serverUrl}/sessions/load/${sessionName}`, {
                method: 'POST',
                headers: this.getSessionHeaders(true)
            });

            if (response.ok) {
                const data = await response.json();
                this.showSystemMessage(`Session loaded: ${data.name}`);
                // Refresh model/provider status after loading
                await this.loadInitialState();
            } else {
                const error = await response.json();
                this.showError(`Failed to load session: ${error.detail || 'Session not found'}`);
            }
        } catch (error) {
            this.showError(`Failed to load session: ${error.message}`);
        }
    }

    async listSessions() {
        try {
            const response = await fetch(`${this.serverUrl}/sessions`, {
                headers: this.getSessionHeaders()
            });
            const data = await response.json();

            if (!data.sessions || data.sessions.length === 0) {
                this.showSystemMessage('No saved sessions found.');
                return;
            }

            let text = '**Saved Sessions:**\n\n';
            text += '| Session | Messages | Provider/Model | Created | Last Saved |\n';
            text += '|:--------|:--------:|:---------------|:--------|:-----------|\n';
            data.sessions.forEach(s => {
                const created = s.created_at ? s.created_at.slice(0, 16).replace('T', ' ') : 'unknown';
                const saved = s.saved_at ? s.saved_at.slice(0, 16).replace('T', ' ') : '-';
                text += `| \`${s.name}\` | ${s.message_count} | ${s.provider}/${s.model} | ${created} | ${saved} |\n`;
            });
            text += '\n*Use `/load <session_name>` to load a session*';

            this.addMessage('system', text);
        } catch (error) {
            this.showError(`Failed to list sessions: ${error.message}`);
        }
    }

    async handleCdCommand(args) {
        if (!args || !args.trim()) {
            // No args - show current working directory (same as /pwd)
            await this.handlePwdCommand();
            return;
        }

        const targetPath = args.trim();

        try {
            const response = await fetch(`${this.serverUrl}/context/working_dir`, {
                method: 'POST',
                headers: this.getSessionHeaders(true),
                body: JSON.stringify({ path: targetPath })
            });

            if (response.ok) {
                const data = await response.json();
                this.showSystemMessage(`Working directory changed to: \`${data.path}\``);
                // Update the folder badge
                this.updateFolderBadge(data.path);
            } else {
                const error = await response.json();
                this.showError(`Failed to change directory: ${error.detail || 'Unknown error'}`);
            }
        } catch (error) {
            this.showError(`Failed to change directory: ${error.message}`);
        }
    }

    async handlePwdCommand() {
        try {
            const response = await fetch(`${this.serverUrl}/context/working_dir`, {
                headers: this.getSessionHeaders()
            });

            if (response.ok) {
                const data = await response.json();
                this.showSystemMessage(`Current working directory: \`${data.path}\``);
            } else {
                this.showError('Failed to get working directory');
            }
        } catch (error) {
            this.showError(`Failed to get working directory: ${error.message}`);
        }
    }

    /**
     * Handle /ls command - list directory contents (v1.16.0)
     */
    async handleLsCommand(args) {
        try {
            const params = new URLSearchParams();
            if (args) {
                const parts = args.trim().split(/\s+/);
                const showHidden = parts.includes('-a');
                const pathParts = parts.filter(p => p !== '-a');
                if (pathParts.length > 0) params.set('path', pathParts.join(' '));
                if (showHidden) params.set('a', 'true');
            }
            const response = await fetch(`${this.serverUrl}/files/list?${params}`, {
                headers: this.getSessionHeaders()
            });

            if (response.ok) {
                const data = await response.json();
                // Format as monospace table
                const pad = (s, n) => s.padEnd(n);
                const header = `${pad('Name', 40)} ${pad('Size', 10)} Modified`;
                const sep = '-'.repeat(60);
                const rows = data.files.map(f => {
                    const size = f.size != null ? this._humanSize(f.size) : '-';
                    const mod = f.modified ? f.modified.replace('T', ' ').slice(0, 16) : '?';
                    return `${pad(f.name, 40)} ${pad(size, 10)} ${mod}`;
                });
                const content = '```\n' + [data.path, '', header, sep, ...rows].join('\n') + '\n```';
                this.showSystemMessage(content);
            } else {
                const err = await response.json();
                this.showError(err.detail || 'Failed to list directory');
            }
        } catch (error) {
            this.showError(`Failed to list directory: ${error.message}`);
        }
    }

    _humanSize(bytes) {
        for (const unit of ['B', 'KB', 'MB', 'GB']) {
            if (Math.abs(bytes) < 1024) return unit === 'B' ? `${bytes} B` : `${bytes.toFixed(1)} ${unit}`;
            bytes /= 1024;
        }
        return `${bytes.toFixed(1)} TB`;
    }

    /**
     * Handle /tree command - show directory tree (v1.16.0)
     */
    async handleTreeCommand(args) {
        try {
            const params = new URLSearchParams();
            if (args) {
                const parts = args.trim().split(/\s+/);
                for (const part of parts) {
                    if (/^\d+$/.test(part)) params.set('depth', part);
                    else params.set('path', part);
                }
            }
            const response = await fetch(`${this.serverUrl}/files/tree?${params}`, {
                headers: this.getSessionHeaders()
            });

            if (response.ok) {
                const data = await response.json();
                const lines = [];
                const renderNode = (node, prefix, isLast) => {
                    const connector = isLast ? '└── ' : '├── ';
                    lines.push(prefix + connector + node.label);
                    const children = node.children || [];
                    for (let i = 0; i < children.length; i++) {
                        const childPrefix = prefix + (isLast ? '    ' : '│   ');
                        renderNode(children[i], childPrefix, i === children.length - 1);
                    }
                };
                // Root
                lines.push(data.tree.label);
                const rootChildren = data.tree.children || [];
                for (let i = 0; i < rootChildren.length; i++) {
                    renderNode(rootChildren[i], '', i === rootChildren.length - 1);
                }
                const stats = `${data.stats.dirs} directories, ${data.stats.files} files`;
                const content = '```\n' + lines.join('\n') + '\n\n' + stats + '\n```';
                this.showSystemMessage(content);
            } else {
                const err = await response.json();
                this.showError(err.detail || 'Failed to get directory tree');
            }
        } catch (error) {
            this.showError(`Failed to get directory tree: ${error.message}`);
        }
    }

    /**
     * Handle /config command - configuration management (v1.15.2)
     * Subcommands: reload, path, or no args for help
     */
    async handleConfigCommand(args) {
        const subCmd = args ? args.trim().toLowerCase() : '';

        if (subCmd === 'reload') {
            await this.reloadConfig();
        } else if (subCmd === 'path') {
            try {
                const response = await fetch(`${this.serverUrl}/config/path`, {
                    headers: this.getSessionHeaders()
                });
                if (response.ok) {
                    const data = await response.json();
                    this.showSystemMessage(`**Config file:** \`${data.path || 'Not found'}\``);
                } else {
                    this.showError('Failed to get config path');
                }
            } catch (error) {
                this.showError(`Failed to get config path: ${error.message}`);
            }
        } else {
            // Show help
            let msg = '**Config Commands:**\n\n';
            msg += '- `/config reload` - Reload config from file\n';
            msg += '- `/config path` - Show config file path\n';
            this.addMessage('system', msg);
        }
    }

    /**
     * Handle /edit command - open file in CodeMirror 6 editor (v1.14.1)
     * Syntax: /edit filepath[:line[:col]]
     */
    async handleEditCommand(args) {
        if (!args || !args.trim()) {
            this.showError('Usage: /edit <filepath[:line[:col]]>');
            return;
        }

        // Parse filepath and optional line:col
        const input = args.trim();
        let filepath = input;
        let line = 1;
        let col = 1;

        // Pattern: filepath:line or filepath:line:col
        const match = input.match(/^(.+?):(\d+)(?::(\d+))?$/);
        if (match) {
            filepath = match[1];
            line = parseInt(match[2], 10);
            col = match[3] ? parseInt(match[3], 10) : 1;
        }

        try {
            const response = await fetch(`${this.serverUrl}/files/read`, {
                method: 'POST',
                headers: this.getSessionHeaders(true),
                body: JSON.stringify({ path: filepath })
            });

            if (response.ok) {
                const data = await response.json();

                // Don't allow editing binary files
                if (data.type === 'image' || data.type === 'pdf') {
                    this.showError(`Cannot edit binary file: ${filepath}`);
                    return;
                }

                // Show editor panel
                this.showEditorPanel(data.filename || filepath, data.content, line, col);
            } else {
                // File doesn't exist - create new file
                const error = await response.json();
                if (response.status === 404) {
                    // Create new empty file
                    this.showEditorPanel(filepath, '', line, col, true);
                } else {
                    this.showError(`Failed to read file: ${error.detail || 'Unknown error'}`);
                }
            }
        } catch (error) {
            this.showError(`Failed to open file: ${error.message}`);
        }
    }

    /**
     * Show the CodeMirror 6 editor panel (v1.14.1)
     */
    showEditorPanel(filename, content, line = 1, col = 1, isNewFile = false) {
        // Store state
        this.editorFilename = filename;
        this.editorContent = content;
        this.editorOriginalContent = content;
        this.editorIsNewFile = isNewFile;

        // Update header
        this.elements.previewFilename.textContent = filename + (isNewFile ? ' (new)' : '');
        this.elements.previewInfo.textContent = isNewFile ? 'New file' : `${content.split('\n').length} lines`;

        // Hide view toggle (not for editor mode)
        if (this.elements.previewViewToggle) {
            this.elements.previewViewToggle.classList.add('hidden');
        }

        // Hide other preview containers
        this.elements.previewCode.parentElement.classList.add('hidden');
        if (this.elements.previewMarkdown) {
            this.elements.previewMarkdown.classList.add('hidden');
        }
        if (this.elements.previewDataViewer) {
            this.elements.previewDataViewer.classList.add('hidden');
        }

        // Get or create editor container
        const previewContentEl = this.elements.previewCode.parentElement.parentElement;
        let editorContainer = previewContentEl.querySelector('.editor-container');
        if (!editorContainer) {
            editorContainer = document.createElement('div');
            editorContainer.className = 'editor-container';
            editorContainer.style.cssText = 'height: 100%; display: flex; flex-direction: column;';
            previewContentEl.appendChild(editorContainer);
        }
        editorContainer.classList.remove('hidden');
        editorContainer.innerHTML = '';

        // Detect file extension for syntax selector
        const ext = filename.split('.').pop().toLowerCase();
        const langMap = {
            'py': 'python', 'python': 'python',
            'js': 'javascript', 'mjs': 'javascript', 'cjs': 'javascript', 'ts': 'javascript', 'tsx': 'javascript',
            'json': 'json',
            'yaml': 'yaml', 'yml': 'yaml',
            'md': 'markdown', 'markdown': 'markdown'
        };
        const detectedLang = langMap[ext] || 'markdown';
        this.editorLanguage = detectedLang;

        // Create editor toolbar
        const toolbar = document.createElement('div');
        toolbar.className = 'editor-toolbar';
        toolbar.innerHTML = `
            <button class="editor-btn editor-save" title="Save (Ctrl+S)">💾 Save</button>
            <button class="editor-btn editor-save-as" title="Save As...">📄 Save As</button>
            <button class="editor-btn editor-open" title="Open file...">📂 Open</button>
            <select class="editor-syntax-select" title="Syntax highlighting">
                <option value="markdown" ${detectedLang === 'markdown' ? 'selected' : ''}>Markdown</option>
                <option value="yaml" ${detectedLang === 'yaml' ? 'selected' : ''}>YAML</option>
                <option value="json" ${detectedLang === 'json' ? 'selected' : ''}>JSON</option>
                <option value="python" ${detectedLang === 'python' ? 'selected' : ''}>Python</option>
                <option value="javascript" ${detectedLang === 'javascript' ? 'selected' : ''}>JavaScript</option>
            </select>
            <button class="editor-btn editor-discard" title="Close editor">✗ Close</button>
            <span class="editor-status"></span>
        `;
        editorContainer.appendChild(toolbar);

        // Create editor element
        const editorEl = document.createElement('div');
        editorEl.className = 'codemirror-editor';
        editorEl.style.cssText = 'flex: 1; overflow: auto;';
        editorContainer.appendChild(editorEl);

        // Initialize CodeMirror 6
        this.initCodeMirror(editorEl, content, filename, line, col);

        // Wire up toolbar buttons
        toolbar.querySelector('.editor-save').addEventListener('click', () => this.saveEditorContent());
        toolbar.querySelector('.editor-save-as').addEventListener('click', () => this.saveEditorAs());
        toolbar.querySelector('.editor-open').addEventListener('click', () => this.openFileDialog());
        toolbar.querySelector('.editor-syntax-select').addEventListener('change', (e) => this.changeSyntax(e.target.value));
        toolbar.querySelector('.editor-discard').addEventListener('click', () => this.discardEditorChanges());

        // Show the panel
        this.elements.resizeHandle.classList.remove('hidden');
        this.elements.previewPanel.classList.remove('hidden');
    }

    /**
     * Initialize CodeMirror 6 editor (v1.14.1)
     */
    initCodeMirror(element, content, filename, line, col) {
        // Destroy previous editor if exists
        if (this.currentEditor) {
            this.currentEditor.destroy();
            this.currentEditor = null;
        }

        // Check if CodeMirror prebuilt is loaded
        if (typeof cm6 === 'undefined') {
            // Load appropriate language bundle based on file extension
            const ext = filename.split('.').pop().toLowerCase();
            const langMap = {
                'py': 'python', 'python': 'python',
                'js': 'javascript', 'mjs': 'javascript', 'cjs': 'javascript',
                'json': 'json',
                'yaml': 'yaml', 'yml': 'yaml',
                'md': 'markdown', 'markdown': 'markdown'
            };
            const lang = langMap[ext] || 'markdown';  // Default to markdown

            // Try to load the appropriate bundle
            const script = document.createElement('script');
            script.src = `lib/codemirror/${lang}.min.js`;
            script.onload = () => {
                this.createCodeMirrorEditor(element, content, line, col);
            };
            script.onerror = () => {
                // Fallback to plain textarea
                this.createFallbackEditor(element, content, line, col);
            };
            document.head.appendChild(script);
        } else {
            this.createCodeMirrorEditor(element, content, line, col);
        }
    }

    /**
     * Create CodeMirror 6 editor instance
     */
    createCodeMirrorEditor(element, content, line, col) {
        try {
            const isDark = this.theme === 'dark';

            // cm6.load() returns an object with newEditor, newState, newView, textarea, fromElement
            const api = cm6.load();

            // Use newEditor which creates both state and view with language support
            const view = api.newEditor(element, content, {
                dark: isDark,
                lineWrapping: true
            });

            this.currentEditor = view;

            // Go to line:col
            if (line > 1 || col > 1) {
                try {
                    const lineCount = view.state.doc.lines;
                    const targetLine = Math.min(line, lineCount);
                    const lineInfo = view.state.doc.line(targetLine);
                    const pos = lineInfo.from + Math.min(col - 1, lineInfo.length);
                    view.dispatch({
                        selection: { anchor: pos },
                        scrollIntoView: true
                    });
                } catch (e) {
                    console.warn('Could not navigate to line:', e);
                }
            }

            // Focus editor
            view.focus();

            // Add Ctrl+S handler
            element.addEventListener('keydown', (e) => {
                if ((e.ctrlKey || e.metaKey) && e.key === 's') {
                    e.preventDefault();
                    this.saveEditorContent();
                }
            });

        } catch (error) {
            console.error('CodeMirror init error:', error);
            this.createFallbackEditor(element, content, line, col);
        }
    }

    /**
     * Create fallback textarea editor if CodeMirror fails
     */
    createFallbackEditor(element, content, line, col) {
        const textarea = document.createElement('textarea');
        textarea.className = 'fallback-editor';
        textarea.style.cssText = 'width: 100%; height: 100%; resize: none; font-family: monospace; font-size: 13px; padding: 8px; border: none; background: var(--bg-secondary); color: var(--text-primary);';
        textarea.value = content;
        element.appendChild(textarea);

        this.currentEditor = {
            state: { doc: { toString: () => textarea.value } },
            destroy: () => {}
        };

        // Go to line (approximate for textarea)
        const lines = content.split('\n');
        let pos = 0;
        for (let i = 0; i < Math.min(line - 1, lines.length); i++) {
            pos += lines[i].length + 1;
        }
        pos += Math.min(col - 1, lines[line - 1]?.length || 0);
        textarea.setSelectionRange(pos, pos);
        textarea.focus();

        // Add Ctrl+S handler
        textarea.addEventListener('keydown', (e) => {
            if ((e.ctrlKey || e.metaKey) && e.key === 's') {
                e.preventDefault();
                this.saveEditorContent();
            }
        });
    }

    /**
     * Save editor content to file (v1.14.1)
     */
    async saveEditorContent() {
        if (!this.currentEditor || !this.editorFilename) {
            return;
        }

        const content = this.currentEditor.state.doc.toString();
        const statusEl = document.querySelector('.editor-status');

        try {
            if (statusEl) statusEl.textContent = 'Saving...';

            const response = await fetch(`${this.serverUrl}/files/write`, {
                method: 'POST',
                headers: this.getSessionHeaders(true),
                body: JSON.stringify({
                    path: this.editorFilename,
                    content: content
                })
            });

            if (response.ok) {
                const data = await response.json();
                this.editorOriginalContent = content;
                this.editorIsNewFile = false;

                // Update header
                this.elements.previewFilename.textContent = this.editorFilename;

                if (statusEl) {
                    statusEl.textContent = data.created ? '✓ Created' : '✓ Saved';
                    setTimeout(() => { statusEl.textContent = ''; }, 2000);
                }

                this.showSystemMessage(`✓ Saved: ${this.editorFilename}`);
            } else {
                const error = await response.json();
                if (statusEl) statusEl.textContent = '✗ Error';
                this.showError(`Failed to save: ${error.detail || 'Unknown error'}`);
            }
        } catch (error) {
            if (statusEl) statusEl.textContent = '✗ Error';
            this.showError(`Failed to save: ${error.message}`);
        }
    }

    /**
     * Save As - save editor content to a different file (v1.14.1)
     */
    async saveEditorAs() {
        const newPath = prompt('Save as (enter file path):', this.editorFilename);
        if (!newPath || !newPath.trim()) {
            return;
        }

        const content = this.currentEditor?.state?.doc?.toString() || '';
        const statusEl = document.querySelector('.editor-status');

        try {
            if (statusEl) statusEl.textContent = 'Saving...';

            const response = await fetch(`${this.serverUrl}/files/write`, {
                method: 'POST',
                headers: this.getSessionHeaders(true),
                body: JSON.stringify({
                    path: newPath.trim(),
                    content: content
                })
            });

            if (response.ok) {
                const data = await response.json();

                // Update current file to new path
                this.editorFilename = newPath.trim();
                this.editorOriginalContent = content;
                this.editorIsNewFile = false;

                // Update header
                this.elements.previewFilename.textContent = this.editorFilename;

                if (statusEl) {
                    statusEl.textContent = data.created ? '✓ Created' : '✓ Saved';
                    setTimeout(() => { statusEl.textContent = ''; }, 2000);
                }

                this.showSystemMessage(`✓ Saved as: ${this.editorFilename}`);
            } else {
                const error = await response.json();
                if (statusEl) statusEl.textContent = '✗ Error';
                this.showError(`Failed to save: ${error.detail || 'Unknown error'}`);
            }
        } catch (error) {
            if (statusEl) statusEl.textContent = '✗ Error';
            this.showError(`Failed to save: ${error.message}`);
        }
    }

    /**
     * Open a different file in the editor (v1.14.1)
     */
    async openFileDialog() {
        const content = this.currentEditor?.state?.doc?.toString() || '';
        const hasChanges = content !== this.editorOriginalContent;

        if (hasChanges) {
            if (!confirm('You have unsaved changes. Open a different file?')) {
                return;
            }
        }

        const filepath = prompt('Open file (enter path):');
        if (!filepath || !filepath.trim()) {
            return;
        }

        // Use handleEditCommand to open the new file
        await this.handleEditCommand(filepath.trim());
    }

    /**
     * Change syntax highlighting language (v1.14.1)
     */
    async changeSyntax(language) {
        if (this.editorLanguage === language) {
            return;
        }

        // Get current content and cursor position
        const content = this.currentEditor?.state?.doc?.toString() || '';
        let cursorPos = 0;
        try {
            cursorPos = this.currentEditor?.state?.selection?.main?.head || 0;
        } catch (e) {}

        // Destroy current editor
        if (this.currentEditor) {
            this.currentEditor.destroy();
            this.currentEditor = null;
        }

        // Update language
        this.editorLanguage = language;

        // Get editor container
        const previewContentEl = this.elements.previewCode.parentElement.parentElement;
        const editorContainer = previewContentEl.querySelector('.editor-container');
        const editorEl = editorContainer?.querySelector('.codemirror-editor');

        if (!editorEl) {
            return;
        }

        // Clear and reinitialize with new language
        editorEl.innerHTML = '';

        // Load the new language bundle
        const script = document.createElement('script');
        script.src = `lib/codemirror/${language}.min.js`;
        script.onload = () => {
            this.createCodeMirrorEditor(editorEl, content, 1, 1);
            // Restore cursor position
            try {
                if (this.currentEditor && cursorPos > 0) {
                    this.currentEditor.dispatch({
                        selection: { anchor: Math.min(cursorPos, content.length) }
                    });
                }
            } catch (e) {}
        };
        script.onerror = () => {
            this.showError(`Failed to load syntax: ${language}`);
            this.createFallbackEditor(editorEl, content, 1, 1);
        };
        document.head.appendChild(script);
    }

    /**
     * Discard editor changes and close
     */
    discardEditorChanges() {
        const content = this.currentEditor?.state?.doc?.toString() || '';
        const hasChanges = content !== this.editorOriginalContent;

        if (hasChanges) {
            if (!confirm('Discard unsaved changes?')) {
                return;
            }
        }

        this.closeEditorPanel();
    }

    /**
     * Close editor panel
     */
    closeEditorPanel() {
        // Clean up editor
        if (this.currentEditor) {
            this.currentEditor.destroy();
            this.currentEditor = null;
        }

        // Hide editor container
        const previewContentEl = this.elements.previewCode.parentElement.parentElement;
        const editorContainer = previewContentEl.querySelector('.editor-container');
        if (editorContainer) {
            editorContainer.classList.add('hidden');
        }

        // Reset state
        this.editorFilename = null;
        this.editorContent = null;
        this.editorOriginalContent = null;
        this.editorIsNewFile = false;

        // Hide preview panel
        this.elements.previewPanel.classList.add('hidden');
        this.elements.resizeHandle.classList.add('hidden');
    }

    // === /preview Command (v1.15.4) ===

    async handlePreviewCommand(args) {
        if (!args || !args.trim()) {
            this.showError('Usage: /preview <file.html>');
            return;
        }

        const filepath = args.trim();

        if (filepath.toLowerCase() === 'close') {
            this.closeHtmlPreview();
            return;
        }

        this.openHtmlPreview(filepath);
    }

    openHtmlPreview(filepath) {
        const panel = this.elements.previewPanel;
        const contentEl = document.getElementById('previewContent');
        if (!panel || !contentEl) {
            this.showError('Preview panel not available');
            return;
        }

        // Set filename header
        this.elements.previewFilename.textContent = filepath;
        this.elements.previewInfo.textContent = 'Live Preview';

        // Hide view toggle (not applicable for iframe preview)
        if (this.elements.previewViewToggle) {
            this.elements.previewViewToggle.classList.add('hidden');
        }

        // Hide code/markdown/data viewers
        if (this.elements.previewCode && this.elements.previewCode.parentElement) {
            this.elements.previewCode.parentElement.classList.add('hidden');
        }
        if (this.elements.previewMarkdown) {
            this.elements.previewMarkdown.classList.add('hidden');
        }
        const dataViewer = document.getElementById('previewDataViewer');
        if (dataViewer) dataViewer.classList.add('hidden');

        // Hide image and PDF containers
        const imageContainer = panel.querySelector('.preview-image-container');
        if (imageContainer) imageContainer.classList.add('hidden');
        const pdfContainer = panel.querySelector('.preview-pdf-container');
        if (pdfContainer) pdfContainer.classList.add('hidden');

        // Remove existing preview iframe if any
        let iframe = contentEl.querySelector('.preview-iframe');
        if (iframe) iframe.remove();

        // Create iframe pointing to server preview endpoint
        iframe = document.createElement('iframe');
        iframe.className = 'preview-iframe';
        iframe.src = `${this.serverUrl}/preview/${encodeURIComponent(filepath)}?session=${encodeURIComponent(this.sessionId)}`;
        iframe.sandbox = 'allow-scripts allow-same-origin';
        iframe.style.cssText = 'width:100%;height:100%;border:none;background:#fff;';
        contentEl.appendChild(iframe);

        // Show panel
        panel.classList.remove('hidden');
        this.elements.resizeHandle.classList.remove('hidden');

        // Track state
        this._htmlPreviewActive = true;
        this._htmlPreviewFilepath = filepath;
    }

    closeHtmlPreview() {
        if (!this._htmlPreviewActive) {
            this.showSystemMessage('No active preview');
            return;
        }

        const contentEl = document.getElementById('previewContent');
        if (contentEl) {
            const iframe = contentEl.querySelector('.preview-iframe');
            if (iframe) iframe.remove();
        }

        // Restore code viewer visibility
        if (this.elements.previewCode && this.elements.previewCode.parentElement) {
            this.elements.previewCode.parentElement.classList.remove('hidden');
        }

        this.hidePreviewPanel();
        this._htmlPreviewActive = false;
        this._htmlPreviewFilepath = null;
    }

    async handleShowCommand(args) {
        if (!args || !args.trim()) {
            this.showError('Usage: /show <filepath> or /show @<search-query>');
            return;
        }

        const filepath = args.trim();

        try {
            const response = await fetch(`${this.serverUrl}/files/read`, {
                method: 'POST',
                headers: this.getSessionHeaders(true),
                body: JSON.stringify({ path: filepath })
            });

            if (response.ok) {
                const data = await response.json();

                // v1.13.10: Handle image and PDF files
                if (data.type === 'image') {
                    this.showImagePreview(data.filename || filepath, data.content, data.mime_type, data.size);
                } else if (data.type === 'pdf') {
                    this.showPdfPreview(data.filename || filepath, data.content, data.size);
                } else {
                    // Show text in preview panel
                    this.showPreviewPanel(data.filename || filepath, data.content, data.size, data.lines);
                }
            } else {
                const error = await response.json();
                this.showError(`Failed to read file: ${error.detail || 'File not found'}`);
            }
        } catch (error) {
            this.showError(`Failed to read file: ${error.message}`);
        }
    }

    /**
     * Display file from display_file event (v1.15.2)
     * Called when AI uses the display_file tool
     */
    async displayFileFromEvent(filepath) {
        try {
            const response = await fetch(`${this.serverUrl}/files/read`, {
                method: 'POST',
                headers: this.getSessionHeaders(true),
                body: JSON.stringify({ path: filepath })
            });

            if (response.ok) {
                const data = await response.json();

                // Handle different file types
                if (data.type === 'image') {
                    this.showImagePreview(data.filename || filepath, data.content, data.mime_type, data.size);
                } else if (data.type === 'pdf') {
                    this.showPdfPreview(data.filename || filepath, data.content, data.size);
                } else {
                    // Show text in preview panel
                    this.showPreviewPanel(data.filename || filepath, data.content, data.size, data.lines);
                }
            } else {
                // Don't show error to user - the AI tool already reports status
                console.error(`Failed to display file: ${filepath}`);
            }
        } catch (error) {
            console.error(`Failed to display file: ${error.message}`);
        }
    }

    showPreviewPanel(filename, content, size, lines) {
        // Store content for view toggle (v1.13.8)
        this.previewContent = content;
        this.previewFilename = filename;

        // Update filename
        this.elements.previewFilename.textContent = filename;

        // Update info
        let info = '';
        if (lines) info += `${lines} lines`;
        if (size) info += info ? ` • ${(size / 1024).toFixed(1)} KB` : `${(size / 1024).toFixed(1)} KB`;
        this.elements.previewInfo.textContent = info;

        // Determine file extension
        const ext = filename.split('.').pop().toLowerCase() || '';

        // Detect data format (v1.13.8)
        const dataFormats = {
            'csv': 'table', 'tsv': 'table', 'tab': 'table',
            'json': 'tree', 'yaml': 'tree', 'yml': 'tree',
            'toml': 'tree', 'hcl': 'tree', 'tf': 'tree', 'tfvars': 'tree'
        };
        this.previewDataFormat = dataFormats[ext] || null;

        // Show/hide view toggle based on whether this is a data file
        if (this.elements.previewViewToggle) {
            if (this.previewDataFormat) {
                this.elements.previewViewToggle.classList.remove('hidden');
                this.updateViewToggleUI();
            } else {
                this.elements.previewViewToggle.classList.add('hidden');
            }
        }

        // v1.13.10: Hide image and PDF containers when showing text
        const imageContainer = this.elements.previewPanel.querySelector('.preview-image-container');
        if (imageContainer) {
            imageContainer.classList.add('hidden');
        }
        const pdfContainer = this.elements.previewPanel.querySelector('.preview-pdf-container');
        if (pdfContainer) {
            pdfContainer.classList.add('hidden');
        }

        // Render based on view mode
        this.renderPreviewContent();

        // Show the panel and resize handle
        this.elements.resizeHandle.classList.remove('hidden');
        this.elements.previewPanel.classList.remove('hidden');
    }

    /**
     * Show image preview (v1.13.10)
     */
    showImagePreview(filename, base64Content, mimeType, size) {
        // Update filename
        this.elements.previewFilename.textContent = filename;

        // Update info
        const sizeKB = (size / 1024).toFixed(1);
        const sizeMB = (size / 1024 / 1024).toFixed(2);
        const sizeStr = size > 1024 * 1024 ? `${sizeMB} MB` : `${sizeKB} KB`;
        this.elements.previewInfo.textContent = `Image • ${sizeStr}`;

        // Hide view toggle (not applicable for images)
        if (this.elements.previewViewToggle) {
            this.elements.previewViewToggle.classList.add('hidden');
        }

        // Hide all other preview containers
        this.elements.previewCode.parentElement.classList.add('hidden');
        if (this.elements.previewMarkdown) {
            this.elements.previewMarkdown.classList.add('hidden');
        }
        if (this.elements.previewDataViewer) {
            this.elements.previewDataViewer.classList.add('hidden');
        }
        const pdfContainer = this.elements.previewPanel.querySelector('.preview-pdf-container');
        if (pdfContainer) {
            pdfContainer.classList.add('hidden');
        }

        // Create or reuse image container (append to preview-content div)
        const previewContentEl = this.elements.previewCode.parentElement.parentElement;
        let imageContainer = previewContentEl.querySelector('.preview-image-container');
        if (!imageContainer) {
            imageContainer = document.createElement('div');
            imageContainer.className = 'preview-image-container';
            imageContainer.style.cssText = 'padding: 1rem; text-align: center; overflow: auto; height: 100%;';
            previewContentEl.appendChild(imageContainer);
        }
        imageContainer.classList.remove('hidden');

        // Create image element
        const dataUrl = `data:${mimeType};base64,${base64Content}`;
        imageContainer.innerHTML = `<img src="${dataUrl}" alt="${filename}" style="max-width: 100%; max-height: calc(100vh - 200px); object-fit: contain; border-radius: 4px; box-shadow: 0 2px 8px rgba(0,0,0,0.3);">`;

        // Show the panel and resize handle
        this.elements.resizeHandle.classList.remove('hidden');
        this.elements.previewPanel.classList.remove('hidden');

        // Clear text preview state
        this.previewContent = null;
        this.previewFilename = filename;
        this.previewDataFormat = null;
    }

    /**
     * Show PDF preview (v1.13.10)
     */
    showPdfPreview(filename, base64Content, size) {
        // Update filename
        this.elements.previewFilename.textContent = filename;

        // Update info
        const sizeMB = (size / 1024 / 1024).toFixed(2);
        const sizeKB = (size / 1024).toFixed(1);
        const sizeStr = size > 1024 * 1024 ? `${sizeMB} MB` : `${sizeKB} KB`;
        this.elements.previewInfo.textContent = `PDF • ${sizeStr}`;

        // Hide view toggle (not applicable for PDFs)
        if (this.elements.previewViewToggle) {
            this.elements.previewViewToggle.classList.add('hidden');
        }

        // Hide all other preview containers
        this.elements.previewCode.parentElement.classList.add('hidden');
        if (this.elements.previewMarkdown) {
            this.elements.previewMarkdown.classList.add('hidden');
        }
        if (this.elements.previewDataViewer) {
            this.elements.previewDataViewer.classList.add('hidden');
        }
        const imageContainer = this.elements.previewPanel.querySelector('.preview-image-container');
        if (imageContainer) {
            imageContainer.classList.add('hidden');
        }

        // Create or reuse PDF container
        const previewContentEl = this.elements.previewCode.parentElement.parentElement;
        let pdfContainer = previewContentEl.querySelector('.preview-pdf-container');
        if (!pdfContainer) {
            pdfContainer = document.createElement('div');
            pdfContainer.className = 'preview-pdf-container';
            pdfContainer.style.cssText = 'height: 100%; width: 100%;';
            previewContentEl.appendChild(pdfContainer);
        }
        pdfContainer.classList.remove('hidden');

        // Create PDF embed using data URL
        const dataUrl = `data:application/pdf;base64,${base64Content}`;
        pdfContainer.innerHTML = `<embed src="${dataUrl}" type="application/pdf" width="100%" height="100%" style="border: none;">`;

        // Show the panel and resize handle
        this.elements.resizeHandle.classList.remove('hidden');
        this.elements.previewPanel.classList.remove('hidden');

        // Clear text preview state
        this.previewContent = null;
        this.previewFilename = filename;
        this.previewDataFormat = null;
    }

    /**
     * Render preview content based on current view mode (v1.13.8)
     */
    renderPreviewContent() {
        const content = this.previewContent;
        const filename = this.previewFilename;
        const ext = filename.split('.').pop().toLowerCase() || '';

        // Clean up previous data viewer
        if (this.currentDataViewer) {
            this.currentDataViewer.destroy();
            this.currentDataViewer = null;
        }

        // Hide all preview containers
        this.elements.previewCode.parentElement.classList.add('hidden');
        if (this.elements.previewMarkdown) {
            this.elements.previewMarkdown.classList.add('hidden');
        }
        if (this.elements.previewDataViewer) {
            this.elements.previewDataViewer.classList.add('hidden');
            this.elements.previewDataViewer.innerHTML = '';
        }

        // Check if markdown preview element exists
        const hasMarkdownPreview = this.elements.previewMarkdown !== null;
        const hasDataViewer = this.elements.previewDataViewer !== null;

        // Determine what to render
        const isDataFile = this.previewDataFormat !== null;
        const showRendered = isDataFile && this.previewViewMode === 'rendered';

        if (showRendered && hasDataViewer) {
            // Show data viewer (v1.13.8)
            this.elements.previewDataViewer.classList.remove('hidden');
            this.renderDataViewer(content, ext);
        } else if ((ext === 'md' || ext === 'markdown') && hasMarkdownPreview) {
            // Render markdown
            this.elements.previewMarkdown.classList.remove('hidden');
            this.renderMarkdownPreview(content, filename);
        } else {
            // Show code with syntax highlighting
            this.elements.previewCode.parentElement.classList.remove('hidden');
            this.renderCodePreview(content, ext);
        }
    }

    /**
     * Render data viewer for CSV/JSON/YAML/etc (v1.13.8)
     */
    renderDataViewer(content, ext) {
        const container = this.elements.previewDataViewer;

        if (this.previewDataFormat === 'table') {
            // CSV/TSV - parse and show table
            const delimiter = ext === 'tsv' || ext === 'tab' ? '\t' : this.detectCSVDelimiter(content);
            const data = this.parseCSV(content, delimiter);

            if (typeof DataTableViewer !== 'undefined') {
                this.currentDataViewer = new DataTableViewer(container, data, {
                    pageSize: 100,
                    maxHeight: '500px'
                });
            } else {
                container.innerHTML = '<div class="error">Table viewer not loaded</div>';
            }
        } else if (this.previewDataFormat === 'tree') {
            // JSON/YAML/TOML/HCL - parse and show tree
            try {
                const tree = this.parseStructuredData(content, ext);

                if (typeof DataTreeViewer !== 'undefined') {
                    this.currentDataViewer = new DataTreeViewer(container, tree, {
                        initialExpandDepth: 2
                    });
                } else {
                    container.innerHTML = '<div class="error">Tree viewer not loaded</div>';
                }
            } catch (e) {
                container.innerHTML = `<div class="error">Parse error: ${escapeHtml(e.message)}</div>`;
            }
        }
    }

    /**
     * Render markdown preview
     */
    renderMarkdownPreview(content, filename) {
        if (typeof marked !== 'undefined') {
            marked.setOptions({
                gfm: true,
                breaks: true,
                headerIds: true,
                mangle: false
            });

            let html = marked.parse(content);
            this.elements.previewMarkdown.innerHTML = html;

            // Apply syntax highlighting to code blocks
            if (typeof hljs !== 'undefined') {
                this.elements.previewMarkdown.querySelectorAll('pre code').forEach(block => {
                    hljs.highlightElement(block);
                });
            }

            // Intercept relative link clicks
            this.elements.previewMarkdown.querySelectorAll('a').forEach(link => {
                const href = link.getAttribute('href');
                if (href && !href.startsWith('http') && !href.startsWith('mailto:') && !href.startsWith('#')) {
                    link.addEventListener('click', (e) => {
                        e.preventDefault();
                        const currentDir = filename.includes('/') ? filename.substring(0, filename.lastIndexOf('/')) : '';
                        const resolvedPath = currentDir ? `${currentDir}/${href}` : href;
                        this.handleShowCommand(resolvedPath);
                    });
                }
            });
        } else {
            this.elements.previewMarkdown.textContent = content;
        }
    }

    /**
     * Render code preview with syntax highlighting
     */
    renderCodePreview(content, ext) {
        const langMap = {
            'py': 'python', 'js': 'javascript', 'ts': 'typescript', 'tsx': 'typescript',
            'json': 'json', 'yaml': 'yaml', 'yml': 'yaml',
            'html': 'html', 'css': 'css',
            'sh': 'bash', 'bash': 'bash', 'rs': 'rust', 'go': 'go',
            'java': 'java', 'cpp': 'cpp', 'c': 'c', 'h': 'c',
            'rb': 'ruby', 'php': 'php', 'sql': 'sql', 'xml': 'xml',
            'csv': 'text', 'tsv': 'text', 'toml': 'toml', 'hcl': 'hcl', 'tf': 'hcl'
        };
        const lang = langMap[ext] || '';

        this.elements.previewCode.textContent = content;
        this.elements.previewCode.className = lang ? `language-${lang}` : '';

        if (typeof hljs !== 'undefined' && lang) {
            try {
                hljs.highlightElement(this.elements.previewCode);
            } catch (e) {
                // Highlighting failed, show plain text
            }
        }
    }

    /**
     * Toggle between rendered and source view (v1.13.8)
     */
    togglePreviewViewMode() {
        this.previewViewMode = this.previewViewMode === 'rendered' ? 'source' : 'rendered';
        this.updateViewToggleUI();
        this.renderPreviewContent();
    }

    /**
     * Update view toggle button UI (v1.13.8)
     */
    updateViewToggleUI() {
        if (!this.elements.previewViewToggle) return;

        const renderedSpan = this.elements.previewViewToggle.querySelector('.toggle-rendered');
        const sourceSpan = this.elements.previewViewToggle.querySelector('.toggle-source');

        if (this.previewViewMode === 'rendered') {
            renderedSpan?.classList.add('active');
            sourceSpan?.classList.remove('active');
        } else {
            renderedSpan?.classList.remove('active');
            sourceSpan?.classList.add('active');
        }
    }

    /**
     * Parse CSV/TSV content (v1.13.8)
     */
    parseCSV(content, delimiter = ',') {
        const lines = content.split('\n');
        const headers = [];
        const rows = [];

        lines.forEach((line, i) => {
            if (!line.trim()) return;

            const cells = this.parseCSVLine(line, delimiter);

            if (i === 0) {
                cells.forEach((cell, j) => {
                    headers.push(cell.trim() || `Column ${j + 1}`);
                });
            } else {
                // Pad row to match headers
                while (cells.length < headers.length) {
                    cells.push('');
                }
                rows.push(cells);
            }
        });

        return {
            headers,
            rows,
            rowCount: rows.length,
            columnCount: headers.length
        };
    }

    /**
     * Parse a single CSV line handling quoted fields
     */
    parseCSVLine(line, delimiter) {
        const cells = [];
        let current = '';
        let inQuotes = false;

        for (let i = 0; i < line.length; i++) {
            const char = line[i];
            const nextChar = line[i + 1];

            if (inQuotes) {
                if (char === '"' && nextChar === '"') {
                    current += '"';
                    i++; // Skip next quote
                } else if (char === '"') {
                    inQuotes = false;
                } else {
                    current += char;
                }
            } else {
                if (char === '"') {
                    inQuotes = true;
                } else if (char === delimiter) {
                    cells.push(current);
                    current = '';
                } else {
                    current += char;
                }
            }
        }
        cells.push(current);
        return cells;
    }

    /**
     * Detect CSV delimiter (v1.13.8)
     */
    detectCSVDelimiter(content) {
        const lines = content.split('\n').slice(0, 10);
        const candidates = [',', '\t', ';', '|'];
        const scores = {};

        candidates.forEach(delim => {
            const counts = lines.filter(l => l.trim()).map(l => (l.match(new RegExp(delim === '|' ? '\\|' : delim, 'g')) || []).length);
            if (counts.length > 0) {
                const unique = new Set(counts);
                if (unique.size === 1 && counts[0] > 0) {
                    scores[delim] = counts[0] * 10;
                } else {
                    const avg = counts.reduce((a, b) => a + b, 0) / counts.length;
                    scores[delim] = avg;
                }
            }
        });

        return Object.keys(scores).reduce((a, b) => scores[a] > scores[b] ? a : b, ',');
    }

    /**
     * Parse structured data (JSON/YAML/TOML) into tree format (v1.13.8)
     */
    parseStructuredData(content, ext) {
        let data;

        if (ext === 'json') {
            data = JSON.parse(content);
        } else if (ext === 'yaml' || ext === 'yml') {
            // Use js-yaml library for YAML parsing (v1.13.11)
            if (typeof jsyaml !== 'undefined') {
                data = jsyaml.load(content);
            } else if (content.trim().startsWith('{') || content.trim().startsWith('[')) {
                // Fallback: treat JSON-like YAML as JSON
                data = JSON.parse(content);
            } else {
                throw new Error('YAML parsing requires js-yaml library. Showing source view.');
            }
        } else if (ext === 'toml') {
            // Use smol-toml library for TOML 1.0 parsing (v1.13.11)
            if (typeof smolToml !== 'undefined') {
                data = smolToml.parse(content);
            } else {
                throw new Error('TOML parsing requires smol-toml library. Showing source view.');
            }
        } else if (ext === 'hcl' || ext === 'tf' || ext === 'tfvars') {
            // Use hcl2-parser library for HCL/Terraform parsing (v1.13.11)
            if (typeof hcl2 !== 'undefined' && hcl2.parseToObject) {
                const result = hcl2.parseToObject(content);
                // parseToObject returns [object, error] - check for error
                if (result[1]) {
                    throw new Error(`HCL parse error: ${result[1]}`);
                }
                data = result[0];
            } else {
                throw new Error('HCL parsing requires hcl2-parser library. Showing source view.');
            }
        } else {
            data = JSON.parse(content);
        }

        return this.buildTreeNode('root', data, 0);
    }

    /**
     * Build tree node from data (v1.13.8)
     */
    buildTreeNode(key, value, depth) {
        const node = {
            key: key,
            value: null,
            node_type: 'null',
            children: [],
            depth: depth
        };

        if (value === null) {
            node.node_type = 'null';
            node.value = null;
        } else if (typeof value === 'boolean') {
            node.node_type = 'boolean';
            node.value = value;
        } else if (typeof value === 'number') {
            node.node_type = 'number';
            node.value = value;
        } else if (typeof value === 'string') {
            node.node_type = 'string';
            node.value = value;
        } else if (Array.isArray(value)) {
            node.node_type = 'array';
            node.children = value.map((item, i) => this.buildTreeNode(`[${i}]`, item, depth + 1));
        } else if (typeof value === 'object') {
            node.node_type = 'object';
            node.children = Object.keys(value).map(k => this.buildTreeNode(k, value[k], depth + 1));
        }

        return node;
    }

    hidePreviewPanel() {
        this.elements.previewPanel.classList.add('hidden');
        this.elements.resizeHandle.classList.add('hidden');
        // Clean up data viewer
        if (this.currentDataViewer) {
            this.currentDataViewer.destroy();
            this.currentDataViewer = null;
        }
        // Reset state
        this.previewContent = null;
        this.previewFilename = null;
        this.previewDataFormat = null;
        this.previewViewMode = 'rendered';
    }

    /**
     * Initialize drag-to-resize for preview panel
     */
    initResizeHandle() {
        const handle = this.elements.resizeHandle;
        const panel = this.elements.previewPanel;
        const container = panel.parentElement;  // .main-content

        let isDragging = false;
        let startX = 0;
        let startWidth = 0;

        handle.addEventListener('mousedown', (e) => {
            isDragging = true;
            startX = e.clientX;
            startWidth = panel.offsetWidth;
            handle.classList.add('dragging');
            document.body.style.cursor = 'col-resize';
            document.body.style.userSelect = 'none';
            e.preventDefault();
        });

        document.addEventListener('mousemove', (e) => {
            if (!isDragging) return;

            const containerWidth = container.offsetWidth;
            const deltaX = startX - e.clientX;  // Moving left increases panel width
            let newWidth = startWidth + deltaX;

            // Enforce min/max constraints (200px to 80% of container)
            const minWidth = 200;
            const maxWidth = containerWidth * 0.8;
            newWidth = Math.max(minWidth, Math.min(maxWidth, newWidth));

            panel.style.width = newWidth + 'px';
        });

        document.addEventListener('mouseup', () => {
            if (isDragging) {
                isDragging = false;
                handle.classList.remove('dragging');
                document.body.style.cursor = '';
                document.body.style.userSelect = '';
            }
        });
    }

    // === Debug Log ===

    async toggleDebugLog() {
        try {
            const newState = !this.debugLogEnabled;
            const response = await fetch(`${this.serverUrl}/debug-log`, {
                method: 'POST',
                headers: this.getSessionHeaders(true),
                body: JSON.stringify({ enabled: newState })
            });
            const data = await response.json();
            this.debugLogEnabled = data.enabled;
            this.updateDebugIndicator();
            this.showSystemMessage(`Debug logging ${data.enabled ? 'enabled' : 'disabled'}${data.log_file ? `: ${data.log_file}` : ''}`);
        } catch (error) {
            this.showError(`Failed to toggle debug log: ${error.message}`);
        }
    }

    updateDebugIndicator() {
        this.elements.debugIndicator.className = `menu-indicator ${this.debugLogEnabled ? 'active' : ''}`;
    }

    // === Usage ===

    async updateUsage() {
        try {
            const response = await fetch(`${this.serverUrl}/usage`, {
                headers: this.getSessionHeaders()
            });
            const data = await response.json();

            const prompt = data.prompt_tokens || 0;
            const completion = data.completion_tokens || 0;
            const cost = data.estimated_cost || 0;

            this.usage = { prompt, completion, cost };

            // Format badge
            const formatTokens = (n) => n >= 1000 ? `${(n/1000).toFixed(1)}K` : n;
            this.elements.usageBadge.textContent = `${formatTokens(prompt)}↓/${formatTokens(completion)}↑ $${cost.toFixed(4)}`;
            this.elements.usageBadge.title = `Prompt: ${prompt}, Completion: ${completion}, Cost: $${cost.toFixed(4)}`;
        } catch {}
    }

    // === Context Info (v1.13.9) ===

    async updateContextInfo() {
        try {
            const response = await fetch(`${this.serverUrl}/context/info`, {
                headers: this.getSessionHeaders()
            });
            const data = await response.json();

            const percent = data.usage_percent || 0;
            const tokens = data.estimated_tokens || 0;
            const limit = data.context_limit || 128000;
            const injectedCount = (data.injected_contexts || []).length;

            // Format the display
            const formatTokens = (n) => n >= 1000 ? `${(n/1000).toFixed(0)}K` : n;
            this.elements.contextUsage.textContent = `${percent.toFixed(0)}% (${formatTokens(tokens)}/${formatTokens(limit)})`;

            // Update badge state based on usage percentage
            this.elements.contextBadge.classList.remove('warning', 'critical');
            if (percent >= 100) {
                this.elements.contextBadge.classList.add('critical');
            } else if (percent >= 80) {
                this.elements.contextBadge.classList.add('warning');
            }

            // Update tooltip with details
            let tooltip = `Context: ${percent.toFixed(1)}%\n${formatTokens(tokens)} / ${formatTokens(limit)} tokens`;
            if (injectedCount > 0) {
                tooltip += `\n${injectedCount} injected file(s) - Click to clear`;
            }
            this.elements.contextBadge.title = tooltip;
        } catch {}
    }

    async clearContextInjections() {
        try {
            const response = await fetch(`${this.serverUrl}/context/clear`, {
                method: 'POST',
                headers: this.getSessionHeaders(true)
            });
            const data = await response.json();

            if (data.removed_count > 0) {
                this.showSystemMessage(`Cleared ${data.removed_count} injected context(s) from conversation.`);
            } else {
                this.showSystemMessage('No injected contexts to clear.');
            }

            // Update the badge
            await this.updateContextInfo();
        } catch (error) {
            console.error('Failed to clear context:', error);
        }
    }

    // === Theme ===

    applyTheme() {
        if (this.theme === 'system') {
            const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
            document.body.dataset.theme = prefersDark ? 'dark' : 'light';
        } else {
            document.body.dataset.theme = this.theme;
        }

        this.elements.themeBtn.textContent = this.theme === 'dark' ? '🌙' : '☀️';
        this.elements.themeSetting.value = this.theme;
    }

    cycleTheme() {
        const themes = ['dark', 'light'];
        const currentIndex = themes.indexOf(this.theme);
        this.theme = themes[(currentIndex + 1) % themes.length];
        this.applyTheme();
        localStorage.setItem('ppxai-theme', this.theme);
    }

    // === Settings ===

    showSettings() {
        this.elements.serverUrlSetting.value = this.serverUrl;
        this.elements.themeSetting.value = this.theme;
        this.elements.settingsModal.classList.remove('hidden');
    }

    hideSettings() {
        this.elements.settingsModal.classList.add('hidden');
    }

    // === Utilities ===

    renderMarkdown(text) {
        if (typeof marked !== 'undefined') {
            try {
                return marked.parse(text);
            } catch (e) {
                return escapeHtml(text);
            }
        }
        return escapeHtml(text);
    }

    /**
     * Get headers with session ID for API requests (v1.14.0)
     */
    getSessionHeaders(includeContentType = false) {
        const headers = {
            'X-Session-Id': this.sessionId
        };
        if (includeContentType) {
            headers['Content-Type'] = 'application/json';
        }
        return headers;
    }

    scrollToBottom() {
        this.elements.messagesContainer.scrollTop = this.elements.messagesContainer.scrollHeight;
    }
}

// Initialize app when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    window.ppxai = new PpxaiApp();
});
