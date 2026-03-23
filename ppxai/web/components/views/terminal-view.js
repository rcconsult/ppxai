/**
 * TerminalView — xterm.js terminal in the right panel (v1.17.1).
 *
 * Opens a WebSocket to /ws/terminal, spawns a PTY shell on the server,
 * and renders the output via xterm.js.
 */
class TerminalView extends BaseView {
    constructor(serverUrl, sessionId) {
        super();
        this._serverUrl = serverUrl;
        this._sessionId = sessionId;
        this._terminal = null;
        this._fitAddon = null;
        this._websocket = null;
        this._container = null;
        this._resizeObserver = null;
        this._reconnectTimer = null;
        this._instanceId = Date.now();  // Unique ID so multiple terminals aren't deduplicated
    }

    getTitle()   { return '💻 Terminal'; }
    getPath()    { return `__terminal__/${this._instanceId}`; }
    getIcon()    { return '💻'; }

    mount(container) {
        this._container = container;
        container.innerHTML = '';
        container.style.padding = '0';
        container.style.overflow = 'hidden';

        // Create terminal container
        const termEl = document.createElement('div');
        termEl.style.cssText = 'width:100%;height:100%;';
        container.appendChild(termEl);

        // Initialize xterm.js
        this._terminal = new window.Terminal({
            fontSize: 13,
            fontFamily: "'JetBrains Mono', 'Fira Code', 'Cascadia Code', Menlo, monospace",
            theme: this._getTheme(),
            cursorBlink: true,
            scrollback: 5000,
            convertEol: true,
        });

        // Fit addon — auto-resize to container
        if (window.FitAddon) {
            this._fitAddon = new window.FitAddon.FitAddon();
            this._terminal.loadAddon(this._fitAddon);
        }

        this._terminal.open(termEl);

        // Initial fit
        if (this._fitAddon) {
            try { this._fitAddon.fit(); } catch {}
        }

        // Observe container resize
        this._resizeObserver = new ResizeObserver(() => {
            if (this._fitAddon) {
                try { this._fitAddon.fit(); } catch {}
            }
        });
        this._resizeObserver.observe(container);

        // Connect WebSocket
        this._connect();

        // Send user input to server
        this._terminal.onData(data => {
            if (this._websocket && this._websocket.readyState === WebSocket.OPEN) {
                this._websocket.send(JSON.stringify({ type: 'input', data }));
            }
        });

        // Send resize events
        this._terminal.onResize(({ cols, rows }) => {
            if (this._websocket && this._websocket.readyState === WebSocket.OPEN) {
                this._websocket.send(JSON.stringify({ type: 'resize', cols, rows }));
            }
        });
    }

    _connect() {
        const protocol = this._serverUrl.startsWith('https') ? 'wss:' : 'ws:';
        const host = this._serverUrl.replace(/^https?:\/\//, '');
        const url = `${protocol}//${host}/ws/terminal?session=${encodeURIComponent(this._sessionId)}`;

        this._websocket = new WebSocket(url);

        this._websocket.onopen = () => {
            // Send initial size
            if (this._terminal && this._fitAddon) {
                try { this._fitAddon.fit(); } catch {}
                const { cols, rows } = this._terminal;
                this._websocket.send(JSON.stringify({ type: 'resize', cols, rows }));
            }
        };

        this._websocket.onmessage = (event) => {
            try {
                const msg = JSON.parse(event.data);
                if (msg.type === 'output') {
                    this._terminal.write(msg.data);
                } else if (msg.type === 'exit') {
                    this._terminal.writeln(`\r\n[Process exited with code ${msg.code}]`);
                } else if (msg.type === 'error') {
                    this._terminal.writeln(`\r\n[Error: ${msg.data}]`);
                }
            } catch {
                // Raw data fallback
                this._terminal.write(event.data);
            }
        };

        this._websocket.onclose = () => {
            if (this._terminal && this._container) {
                this._terminal.writeln('\r\n[Connection closed]');
            }
        };

        this._websocket.onerror = () => {
            if (this._terminal) {
                this._terminal.writeln('\r\n[WebSocket error]');
            }
        };
    }

    unmount() {
        if (this._reconnectTimer) {
            clearTimeout(this._reconnectTimer);
            this._reconnectTimer = null;
        }
        if (this._resizeObserver) {
            this._resizeObserver.disconnect();
            this._resizeObserver = null;
        }
        if (this._websocket) {
            this._websocket.close();
            this._websocket = null;
        }
        if (this._terminal) {
            this._terminal.dispose();
            this._terminal = null;
        }
        this._fitAddon = null;
        if (this._container) {
            this._container.innerHTML = '';
            this._container = null;
        }
    }

    focus() {
        if (this._terminal) {
            this._terminal.focus();
        }
    }

    onKeyDown() {
        // Terminal handles all keys internally via xterm.js
        return true;
    }

    onActivate() {
        // Re-fit when tab becomes active (container may have resized)
        if (this._fitAddon) {
            setTimeout(() => {
                try { this._fitAddon.fit(); } catch {}
            }, 50);
        }
        this.focus();
    }

    _getTheme() {
        // Match ppxai's dark theme
        return {
            background: '#1a1a2e',
            foreground: '#e0e0e0',
            cursor: '#ff0055',
            cursorAccent: '#1a1a2e',
            selectionBackground: 'rgba(255, 0, 85, 0.3)',
            black: '#1a1a2e',
            red: '#ff0055',
            green: '#00ff88',
            yellow: '#ffcc00',
            blue: '#0088ff',
            magenta: '#cc44ff',
            cyan: '#00cccc',
            white: '#e0e0e0',
            brightBlack: '#555555',
            brightRed: '#ff3377',
            brightGreen: '#33ffaa',
            brightYellow: '#ffdd33',
            brightBlue: '#33aaff',
            brightMagenta: '#dd66ff',
            brightCyan: '#33dddd',
            brightWhite: '#ffffff',
        };
    }
}

// Browser global export
if (typeof window !== 'undefined') {
    window.TerminalView = TerminalView;
}
