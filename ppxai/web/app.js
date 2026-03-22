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
        // Use current page origin as server URL (since server serves the web UI).
        // When deployed under a path prefix (e.g. /s/alice/), include the prefix
        // so API calls route through the ingress to the correct per-user backend.
        // Fall back to localStorage or default only if origin is file:// or about:
        const pageOrigin = window.location.origin;
        const usePageOrigin = pageOrigin && !pageOrigin.startsWith('file:') && pageOrigin !== 'null';
        const pathPrefix = window.location.pathname.match(/^(\/s\/[^/]+)/)?.[1] || '';
        this.serverUrl = usePageOrigin ? (pageOrigin + pathPrefix) : (localStorage.getItem('ppxai-server-url') || 'http://127.0.0.1:54320');

        // Session ID for server session isolation (v1.14.0)
        // Each browser tab/window gets its own session ID
        this.sessionId = sessionStorage.getItem('ppxai-session-id');
        if (!this.sessionId) {
            this.sessionId = `webapp-${generateUUID()}`;
            sessionStorage.setItem('ppxai-session-id', this.sessionId);
        }
        console.log(`[PpxaiApp] Session ID: ${this.sessionId}`);

        // Shared API client — wraps all HTTP calls to the server (v1.16.2)
        this.apiClient = new ApiClient(this.serverUrl, this.sessionId);

        // Stream handler — SSE client for /chat (v1.16.2)
        this.streamHandler = new StreamHandler({
            serverUrl:  this.serverUrl,
            getHeaders: (ct) => this.getSessionHeaders(ct)
        });

        // Command dispatcher — handles all slash commands (v1.16.2)
        this.commandDispatcher = new CommandDispatcher(this);

        // State — all mutable state is managed via AppState (observable Proxy)
        // Canonical fields match Python AppState (snake_case → camelCase).
        this.state = new AppState({
            // --- Canonical fields (match ppxai/engine/app_state.py) ---
            // Core identity
            currentProvider: '',
            currentModel:    '',
            workingDir:      '',
            sessionId:       this.sessionId,
            sessionName:     '',

            // Feature toggles
            toolsEnabled:  false,
            toolsVerbose:  false,
            agentMode:     false,
            autoRoute:     false,

            // Streaming / flow control
            isStreaming:      false,
            cancelRequested: false,

            // Usage statistics (flattened from previous {prompt, completion, cost} object)
            totalTokens:       0,
            promptTokens:      0,
            completionTokens:  0,
            totalCost:         0.0,
            contextPercentage: 0.0,

            // Debug
            debugLog: false,

            // --- Web-app-specific fields (not in canonical set) ---
            // UI theme
            theme: localStorage.getItem('ppxai-theme') || 'dark',

            // Flow control (web-specific)
            isSending:               false,
            isHandlingCommand:       false,
            currentAbortController:  null,
            currentAssistantMessage: null,

            // Command history (restored from localStorage)
            commandHistory: JSON.parse(localStorage.getItem('ppxai-history') || '[]'),
            historyIndex:   -1,

            // Checkpoints
            lastCheckpoint:  null,
            checkpointCount: 0,

            // Preview panel
            previewViewMode:   'rendered',
            previewContent:    null,
            previewFilename:   null,
            previewDataFormat: null,

            // Autocomplete
            autocompleteVisible: false,
            autocompleteItems:   [],
            autocompleteIndex:   0,
            autocompleteType:    null,

            // HTML preview
            htmlPreviewActive:   false,
            htmlPreviewFilepath: null,

            // RightPanelFrame config (overridden from GET /config web_ui section)
            rpfStackSize: 10,
            rpfDedup:     true,
            rpfPersist:   false,

            // RightPanelFrame runtime state (written by RightPanelFrame._notifyChange)
            rpfStackDepth:  0,
            rpfActiveTitle: null,
            rpfActiveDirty: false,
        });

        // Non-state instance data
        this.currentDataViewer = null;      // Current viewer instance (not reactive state)
        this._domMessageCount = 0;          // DOM message count for virtual scroll (item 10)

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

        // v1.16.2: Virtual scroll sentinel — grows to replace trimmed messages
        this._scrollSpacer = document.createElement('div');
        this._scrollSpacer.className = 'message-spacer';
        this.elements.messagesContainer.prepend(this._scrollSpacer);

        this._initRightPanelFrame();
        this._restoreRpfStack();    // Phase 4: re-open files from previous session
        this.setupEventListeners();
        this.applyTheme();
        this.setupMarkdown();
        await this.connectToServer();

        // v1.17.0: Start heartbeat watchdog
        this._heartbeatFailCount = 0;
        this._heartbeatTimer = setInterval(() => this._heartbeat(), 15000);
    }

    /**
     * Periodic health check. Detects stuck connections and server unavailability.
     * After 2 consecutive failures: marks disconnected, aborts any stuck stream.
     * On recovery: reconnects and re-enables UI.
     */
    async _heartbeat() {
        try {
            const resp = await fetch(`${this.serverUrl}/health`, {
                signal: AbortSignal.timeout(5000)
            });
            if (resp.ok) {
                if (this._heartbeatFailCount >= 2) {
                    // Recovered — reconnect
                    this.updateServerStatus('connected');
                    this.showSystemMessage('Server connection restored.');
                }
                this._heartbeatFailCount = 0;
                return;
            }
        } catch {}

        this._heartbeatFailCount++;

        if (this._heartbeatFailCount === 2) {
            this.updateServerStatus('disconnected');

            // Abort any stuck streaming request
            if (this.state.isStreaming && this.state.currentAbortController) {
                this.state.currentAbortController.abort();
                this.showSystemMessage('Connection lost - stream interrupted. Retrying...', 'warning');
            }
        }

        // After 4 consecutive failures (1 min), attempt full reconnect
        if (this._heartbeatFailCount === 4) {
            this._heartbeatFailCount = 0;
            this.connectToServer(true);
        }
    }

    _initRightPanelFrame() {
        const el = this.elements;
        if (!el.rpfFrame) return;

        // Phase 4: Read RPF config from localStorage (user preferences)
        const savedSize = parseInt(localStorage.getItem('ppxai-rpf-stack-size'), 10);
        if (savedSize > 0 && savedSize <= 50) this.state.rpfStackSize = savedSize;
        const savedPersist = localStorage.getItem('ppxai-rpf-persist');
        if (savedPersist !== null) this.state.rpfPersist = savedPersist === 'true';

        // Expose apiClient on state so view types can access it without extra args
        this.state.apiClient = this.apiClient;

        // Frame uses #rpfViewport as its content area
        this.rightPanelFrame = new RightPanelFrame(el.rpfFrame, this.state);
        this.rightPanelFrame._viewportEl = el.rpfViewport;

        // AppState observers → update chrome and persist stack on change
        this.state.on('rpfActiveTitle', () => this._updateFrameChrome());
        this.state.on('rpfActiveDirty', () => this._updateFrameChrome());
        this.state.on('rpfStackDepth',  () => { this._updateFrameChrome(); this._saveRpfStack(); });

        // Chrome button wiring
        el.rpfClose.addEventListener('click', () => this.rightPanelFrame.hideFrame());
        el.rpfBack.addEventListener('click',  () => this.rightPanelFrame.back());
        el.rpfFwd.addEventListener('click',   () => this.rightPanelFrame.forward());

        // Stack dropdown toggle
        el.rpfStackMenuBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            this._toggleRpfDropdown();
        });

        // Close dropdown on outside click
        document.addEventListener('click', () => {
            el.rpfStackDropdown?.classList.add('hidden');
        });

        // Keyboard routing — capture phase so view keydown fires before bubbling
        el.rpfFrame.addEventListener('keydown', (e) => {
            this.rightPanelFrame.handleKeyDown(e);
        }, true);
    }

    /** Update frame chrome elements from current AppState values. */
    _updateFrameChrome() {
        const el    = this.elements;
        const frame = this.rightPanelFrame;
        if (!frame || !el.rpfTitle) return;

        el.rpfTitle.textContent = this.state.rpfActiveTitle ?? '—';
        el.rpfDirty?.classList.toggle('hidden', !this.state.rpfActiveDirty);

        const depth = this.state.rpfStackDepth ?? 0;
        el.rpfPosition.textContent = depth > 1 ? `${depth}` : '';
        el.rpfBack.disabled = depth < 2;
        el.rpfFwd.disabled  = depth < 2;
    }

    /** Build and toggle the stack dropdown. */
    _toggleRpfDropdown() {
        const el    = this.elements;
        const frame = this.rightPanelFrame;
        const dd    = el.rpfStackDropdown;
        if (!dd || !frame) return;

        if (!dd.classList.contains('hidden')) {
            dd.classList.add('hidden');
            return;
        }

        // Build dropdown from current stack info
        const items = frame.getStackInfo();
        dd.innerHTML = items.map(item => `
            <div class="rpf-stack-item${item.isActive ? ' rpf-active' : ''}"
                 data-stack-index="${item.stackIndex}">
                <span class="rpf-stack-item-icon">${item.icon}</span>
                <span class="rpf-stack-item-title">${_rpfEsc(item.title)}</span>
                ${item.isDirty ? '<span class="rpf-stack-item-dirty">●</span>' : ''}
                <button class="rpf-pin-btn${item.isPinned ? ' pinned' : ''}"
                        data-stack-index="${item.stackIndex}"
                        title="${item.isPinned ? 'Unpin' : 'Pin to stack'}">📌</button>
                <button class="rpf-close-item-btn"
                        data-stack-index="${item.stackIndex}"
                        title="Close">x</button>
            </div>
        `).join('');

        dd.querySelectorAll('.rpf-stack-item').forEach(row => {
            row.addEventListener('click', (e) => {
                e.stopPropagation();
                const idx = parseInt(row.dataset.stackIndex, 10);
                frame.activateByIndex(idx);
                dd.classList.add('hidden');
            });
        });

        // Pin toggle — stops propagation so it doesn't also activate the view
        dd.querySelectorAll('.rpf-pin-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                const idx  = parseInt(btn.dataset.stackIndex, 10);
                const view = frame._stack[idx];
                if (!view) return;
                if (view.isPinned()) view.unpin(); else view.pin();
                btn.classList.toggle('pinned', view.isPinned());
                btn.title = view.isPinned() ? 'Unpin' : 'Pin to stack';
            });
        });

        // Close button — remove view from stack
        dd.querySelectorAll('.rpf-close-item-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                const idx = parseInt(btn.dataset.stackIndex, 10);
                frame.closeByIndex(idx);
                dd.classList.add('hidden');
            });
        });

        dd.classList.remove('hidden');
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

            // File sidebar
            fileSidebar: document.getElementById('fileSidebar'),
            sidebarToggleBtn: document.getElementById('sidebarToggleBtn'),
            sidebarResizeHandle: document.getElementById('sidebarResizeHandle'),

            // Right Panel Frame
            rpfFrame:        document.getElementById('rpfFrame'),
            rpfViewport:     document.getElementById('rpfViewport'),
            rpfTitle:        document.getElementById('rpfTitle'),
            rpfDirty:        document.getElementById('rpfDirty'),
            rpfPosition:     document.getElementById('rpfPosition'),
            rpfBack:         document.getElementById('rpfBack'),
            rpfFwd:          document.getElementById('rpfFwd'),
            rpfClose:        document.getElementById('rpfClose'),
            rpfStackMenuBtn: document.getElementById('rpfStackMenuBtn'),
            rpfStackDropdown: document.getElementById('rpfStackDropdown'),
            resizeHandle:    document.getElementById('resizeHandle'),

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
        // Prevent accidental tab/window close when session is active
        window.addEventListener('beforeunload', (e) => {
            // Only warn if there's an active chat (messages beyond the welcome)
            const hasMessages = this.elements.messagesContainer &&
                this.elements.messagesContainer.querySelectorAll('.message.user-message').length > 0;
            if (hasMessages) {
                e.preventDefault();
                // Modern browsers ignore custom messages but require returnValue
                e.returnValue = '';
            }
        });

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
            this.state.theme = this.elements.themeSetting.value;
            this.applyTheme();
            localStorage.setItem('ppxai-theme', this.state.theme);
        });
        this.elements.serverUrlSetting.addEventListener('change', () => {
            this.serverUrl = this.elements.serverUrlSetting.value;
            this.apiClient.setServerUrl(this.serverUrl);
            this.streamHandler.setServerUrl(this.serverUrl);
            localStorage.setItem('ppxai-server-url', this.serverUrl);
            this.connectToServer();
        });

        // File sidebar toggle button
        if (this.elements.sidebarToggleBtn) {
            this.elements.sidebarToggleBtn.addEventListener('click', () => this.toggleFileSidebar());
        }

        // Right panel frame resize handle
        this.initResizeHandle();

        // Sidebar resize handle
        this.initSidebarResizeHandle();

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
                if (this.state.isStreaming) {
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
     * v1.17.0: In coder mode (path prefix /s/<user>), redirect to login
     * instead of killing the server — the pod must stay alive.
     */
    async handleQuit() {
        const pathPrefix = window.location.pathname.match(/^(\/s\/[^/]+)/)?.[1] || '';

        if (pathPrefix) {
            // Coder mode: don't kill the server, redirect to login
            const confirmed = confirm('Leave this session and return to login?');
            if (!confirmed) return;
            window.location.href = '/login';
            return;
        }

        // Desktop/local mode: shutdown server and close tab
        const confirmed = confirm('Stop the ppxai server and close this tab?');
        if (!confirmed) return;

        try {
            this.updateServerStatus('connecting');
            this.elements.serverStatus.textContent = 'Stopping...';

            await this.apiClient.shutdown();
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
            const result = await this.apiClient.reloadConfig();
            this.showSystemMessage(`Configuration reloaded from ${result.config_path || 'defaults'}`);
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
            const data = await this.apiClient.getWorkingDir();
            this.updateFolderBadge(data.path);
        } catch (e) {
            console.error('Failed to load working directory:', e);
        }
    }

    async setWorkingDir(path) {
        try {
            const data = await this.apiClient.setWorkingDir(path);
            this.updateFolderBadge(data.path);
            this.showSystemMessage(`Working directory set to: ${data.path}`);
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
            const providersData = await this.apiClient.getProviders();
            this.populateProviders(providersData.providers);

            // Load status
            const status = await this.apiClient.getStatus();
            this.state.currentProvider = status.provider;
            this.state.currentModel = status.model;
            this.state.toolsEnabled = status.tools_enabled;

            // Select current provider/model
            this.elements.providerSelect.value = this.state.currentProvider;
            await this.loadModels();
            this.elements.modelSelect.value = this.state.currentModel;

            // Update badges
            this.updateToolsBadge();

            // Load working directory
            await this.loadWorkingDir();

            // Load tools status
            const toolsData = await this.apiClient.getTools();
            this.state.toolsVerbose = toolsData.verbose || false;

            // Load agent status
            try {
                const agentData = await this.apiClient.getAgentStatus();
                this.state.agentMode = agentData.agent_mode;
                this.updateAgentBadge();

                // Update undo badge
                if (agentData.checkpoint && agentData.checkpoint.last_checkpoint) {
                    this.state.lastCheckpoint = agentData.checkpoint.last_checkpoint;
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
                const debugData = await this.apiClient.getDebugLogStatus();
                this.state.debugLog = debugData.enabled;
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
            const data = await this.apiClient.getLastSession();

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
            const data = await this.apiClient.restoreSession();
            this.showSystemMessage(`✓ Session restored: ${data.name} (${data.message_count} messages)`);

            // Update state from restored session
            if (data.working_dir) {
                this.elements.folderPath.textContent = data.working_dir;
            }
            if (data.tools_enabled) {
                this.state.toolsEnabled = true;
                this.updateToolsBadge();
            }

            // Restore provider and model (v1.15.3)
            if (data.provider) {
                this.state.currentProvider = data.provider;
                this.elements.providerSelect.value = data.provider;
                console.log(`[PpxaiApp] Restored provider: ${data.provider}`);
            }
            if (data.model) {
                this.state.currentModel = data.model;
                // Reload models for the restored provider
                await this.loadModels();
                this.elements.modelSelect.value = data.model;
                console.log(`[PpxaiApp] Restored model: ${data.model}`);
            }

            // Reload working dir badge
            await this.loadWorkingDir();
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
            const data = await this.apiClient.getModels();

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
            const data = await this.apiClient.setProvider(providerId);
            this.state.currentProvider = providerId;
            await this.loadModels();

            // Get new default model
            const status = await this.apiClient.getStatus();
            this.state.currentModel = status.model;
            this.elements.modelSelect.value = this.state.currentModel;

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
            const data = await this.apiClient.setModel(modelId);
            this.state.currentModel = modelId;
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
            const newState = !this.state.toolsEnabled;
            await this.apiClient.setToolsEnabled(newState);
            this.state.toolsEnabled = newState;
            this.updateToolsBadge();
            this.showSystemMessage(`Tools ${newState ? 'enabled' : 'disabled'}`);
        } catch (error) {
            this.showError(`Failed to toggle tools: ${error.message}`);
        }
    }

    updateToolsBadge() {
        this.elements.toolsStatus.textContent = `Tools: ${this.state.toolsEnabled ? 'on' : 'off'}`;
        this.elements.toolsBadge.classList.toggle('enabled', this.state.toolsEnabled);
    }

    async toggleAgent() {
        try {
            const newState = !this.state.agentMode;
            const data = await (newState ? this.apiClient.enableAgent() : this.apiClient.disableAgent());
            this.state.agentMode = data.agent_mode;
            this.state.toolsEnabled = data.tools_enabled || this.state.toolsEnabled;
            this.updateAgentBadge();
            this.updateToolsBadge();
            this.showSystemMessage(`Agent mode ${this.state.agentMode ? 'enabled' : 'disabled'}`);
        } catch (error) {
            this.showError(`Failed to toggle agent: ${error.message}`);
        }
    }

    updateAgentBadge() {
        this.elements.agentStatus.textContent = `Agent: ${this.state.agentMode ? 'on' : 'off'}`;
        this.elements.agentBadge.classList.toggle('enabled', this.state.agentMode);
    }

    async undoCheckpoint() {
        try {
            const data = await this.apiClient.undoCheckpoint();
            this.showSystemMessage(data.message || 'Checkpoint restored');
            this.elements.undoBadge.classList.add('hidden');
            this.state.lastCheckpoint = null;
        } catch (error) {
            this.showError(`Undo failed: ${error.message}`);
        }
    }

    // === Chat ===

    async sendMessage() {
        const content = this.elements.messageInput.value.trim();
        if (!content || this.state.isStreaming || this.state.isSending) return;

        // Debounce guard to prevent rapid-fire
        this.state.isSending = true;

        // Save to history
        if (content !== this.state.commandHistory[0]) {
            this.state.commandHistory.unshift(content);
            if (this.state.commandHistory.length > 100) this.state.commandHistory.pop();
            localStorage.setItem('ppxai-history', JSON.stringify(this.state.commandHistory));
        }
        this.state.historyIndex = -1;

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
                this.state.isSending = false;
            }
            return;
        }

        // Show user message
        this.addMessage('user', content);

        // Start streaming (isSending will be reset by streamChat's finally block)
        await this.streamChat(content);
    }

    async streamChat(message) {
        this.state.isStreaming = true;
        this.elements.streamingBadge.classList.remove('hidden');
        this.state.currentAbortController = new AbortController();

        // Create assistant message container
        const msgEl = this.addMessage('assistant', '', true);
        const contentEl = msgEl.querySelector('.message-content');
        let fullContent = '';
        // Track inline image markdown appended during streaming so stream_end doesn't lose it
        this._streamInlineImages = '';

        // Track this as the current assistant message for correct tool call ordering
        this.state.currentAssistantMessage = msgEl;

        try {
            // v1.16.2: Delegate SSE fetch + line-buffering to StreamHandler
            for await (const event of this.streamHandler.stream(message, this.state.currentAbortController.signal)) {
                fullContent = this.handleStreamEvent(event, contentEl, fullContent);
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
            this.state.isStreaming = false;
            this.state.isSending = false;
            this.elements.streamingBadge.classList.add('hidden');
            this.state.currentAbortController = null;
            this.state.currentAssistantMessage = null;
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
                // Debounce markdown rendering via rAF — avoids layout thrashing
                if (!this._streamRafPending) {
                    this._streamRafPending = true;
                    requestAnimationFrame(() => {
                        contentEl.innerHTML = this.renderMarkdown(fullContent);
                        this.scrollToBottom();
                        this._streamRafPending = false;
                    });
                }
                break;

            case 'stream_end':
                // v1.13.2: Clear thinking indicator on stream end
                this.clearThinkingIndicator(contentEl);
                // Full response (especially when tools are used).
                // Append any inline image markdown that was injected during streaming —
                // stream_end carries the canonical text-only response from the server.
                if (event.data && event.data.trim()) {
                    // Inline images precede the AI text — preserves the order shown
                    // during streaming (display_file fires before the final response).
                    fullContent = (this._streamInlineImages || '') + event.data;
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
                    this.state.checkpointCount = (this.state.checkpointCount || 0) + 1;
                } else {
                    let msg = event.data;
                    // Enrich commit message with checkpoint count
                    if (this.state.checkpointCount > 0 && typeof msg === 'string' && msg.startsWith('✓ Changes committed:')) {
                        msg += ` (${this.state.checkpointCount} file${this.state.checkpointCount !== 1 ? 's' : ''} checkpointed)`;
                        this.state.checkpointCount = 0;
                    }
                    this.showSystemMessage(msg);
                }
                break;

            case 'working_dir_changed':
                // Update folder badge when working directory changes (v1.13.2)
                if (event.data && event.data.path) {
                    this.updateFolderBadge(event.data.path);
                    // Debounce file tree refresh — session restore fires multiple
                    // working_dir_changed events in quick succession; only refresh once.
                    // Also skip the refresh if cwd hasn't actually changed (avoids flicker
                    // on every chat send when session restore replays the same cwd).
                    if (this._fileTree) {
                        const newPath = event.data.path;
                        clearTimeout(this._fileTreeRefreshTimer);
                        this._fileTreeRefreshTimer = setTimeout(() => {
                            if (newPath !== this._fileTreeCurrentPath) {
                                this._fileTreeCurrentPath = newPath;
                                this._fileTree.refresh(true);
                            }
                        }, 300);
                    }
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
                    const fp = event.data.filepath;
                    // v1.16.2: Inject inline image into chat bubble for image files
                    const imgExt = fp.split('.').pop().toLowerCase();
                    const inlineImageExts = new Set(['png','jpg','jpeg','gif','svg','webp','bmp','ico']);
                    if (inlineImageExts.has(imgExt)) {
                        const imgUrl = `${this.apiClient.serverUrl}/files/image/${encodeURIComponent(fp)}`;
                        const basename = fp.split('/').pop().split('\\').pop();
                        const inlineImgMd = `\n\n![${basename}](${imgUrl})\n`;
                        fullContent += inlineImgMd;
                        // Keep a separate copy so stream_end can re-append it (stream_end
                        // overwrites fullContent with the server's text-only response).
                        this._streamInlineImages = (this._streamInlineImages || '') + inlineImgMd;
                        contentEl.innerHTML = this.renderMarkdown(fullContent);
                        // Click inline image → zoom overlay (lightbox)
                        const img = contentEl.querySelector(`img[src="${imgUrl}"]`);
                        if (img) {
                            img.title = 'Click to zoom';
                            img.addEventListener('click', () => this._showImageOverlay(imgUrl, basename));
                        }
                        this.scrollToBottom();
                    } else {
                        // Non-image files → open in RightPanelFrame
                        this.displayFileFromEvent(fp);
                    }
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

        if (this.state.currentAbortController) {
            this.state.currentAbortController.abort();
        }
    }

    // === Slash Commands ===

    async handleSlashCommand(input) {
        await this.commandDispatcher.dispatch(input);
    }

    async handleShowCommand(args) {
        await this.commandDispatcher.handleShowCommand(args);
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

        // v1.16.2: Virtual scroll — trim oldest message when DOM cap is exceeded
        this._domMessageCount++;
        const MAX_DOM_MESSAGES = 150;
        if (this._domMessageCount > MAX_DOM_MESSAGES) {
            const oldest = this.elements.messagesContainer.querySelector('.message');
            if (oldest) {
                // Batch read then write to avoid layout thrashing
                const spacerH = this._scrollSpacer.offsetHeight;
                const oldestH = oldest.offsetHeight;
                oldest.remove();
                this._scrollSpacer.style.height = (spacerH + oldestH) + 'px';
                this._domMessageCount--;
            }
        }

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

    showSystemMessage(content, level = 'info') {
        this.addMessage('system', content);
        // Forward to server debug log (fire-and-forget)
        fetch(`${this.serverUrl}/client-log`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ level, message: content, client: 'web' }),
        }).catch(() => {});
    }

    showError(message) {
        const msgEl = document.createElement('div');
        msgEl.className = 'message error-message';
        msgEl.innerHTML = `
            <div class="message-content">${escapeHtml(message)}</div>
        `;
        this.elements.messagesContainer.appendChild(msgEl);
        this.scrollToBottom();
        // Forward to server debug log
        fetch(`${this.serverUrl}/client-log`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ level: 'error', message, client: 'web' }),
        }).catch(() => {});
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
        if (this.state.currentAssistantMessage) {
            this.elements.messagesContainer.insertBefore(groupEl, this.state.currentAssistantMessage);
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

        if (this.state.toolsVerbose && data.arguments) {
            content += `<div class="tool-details">
                <pre>${escapeHtml(typeof data.arguments === 'string' ? data.arguments : JSON.stringify(data.arguments, null, 2))}</pre>
            </div>`;
        }

        msgEl.innerHTML = content;

        // v1.16.0: Append inside tool group if active, otherwise insert before assistant message
        if (this._currentToolGroup) {
            this._currentToolGroup.querySelector('.tool-group-body').appendChild(msgEl);
        } else if (this.state.currentAssistantMessage) {
            this.elements.messagesContainer.insertBefore(msgEl, this.state.currentAssistantMessage);
        } else {
            this.elements.messagesContainer.appendChild(msgEl);
        }
        this.scrollToBottom();
    }

    showToolResult(data) {
        // display_file results are already handled inline (image in chat bubble or
        // file opened in RightPanelFrame) — no separate tool result bubble needed.
        if (data && data.tool === 'display_file') return;

        const msgEl = document.createElement('div');
        msgEl.className = 'message tool-message tool-result';

        let content = `<div class="tool-header" onclick="this.parentElement.classList.toggle('expanded')">
            <span class="tool-icon">📋</span>
            <span class="tool-name">${escapeHtml(data.tool || 'Result')}</span>
            <span class="tool-expand">▶</span>
        </div>`;

        if (this.state.toolsVerbose && data.result) {
            const result = typeof data.result === 'string' ? data.result : JSON.stringify(data.result, null, 2);
            content += `<div class="tool-details">
                <pre>${escapeHtml(result.slice(0, 2000))}${result.length > 2000 ? '\n...(truncated)' : ''}</pre>
            </div>`;
        }

        msgEl.innerHTML = content;

        // v1.16.0: Append inside tool group if active
        if (this._currentToolGroup) {
            this._currentToolGroup.querySelector('.tool-group-body').appendChild(msgEl);
        } else if (this.state.currentAssistantMessage) {
            this.elements.messagesContainer.insertBefore(msgEl, this.state.currentAssistantMessage);
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
        if (this.state.currentAssistantMessage) {
            this.elements.messagesContainer.insertBefore(msgEl, this.state.currentAssistantMessage);
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
            await this.apiClient.submitConsent(filePath, response);
        } catch (error) {
            this.showError(`Failed to send consent: ${error.message}`);
        }
    }

    async sendShellConsent(command, workingDir, response) {
        try {
            await this.apiClient.submitShellConsent(command, workingDir, response);
        } catch (error) {
            this.showError(`Failed to send consent: ${error.message}`);
        }
    }

    // === Autocomplete ===

    handleInputKeydown(e) {
        // Handle autocomplete navigation
        if (this.state.autocompleteVisible) {
            if (e.key === 'ArrowDown') {
                e.preventDefault();
                this.state.autocompleteIndex = Math.min(this.state.autocompleteIndex + 1, this.state.autocompleteItems.length - 1);
                this.renderAutocomplete();
                return;
            } else if (e.key === 'ArrowUp') {
                e.preventDefault();
                this.state.autocompleteIndex = Math.max(this.state.autocompleteIndex - 1, 0);
                this.renderAutocomplete();
                return;
            } else if (e.key === 'Tab' || e.key === 'Enter') {
                if (this.state.autocompleteItems.length > 0) {
                    e.preventDefault();
                    this.selectAutocompleteItem(this.state.autocompleteIndex);
                    return;
                }
            } else if (e.key === 'Escape') {
                this.hideAutocomplete();
                return;
            }
        }

        // Command history
        if (e.key === 'ArrowUp' && !this.state.autocompleteVisible) {
            if (this.elements.messageInput.selectionStart === 0) {
                e.preventDefault();
                if (this.state.historyIndex < this.state.commandHistory.length - 1) {
                    this.state.historyIndex++;
                    this.elements.messageInput.value = this.state.commandHistory[this.state.historyIndex];
                }
            }
        } else if (e.key === 'ArrowDown' && !this.state.autocompleteVisible) {
            if (this.elements.messageInput.selectionStart === this.elements.messageInput.value.length) {
                e.preventDefault();
                if (this.state.historyIndex > 0) {
                    this.state.historyIndex--;
                    this.elements.messageInput.value = this.state.commandHistory[this.state.historyIndex];
                } else if (this.state.historyIndex === 0) {
                    this.state.historyIndex = -1;
                    this.elements.messageInput.value = '';
                }
            }
        }

        // Send on Enter (but allow Shift+Enter for newlines)
        if (e.key === 'Enter' && !e.shiftKey && !this.state.autocompleteVisible) {
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
            this.state.autocompleteItems = Object.keys(this.slashCommands)
                .filter(cmd => cmd.startsWith(query))
                .map(cmd => ({
                    label: cmd,
                    description: this.slashCommands[cmd].description,
                    value: cmd
                }));
            this.state.autocompleteType = 'command';
            this.state.autocompleteIndex = 0;
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
        this.state.autocompleteType = 'file';
        const fallback = [
            { label: '@git', description: 'Include git diff', value: '@git' },
            { label: '@tree', description: 'Include project structure', value: '@tree' },
        ];

        try {
            const data = await this.apiClient.searchFiles(query || '', 20);
            this.state.autocompleteItems = data.files.map(file => ({
                label: file.name.startsWith('@') ? file.name : `@${file.name}`,
                description: file.path,
                value: file.name.startsWith('@') ? file.name : `@${file.name}`
            }));
        } catch (error) {
            // Fallback to special refs on error
            this.state.autocompleteItems = query
                ? fallback.filter(item => item.label.toLowerCase().includes(query.toLowerCase()))
                : fallback;
        }

        this.state.autocompleteIndex = 0;
        // v1.13.8: Don't show if input was cleared (message sent during async request)
        if (!this.elements.messageInput.value.includes('@')) {
            return;
        }
        this.showAutocomplete();
    }

    showAutocomplete() {
        if (this.state.autocompleteItems.length === 0) {
            this.hideAutocomplete();
            return;
        }

        this.state.autocompleteVisible = true;
        this.renderAutocomplete();
        this.elements.autocompleteDropdown.classList.remove('hidden');
    }

    hideAutocomplete() {
        this.state.autocompleteVisible = false;
        this.elements.autocompleteDropdown.classList.add('hidden');
    }

    renderAutocomplete() {
        this.elements.autocompleteDropdown.innerHTML = this.state.autocompleteItems.map((item, i) => `
            <div class="autocomplete-item ${i === this.state.autocompleteIndex ? 'selected' : ''}"
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
        const item = this.state.autocompleteItems[index];
        if (!item) return;

        const input = this.elements.messageInput;
        const value = input.value;

        if (this.state.autocompleteType === 'command') {
            input.value = item.value + ' ';
        } else if (this.state.autocompleteType === 'file') {
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
            await this.apiClient.clearSession();
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
            // Re-prepend spacer (lost when innerHTML was replaced) and reset counter
            this._scrollSpacer.style.height = '0';
            this.elements.messagesContainer.prepend(this._scrollSpacer);
            this._domMessageCount = 0;
            // Quick command handlers use event delegation, no need to re-attach
            this.showSystemMessage('Conversation cleared');
        } catch (error) {
            this.showError(`Failed to clear: ${error.message}`);
        }
    }

    async saveSession(name) {
        try {
            const data = await this.apiClient.post('/sessions/save', name ? { name } : {});
            this.showSystemMessage(`Session saved: ${data.name}`);
        } catch (error) {
            this.showError(`Failed to save session: ${error.message}`);
        }
    }

    async exportAnswer(filename) {
        try {
            const data = await this.apiClient.post('/export', filename ? { filename } : {});
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
            const data = await this.apiClient.loadSession(name.trim());
            this.showSystemMessage(`Session loaded: ${data.name}`);
            // Refresh model/provider status after loading
            await this.loadInitialState();
        } catch (error) {
            this.showError(`Failed to load session: ${error.message}`);
        }
    }

    async listSessions() {
        try {
            const data = await this.apiClient.getSessions();

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

    /**
     * Handle /edit command - open file in CodeMirror 6 editor (v1.14.1)
     * Syntax: /edit filepath[:line[:col]]
     * v1.16.2: Delegates to EditorController
     */
    async handleEditCommand(args) {
        // Route through RightPanelFrame (v1.16.2)
        // args format: "filepath" or "filepath:line:col"
        if (this.rightPanelFrame) {
            const parts  = (args || '').trim().split(':');
            const relPath = parts[0];
            const line    = parts.length > 1 ? parseInt(parts[1], 10) || 1 : 1;
            const col     = parts.length > 2 ? parseInt(parts[2], 10) || 1 : 1;
            this.rightPanelFrame.push(new CodeEditorView(relPath, this.state, { mode: 'edit', line, col }));
            this.elements.resizeHandle.classList.remove('hidden');
            return;
        }
        // Legacy no-op (editorController removed in v1.16.2)
    }

    // === /preview Command (v1.15.4) ===

    openHtmlPreview(filepath) {
        // Route through RightPanelFrame (v1.16.2): push an inline iframe view
        if (this.rightPanelFrame) {
            // Inline minimal BaseView subclass for live HTML preview
            const iframeView = Object.assign(Object.create(BaseView.prototype), {
                getTitle()   { return filepath.split('/').pop(); },
                getPath()    { return filepath; },
                getIcon()    { return '🌐'; },
                mount(container) {
                    const src = `${this._serverUrl}/preview/${encodeURIComponent(filepath)}?session=${encodeURIComponent(this._sessionId)}`;
                    container.innerHTML = `<iframe src="${src}" sandbox="allow-scripts allow-same-origin" style="width:100%;height:100%;border:none;background:#fff;" class="rpf-html-iframe"></iframe>`;
                },
                unmount() { if (this._container) { this._container.innerHTML = ''; this._container = null; } },
                focus()     {},
                onKeyDown() { return false; },
            });
            iframeView._serverUrl  = this.serverUrl;
            iframeView._sessionId  = this.sessionId;
            iframeView._container  = null;
            this.rightPanelFrame.push(iframeView);
            this.elements.resizeHandle.classList.remove('hidden');
            this.state.htmlPreviewActive  = true;
            this.state.htmlPreviewFilepath = filepath;
            return;
        }
        // Legacy fallback — no-op (previewPanel removed in v1.16.2)
    }

    closeHtmlPreview() {
        if (this.rightPanelFrame && this.state.htmlPreviewActive) {
            this.rightPanelFrame.pop();
        }
        this.state.htmlPreviewActive  = false;
        this.state.htmlPreviewFilepath = null;
    }

    /**
     * Display file from display_file event (v1.15.2)
     * Called when AI uses the display_file tool
     */
    async displayFileFromEvent(filepath) {
        if (!this.rightPanelFrame) return;
        // Route to the appropriate view type by extension (v1.16.2 Phase 3)
        const ext = filepath.split('.').pop().toLowerCase();
        const imageExts = new Set(['png','jpg','jpeg','gif','svg','webp','bmp','ico','tiff']);
        const dataExts  = new Set(['json','yaml','yml','toml','hcl','tf','tfvars','csv','tsv','tab']);
        const mdExts    = new Set(['md','markdown']);
        let view;
        if (imageExts.has(ext)) {
            view = new ImageFileView(filepath, this.state);
        } else if (ext === 'pdf') {
            view = new PdfFileView(filepath, this.state);
        } else if (mdExts.has(ext)) {
            view = new MarkdownFileView(filepath, this.state);
        } else if (dataExts.has(ext)) {
            view = new DataFileView(filepath, this.state);
        } else {
            view = new CodeEditorView(filepath, this.state, { mode: 'view' });
        }
        this.rightPanelFrame.push(view);
        this.elements.resizeHandle.classList.remove('hidden');
    }

    showPreviewPanel(filename, _content, _size, _lines) {
        // Route through RightPanelFrame (v1.16.2); view fetches its own data
        if (this.rightPanelFrame) {
            this.displayFileFromEvent(filename);
        }
    }

    /**
     * Show lightbox zoom overlay for inline chat images (v1.16.2).
     * Click overlay or press Escape to close.
     */
    _showImageOverlay(src, title) {
        const overlay = document.createElement('div');
        overlay.className = 'image-overlay';
        overlay.innerHTML = `
            <div class="image-overlay-title">${title}</div>
            <img src="${src}" alt="${title}" />
        `;
        const close = () => overlay.remove();
        overlay.addEventListener('click', close);
        const onKey = (e) => { if (e.key === 'Escape') { close(); document.removeEventListener('keydown', onKey); } };
        document.addEventListener('keydown', onKey);
        document.body.appendChild(overlay);
    }

    /**
     * Show image preview (v1.13.10)
     */
    showImagePreview(filename, _base64Content, _mimeType, _size) {
        // Route through RightPanelFrame (v1.16.2)
        if (this.rightPanelFrame) {
            this.rightPanelFrame.push(new ImageFileView(filename, this.state));
            this.elements.resizeHandle.classList.remove('hidden');
        }
    }

    /**
     * Show PDF preview (v1.13.10)
     */
    showPdfPreview(filename, _base64Content, _size) {
        // Route through RightPanelFrame (v1.16.2)
        if (this.rightPanelFrame) {
            this.rightPanelFrame.push(new PdfFileView(filename, this.state));
            this.elements.resizeHandle.classList.remove('hidden');
            return;
        }
        // Legacy fallback — no-op (previewPanel removed in v1.16.2)
    }

    // (renderPreviewContent, renderDataViewer, renderMarkdownPreview, renderCodePreview,
    //  togglePreviewViewMode, updateViewToggleUI, parseCSV, parseCSVLine,
    //  detectCSVDelimiter, parseStructuredData, buildTreeNode removed in v1.16.2 Phase 5 —
    //  all functionality moved to DataFileView / MarkdownFileView / CodeEditorView)

    hidePreviewPanel() {
        // Route through RightPanelFrame (v1.16.2)
        if (this.rightPanelFrame) {
            this.rightPanelFrame.hideFrame();
            this.elements.resizeHandle.classList.add('hidden');
            return;
        }
        // Legacy fallback — no-op (previewPanel removed in v1.16.2)
    }

    // === RightPanelFrame Stack Persistence (v1.16.2 Phase 4) ================

    /**
     * Persist the current open-file stack to sessionStorage.
     * Only runs when rpfPersist is true (opt-in, off by default).
     * Dirty views are skipped — they cannot be restored with their unsaved content.
     */
    _saveRpfStack() {
        if (!this.state.rpfPersist || !this.rightPanelFrame) return;
        const entries = [];
        for (const view of this.rightPanelFrame._stack) {
            const path = view.getPath();
            if (!path) continue;      // non-file views (HTML iframe) not persisted
            if (view.isDirty()) continue;  // skip views with unsaved changes
            let viewType = 'code';
            if (view instanceof MarkdownFileView) viewType = 'markdown';
            else if (view instanceof DataFileView)  viewType = 'data';
            else if (view instanceof ImageFileView) viewType = 'image';
            else if (view instanceof PdfFileView)   viewType = 'pdf';
            entries.push({ path, viewType });
        }
        try {
            sessionStorage.setItem(`ppxai-rpf-stack-${this.sessionId}`, JSON.stringify(entries));
        } catch {}
    }

    /**
     * Restore the view stack from a previous session.
     * Only runs when rpfPersist is true. Views are pushed in bottom-first order
     * so the last push (previously active view) ends up on top.
     */
    _restoreRpfStack() {
        if (!this.state.rpfPersist || !this.rightPanelFrame) return;
        let entries;
        try {
            const raw = sessionStorage.getItem(`ppxai-rpf-stack-${this.sessionId}`);
            if (!raw) return;
            entries = JSON.parse(raw);
        } catch { return; }
        if (!Array.isArray(entries) || entries.length === 0) return;

        for (const entry of entries) {
            if (!entry.path) continue;
            let view;
            switch (entry.viewType) {
                case 'markdown': view = new MarkdownFileView(entry.path, this.state); break;
                case 'data':     view = new DataFileView(entry.path, this.state);     break;
                case 'image':    view = new ImageFileView(entry.path, this.state);    break;
                case 'pdf':      view = new PdfFileView(entry.path, this.state);      break;
                default:         view = new CodeEditorView(entry.path, this.state, { mode: 'view' }); break;
            }
            this.rightPanelFrame.push(view);
        }
        if (this.rightPanelFrame.stackSize > 0) {
            this.elements.resizeHandle.classList.remove('hidden');
        }
    }

    // === File Sidebar (v1.16.2) ===

    toggleFileSidebar() {
        const sidebar = this.elements.fileSidebar;
        const btn = this.elements.sidebarToggleBtn;
        const handle = this.elements.sidebarResizeHandle;

        const isHidden = sidebar.classList.contains('hidden');
        if (isHidden) {
            sidebar.classList.remove('hidden');
            handle.classList.remove('hidden');
            btn.classList.add('active');
            // Lazy-init FileTreeComponent on first open
            if (!this._fileTree) {
                this._fileTree = new FileTreeComponent(sidebar, {
                    serverUrl: this.serverUrl,
                    getHeaders: () => this.getSessionHeaders(),
                    onFileClick: (relPath) => this.displayFileFromEvent(relPath),
                    onFileEdit:  (relPath) => {
                        if (this.rightPanelFrame) {
                            this.rightPanelFrame.push(new CodeEditorView(relPath, this.state, { mode: 'edit' }));
                            this.elements.resizeHandle.classList.remove('hidden');
                        }
                    },
                    onFileInject: (relPath) => this._injectFileRef(relPath),
                    onDirCd: (path) => this.commandDispatcher.handleCdCommand(path),
                });
            } else {
                this._fileTree.refresh();
            }
        } else {
            sidebar.classList.add('hidden');
            handle.classList.add('hidden');
            btn.classList.remove('active');
        }
    }

    _injectFileRef(relPath) {
        const input = this.elements.messageInput;
        const ref = `@file:${relPath} `;
        const pos = input.selectionStart || input.value.length;
        input.value = input.value.slice(0, pos) + ref + input.value.slice(pos);
        input.selectionStart = input.selectionEnd = pos + ref.length;
        input.focus();
        // Trigger autocomplete/resize handlers
        input.dispatchEvent(new Event('input'));
    }

    /**
     * Initialize drag-to-resize for sidebar panel
     */
    initSidebarResizeHandle() {
        const handle = this.elements.sidebarResizeHandle;
        const panel = this.elements.fileSidebar;
        if (!handle || !panel) return;

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
            const deltaX = e.clientX - startX;  // Moving right increases width
            let newWidth = startWidth + deltaX;
            newWidth = Math.max(140, Math.min(400, newWidth));
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

    /**
     * Initialize drag-to-resize for preview panel
     */
    initResizeHandle() {
        const handle = this.elements.resizeHandle;
        const panel = this.elements.rpfFrame;
        if (!handle || !panel) return;
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
            const newState = !this.state.debugLog;
            const data = await this.apiClient.setDebugLog(newState);
            this.state.debugLog = data.enabled;
            this.updateDebugIndicator();
            this.showSystemMessage(`Debug logging ${data.enabled ? 'enabled' : 'disabled'}${data.log_file ? `: ${data.log_file}` : ''}`);
        } catch (error) {
            this.showError(`Failed to toggle debug log: ${error.message}`);
        }
    }

    updateDebugIndicator() {
        this.elements.debugIndicator.className = `menu-indicator ${this.state.debugLog ? 'active' : ''}`;
    }

    // === Usage ===

    async updateUsage() {
        try {
            const data = await this.apiClient.getUsage();

            const prompt = data.prompt_tokens || 0;
            const completion = data.completion_tokens || 0;
            const cost = data.estimated_cost || 0;

            this.state.promptTokens = prompt;
            this.state.completionTokens = completion;
            this.state.totalTokens = prompt + completion;
            this.state.totalCost = cost;

            // Format badge
            const formatTokens = (n) => n >= 1000 ? `${(n/1000).toFixed(1)}K` : n;
            this.elements.usageBadge.textContent = `${formatTokens(prompt)}↓/${formatTokens(completion)}↑ $${cost.toFixed(4)}`;
            this.elements.usageBadge.title = `Prompt: ${prompt}, Completion: ${completion}, Cost: $${cost.toFixed(4)}`;
        } catch {}
    }

    // === Context Info (v1.13.9) ===

    async updateContextInfo() {
        try {
            const data = await this.apiClient.getContextInfo();

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
            const data = await this.apiClient.clearContextInjections();

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
        if (this.state.theme === 'system') {
            const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
            document.body.dataset.theme = prefersDark ? 'dark' : 'light';
        } else {
            document.body.dataset.theme = this.state.theme;
        }

        this.elements.themeBtn.textContent = this.state.theme === 'dark' ? '🌙' : '☀️';
        this.elements.themeSetting.value = this.state.theme;
    }

    cycleTheme() {
        const themes = ['dark', 'light'];
        const currentIndex = themes.indexOf(this.state.theme);
        this.state.theme = themes[(currentIndex + 1) % themes.length];
        this.applyTheme();
        localStorage.setItem('ppxai-theme', this.state.theme);
    }

    // === Settings ===

    showSettings() {
        this.elements.serverUrlSetting.value = this.serverUrl;
        this.elements.themeSetting.value = this.state.theme;
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
        if (this._scrollRafPending) return;
        this._scrollRafPending = true;
        requestAnimationFrame(() => {
            this.elements.messagesContainer.scrollTop = this.elements.messagesContainer.scrollHeight;
            this._scrollRafPending = false;
        });
    }
}

// ── RightPanelFrame helpers ───────────────────────────────────────────────────

/**
 * HTML-escape helper used in rpf dropdown template literals.
 * @param {*} str
 * @returns {string}
 */
function _rpfEsc(str) {
    return String(str ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

// Initialize app when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    window.ppxai = new PpxaiApp();
});
