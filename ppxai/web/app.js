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
            this.sessionId = `webapp-${this.generateUUID()}`;
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

            // Load usage
            await this.updateUsage();

            // Load debug log status
            try {
                const debugResp = await fetch(`${this.serverUrl}/debug-log`, {
                    headers: this.getSessionHeaders()
                });
                const debugData = await debugResp.json();
                this.debugLogEnabled = debugData.enabled;
                this.updateDebugIndicator();
            } catch {}

        } catch (error) {
            this.showError(`Failed to load initial state: ${error.message}`);
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
            await fetch(`${this.serverUrl}/providers`, {
                method: 'POST',
                headers: this.getSessionHeaders(true),
                body: JSON.stringify({ provider: providerId })
            });
            this.currentProvider = providerId;
            await this.loadModels();

            // Get new default model
            const statusResp = await fetch(`${this.serverUrl}/status`, {
                headers: this.getSessionHeaders()
            });
            const status = await statusResp.json();
            this.currentModel = status.model;
            this.elements.modelSelect.value = this.currentModel;

            this.showSystemMessage(`Switched to provider: ${providerId}`);
        } catch (error) {
            this.showError(`Failed to switch provider: ${error.message}`);
        }
    }

    async handleModelChange() {
        const modelId = this.elements.modelSelect.value;
        try {
            await fetch(`${this.serverUrl}/models`, {
                method: 'POST',
                headers: this.getSessionHeaders(true),
                body: JSON.stringify({ model: modelId })
            });
            this.currentModel = modelId;
            this.showSystemMessage(`Switched to model: ${modelId}`);
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
            this.scrollToBottom();
        }
    }

    handleStreamEvent(event, contentEl, fullContent) {
        switch (event.type) {
            case 'stream_chunk':
                // v1.13.2: Clear thinking indicator when first content arrives
                if (!fullContent && event.data) {
                    this.clearThinkingIndicator(contentEl);
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
                this.showSystemMessage(event.data);
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
                // Update undo badge
                this.elements.undoBadge.classList.remove('hidden');
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

            case '/theme':
                this.handleThemeCommand(args);
                break;

            case '/show':
            case '/cat':
                await this.handleShowCommand(args);
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
        const parts = args.trim().split(/\s+/);
        const subCmd = parts[0];

        // Check for subcommands first
        if (subCmd === 'show') {
            const mode = parts[1];
            if (mode && ['session', 'provider', 'model', 'off'].includes(mode)) {
                try {
                    await fetch(`${this.serverUrl}/usage/display`, {
                        method: 'POST',
                        headers: this.getSessionHeaders(true),
                        body: JSON.stringify({ mode })
                    });
                    this.showSystemMessage(`Usage display mode set to: ${mode}`);
                } catch (error) {
                    this.showError(`Failed to set usage display mode: ${error.message}`);
                }
            } else {
                this.addMessage('system', '**Usage Display Mode**\n\nUsage: `/usage show <mode>`\n\nModes:\n- `session`: Show session totals\n- `provider`: Show by provider\n- `model`: Show by model\n- `off`: Hide usage display');
            }
            return;
        }

        if (subCmd === 'reset') {
            try {
                await fetch(`${this.serverUrl}/usage/reset`, {
                    method: 'POST',
                    headers: this.getSessionHeaders(true)
                });
                this.showSystemMessage('Usage counters reset.');
            } catch (error) {
                this.showError(`Failed to reset usage: ${error.message}`);
            }
            return;
        }

        // Period-based report (24h, week, month, year, all) or no args
        try {
            const period = ['24h', 'week', 'month', 'year', 'all'].includes(subCmd) ? subCmd : null;
            const endpoint = period ? `/usage/report?period=${period}` : '/usage';
            const response = await fetch(`${this.serverUrl}${endpoint}`, {
                headers: this.getSessionHeaders()
            });
            const data = await response.json();

            let text = '**Usage Statistics:**\n\n';

            if (period) {
                text += `**Period:** ${data.period}\n`;
                text += `**Sessions:** ${data.session_count}\n\n`;
            }

            // Summary stats as list
            text += `- Total tokens: ${(data.total_tokens || 0).toLocaleString()} (${(data.prompt_tokens || 0).toLocaleString()}↓ / ${(data.completion_tokens || 0).toLocaleString()}↑)\n`;
            text += `- Estimated cost: $${(data.estimated_cost || data.total_cost || 0).toFixed(4)}\n`;

            // Per-model breakdown as table (matching VSCode extension format)
            if (data.by_model && Object.keys(data.by_model).length > 0) {
                text += '\n**Usage by Model:**\n\n';
                text += '| Provider | Model | In | Out | Cost |\n';
                text += '|:---------|:------|---:|----:|-----:|\n';
                Object.entries(data.by_model).sort().forEach(([key, stats]) => {
                    const [provider, model] = key.includes('/') ? key.split('/', 2) : ['', key];
                    text += `| ${provider} | ${model} | ${stats.prompt_tokens?.toLocaleString() || 0} | ${stats.completion_tokens?.toLocaleString() || 0} | $${stats.estimated_cost?.toFixed(4) || '0.0000'} |\n`;
                });
                // Totals row
                text += `| **TOTAL** | | **${(data.prompt_tokens || 0).toLocaleString()}** | **${(data.completion_tokens || 0).toLocaleString()}** | **$${(data.estimated_cost || 0).toFixed(4)}** |\n`;
            }

            this.addMessage('system', text);
        } catch (error) {
            this.showError(`Failed to get usage: ${error.message}`);
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

        msgEl.innerHTML = `
            <div class="message-header">
                <span class="message-role">${role === 'user' ? 'You' : role === 'assistant' ? 'Assistant' : 'System'}</span>
                <span class="message-time">${timestamp}</span>
            </div>
            <div class="message-content">${streaming ? thinkingHtml : this.renderMarkdown(content)}</div>
        `;

        this.elements.messagesContainer.appendChild(msgEl);
        this.scrollToBottom();

        return msgEl;
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

    showSystemMessage(content) {
        this.addMessage('system', content);
    }

    showError(message) {
        const msgEl = document.createElement('div');
        msgEl.className = 'message error-message';
        msgEl.innerHTML = `
            <div class="message-content">${this.escapeHtml(message)}</div>
        `;
        this.elements.messagesContainer.appendChild(msgEl);
        this.scrollToBottom();
    }

    showToolCall(data) {
        const msgEl = document.createElement('div');
        msgEl.className = 'message tool-message';

        let content = `<div class="tool-header" onclick="this.parentElement.classList.toggle('expanded')">
            <span class="tool-icon">🔧</span>
            <span class="tool-name">${this.escapeHtml(data.tool || 'Unknown tool')}</span>
            <span class="tool-expand">▶</span>
        </div>`;

        if (this.verbose && data.arguments) {
            content += `<div class="tool-details">
                <pre>${this.escapeHtml(typeof data.arguments === 'string' ? data.arguments : JSON.stringify(data.arguments, null, 2))}</pre>
            </div>`;
        }

        msgEl.innerHTML = content;

        // Insert before current assistant message to show tool calls before the answer
        if (this.currentAssistantMessage) {
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
            <span class="tool-name">${this.escapeHtml(data.tool || 'Result')}</span>
            <span class="tool-expand">▶</span>
        </div>`;

        if (this.verbose && data.result) {
            const result = typeof data.result === 'string' ? data.result : JSON.stringify(data.result, null, 2);
            content += `<div class="tool-details">
                <pre>${this.escapeHtml(result.slice(0, 2000))}${result.length > 2000 ? '\n...(truncated)' : ''}</pre>
            </div>`;
        }

        msgEl.innerHTML = content;

        // Insert before current assistant message
        if (this.currentAssistantMessage) {
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
                <span class="context-source">${this.escapeHtml(data.source || 'Context')}</span>
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
        // Note: In the web UI, we can't directly search files.
        // We'd need a server endpoint for this. For now, show common patterns.
        this.autocompleteType = 'file';
        this.autocompleteItems = [
            { label: '@git', description: 'Include git diff', value: '@git' },
            { label: '@tree', description: 'Include project structure', value: '@tree' },
        ];

        if (query && query.length > 0) {
            // Filter based on query
            this.autocompleteItems = this.autocompleteItems.filter(item =>
                item.label.toLowerCase().includes(query.toLowerCase())
            );
        }

        this.autocompleteIndex = 0;
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
                <span class="autocomplete-label">${this.escapeHtml(item.label)}</span>
                <span class="autocomplete-desc">${this.escapeHtml(item.description)}</span>
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

                // Show in preview panel
                this.showPreviewPanel(data.filename || filepath, data.content, data.size, data.lines);
            } else {
                const error = await response.json();
                this.showError(`Failed to read file: ${error.detail || 'File not found'}`);
            }
        } catch (error) {
            this.showError(`Failed to read file: ${error.message}`);
        }
    }

    showPreviewPanel(filename, content, size, lines) {
        // Update filename
        this.elements.previewFilename.textContent = filename;

        // Update info
        let info = '';
        if (lines) info += `${lines} lines`;
        if (size) info += info ? ` • ${(size / 1024).toFixed(1)} KB` : `${(size / 1024).toFixed(1)} KB`;
        this.elements.previewInfo.textContent = info;

        // Determine file extension
        const ext = filename.split('.').pop().toLowerCase() || '';

        // Check if markdown preview element exists (may not in older HTML versions)
        const hasMarkdownPreview = this.elements.previewMarkdown !== null;

        // Check if this is a markdown file and we have the preview element
        if ((ext === 'md' || ext === 'markdown') && hasMarkdownPreview) {
            // Render markdown with marked.js
            this.elements.previewCode.parentElement.classList.add('hidden');
            this.elements.previewMarkdown.classList.remove('hidden');

            if (typeof marked !== 'undefined') {
                // Configure marked for GFM (tables, code blocks, etc.)
                marked.setOptions({
                    gfm: true,
                    breaks: true,
                    headerIds: true,
                    mangle: false
                });

                // Parse and render markdown
                let html = marked.parse(content);

                // Set the rendered HTML
                this.elements.previewMarkdown.innerHTML = html;

                // Apply syntax highlighting to code blocks
                if (typeof hljs !== 'undefined') {
                    this.elements.previewMarkdown.querySelectorAll('pre code').forEach(block => {
                        hljs.highlightElement(block);
                    });
                }

                // Intercept relative link clicks to show files in preview (v1.14.0)
                this.elements.previewMarkdown.querySelectorAll('a').forEach(link => {
                    const href = link.getAttribute('href');
                    // Handle relative links to local files (not http/https/mailto)
                    if (href && !href.startsWith('http') && !href.startsWith('mailto:') && !href.startsWith('#')) {
                        link.addEventListener('click', (e) => {
                            e.preventDefault();
                            // Resolve relative path from current file's directory
                            const currentDir = filename.includes('/') ? filename.substring(0, filename.lastIndexOf('/')) : '';
                            const resolvedPath = currentDir ? `${currentDir}/${href}` : href;
                            this.handleShowCommand(resolvedPath);
                        });
                    }
                });
            } else {
                // Fallback: show raw content if marked not available
                this.elements.previewMarkdown.textContent = content;
            }
        } else {
            // Non-markdown or no markdown preview: show code with syntax highlighting
            if (hasMarkdownPreview) {
                this.elements.previewMarkdown.classList.add('hidden');
            }
            this.elements.previewCode.parentElement.classList.remove('hidden');

            const langMap = {
                'py': 'python', 'js': 'javascript', 'ts': 'typescript', 'tsx': 'typescript',
                'json': 'json', 'yaml': 'yaml', 'yml': 'yaml',
                'html': 'html', 'css': 'css',
                'sh': 'bash', 'bash': 'bash', 'rs': 'rust', 'go': 'go',
                'java': 'java', 'cpp': 'cpp', 'c': 'c', 'h': 'c',
                'rb': 'ruby', 'php': 'php', 'sql': 'sql', 'xml': 'xml'
            };
            const lang = langMap[ext] || '';

            // Set content with syntax highlighting
            this.elements.previewCode.textContent = content;
            if (lang) {
                this.elements.previewCode.className = `language-${lang}`;
            } else {
                this.elements.previewCode.className = '';
            }

            // Apply syntax highlighting
            if (typeof hljs !== 'undefined' && lang) {
                try {
                    hljs.highlightElement(this.elements.previewCode);
                } catch (e) {
                    // Highlighting failed, show plain text
                }
            }
        }

        // Show the panel
        this.elements.previewPanel.classList.remove('hidden');
    }

    hidePreviewPanel() {
        this.elements.previewPanel.classList.add('hidden');
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
                return this.escapeHtml(text);
            }
        }
        return this.escapeHtml(text);
    }

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    /**
     * Generate a UUID v4 (v1.14.0)
     */
    generateUUID() {
        return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
            const r = Math.random() * 16 | 0;
            const v = c === 'x' ? r : (r & 0x3 | 0x8);
            return v.toString(16);
        });
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
