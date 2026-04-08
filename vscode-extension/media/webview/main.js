const vscode = acquireVsCodeApi();
const messagesContainer = document.getElementById('messages');
let typingIndicator = document.getElementById('typingIndicator');
const messageInput = document.getElementById('messageInput');
const sendBtn = document.getElementById('sendBtn');
const providerSpan = document.getElementById('provider');
const modelSpan = document.getElementById('model');
const serverBadge = document.getElementById('serverBadge');
const serverStatus = document.getElementById('serverStatus');
const toolsBadge = document.getElementById('toolsBadge');
const streamingBadge = document.getElementById('streamingBadge');
const usageBadge = document.getElementById('usageBadge');
const contextBadge = document.getElementById('contextBadge');
const contextUsage = document.getElementById('contextUsage');
const clearBtn = document.getElementById('clearBtn');
const menuBtn = document.getElementById('menuBtn');
const menuDropdown = document.getElementById('menuDropdown');
const saveSessionMenuItem = document.getElementById('saveSessionMenuItem');
const saveAnswerMenuItem = document.getElementById('saveAnswerMenuItem');
const verboseToolsMenuItem = document.getElementById('verboseToolsMenuItem');
const verboseToolsIndicator = document.getElementById('verboseToolsIndicator');
const debugLogMenuItem = document.getElementById('debugLogMenuItem');
const debugLogIndicator = document.getElementById('debugLogIndicator');
const hintsBadge = document.getElementById('hintsBadge');
const hintsStatus = document.getElementById('hintsStatus');

let currentResponseEl = null;
let currentResponseContent = '';
let lastAssistantMessage = '';  // Track last assistant response
let renderPending = false;
let lastRenderTime = 0;
let responseStartTime = 0; // Track when response started
const RENDER_THROTTLE_MS = 100; // Render at most every 100ms during streaming
const MAX_HIGHLIGHT_SIZE = 10000; // Skip syntax highlighting for code blocks > 10KB

// Command history
const commandHistory = [];
const MAX_HISTORY = 100;
let historyIndex = -1;
let currentInput = '';

// Time divider tracking
let lastMessageTime = null;
const TIME_GAP_THRESHOLD_MS = 5 * 60 * 1000; // 5 minutes - show divider after this gap

// Autocomplete state
const autocompleteDropdown = document.getElementById('autocompleteDropdown');
let autocompleteItems = [];
let autocompleteSelectedIndex = -1;
let autocompleteMode = null; // 'file', 'command', or null
let autocompleteQuery = '';
let autocompleteStartPos = 0;
let autocompleteDisabled = false; // Disabled for special providers (@git, @tree)

// v1.17.4: Slash commands now fetched dynamically from server via POST /complete.
// No hardcoded list needed — CommandFactory is the single source of truth.

// Configure marked for GFM
// Check if marked library loaded
let parseMarkdown;
if (typeof marked !== 'undefined' && typeof marked.parse === 'function') {
    marked.setOptions({
        breaks: true,
        gfm: true
    });
    // Wrap marked.parse to pre-process backtick-wrapped URLs and markdown code blocks
    parseMarkdown = function(text) {
        if (!text) return '';

        // BUGFIX: Unwrap markdown code blocks BEFORE marked processes them
        // Some models (Gemini 2.0 Flash, Gemini 3 Pro) wrap output in triple-backtick markdown blocks
        // which would cause syntax highlighting instead of rendering
        // Simply extract the content and let marked parse it normally
        // Use \x60 hex escape for backticks to avoid template literal parsing issues
        text = text.replace(/\x60\x60\x60(?:markdown|md)\s*\n([\s\S]*?)\x60\x60\x60/g, '$1');

        // Convert backtick-wrapped URLs to links BEFORE marked processes them
        text = text.replace(/\x60(https?:\/\/[^\x60]+)\x60/g, '<a href="$1" target="_blank" rel="noopener" class="url-link">$1</a>');

        // Parse with marked
        return marked.parse(text);
    };
    console.log('Marked library loaded successfully');
} else {
    console.error('Marked library not loaded! typeof marked =', typeof marked);
    // Fallback: basic markdown parsing
    parseMarkdown = function(text) {
        if (!text) return '';
        // Code blocks first (before escaping HTML)
        text = text.replace(/\`\`\`(\w*)\n([\s\S]*?)\`\`\`/g, function(m, lang, code) {
            code = code.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
            return '<pre><code class="' + lang + '">' + code + '</code></pre>';
        });
        // Inline code - but convert URL-only code to links instead
        text = text.replace(/\`(https?:\/\/[^\`]+)\`/g, '<a href="$1" target="_blank" rel="noopener" class="url-link">$1</a>');
        text = text.replace(/\`([^\`]+)\`/g, function(m, code) {
            code = code.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
            return '<code>' + code + '</code>';
        });
        // Escape remaining HTML
        text = text.replace(/&(?!amp;|lt;|gt;)/g, '&amp;');
        text = text.replace(/<(?!\/?(pre|code|h[1-6]|strong|em|ul|ol|li|p|blockquote)[ >])/g, '&lt;');
        // Headers
        text = text.replace(/^###### (.+)$/gm, '<h6>$1</h6>');
        text = text.replace(/^##### (.+)$/gm, '<h5>$1</h5>');
        text = text.replace(/^#### (.+)$/gm, '<h4>$1</h4>');
        text = text.replace(/^### (.+)$/gm, '<h3>$1</h3>');
        text = text.replace(/^## (.+)$/gm, '<h2>$1</h2>');
        text = text.replace(/^# (.+)$/gm, '<h1>$1</h1>');
        // Bold
        text = text.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
        // Italic
        text = text.replace(/\*([^*]+)\*/g, '<em>$1</em>');
        // Links [text](url)
        text = text.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
        // Bare URLs (http/https) - convert to clickable links
        text = text.replace(/(^|[^"'>])(https?:\/\/[^\s<)\]]+)/g, '$1<a href="$2" target="_blank" rel="noopener">$2</a>');
        // Lists
        text = text.replace(/^- (.+)$/gm, '<li>$1</li>');
        text = text.replace(/(<li>.*<\/li>\n?)+/g, '<ul>$&</ul>');
        // Paragraphs
        var lines = text.split('\n');
        text = lines.map(function(line) {
            if (line.trim() === '' || line.match(/^<(pre|h[1-6]|ul|ol|li|blockquote)/)) return line;
            if (!line.match(/^<[a-z]/)) return '<p>' + line + '</p>';
            return line;
        }).join('\n');
        return text;
    };
}

// Throttled render function for streaming
function scheduleRender() {
    if (renderPending) return;

    const now = Date.now();
    const timeSinceLastRender = now - lastRenderTime;

    if (timeSinceLastRender >= RENDER_THROTTLE_MS) {
        // Render immediately
        doRender();
    } else {
        // Schedule render
        renderPending = true;
        setTimeout(() => {
            renderPending = false;
            doRender();
        }, RENDER_THROTTLE_MS - timeSinceLastRender);
    }
}

function doRender() {
    if (!currentResponseEl || !currentResponseContent) return;
    lastRenderTime = Date.now();
    // Use simple escaping during streaming for speed
    const contentEl = currentResponseEl.querySelector('.message-content') || currentResponseEl;
    contentEl.innerHTML = simpleFormat(currentResponseContent);
    scrollToBottom();
}

// Simple formatting for streaming (fast)
function simpleFormat(text) {
    if (!text) return '';
    // Escape HTML
    text = text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    // Basic code blocks
    text = text.replace(/\`\`\`(\w*)\n([\s\S]*?)\`\`\`/g, '<pre><code>$2</code></pre>');
    // Inline code - but convert URL-only code to links instead
    text = text.replace(/\`(https?:\/\/[^\`]+)\`/g, '<a href="$1" target="_blank" rel="noopener" class="url-link">$1</a>');
    text = text.replace(/\`([^\`]+)\`/g, '<code>$1</code>');
    // Bold
    text = text.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
    // Headers (basic support during streaming)
    text = text.replace(/^### (.+)$/gm, '<h3>$1</h3>');
    text = text.replace(/^## (.+)$/gm, '<h2>$1</h2>');
    text = text.replace(/^# (.+)$/gm, '<h1>$1</h1>');
    // Links [text](url)
    text = text.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
    // Bare URLs (convert https://... to clickable links)
    text = text.replace(/(^|[^"'>])(https?:\/\/[^\s<)\]]+)/g, '$1<a href="$2" target="_blank" rel="noopener">$2</a>');
    // Line breaks
    text = text.replace(/\n/g, '<br>');
    return text;
}

// Full markdown render (at end of streaming)
function fullRender(showTime = false) {
    if (!currentResponseEl || !currentResponseContent) return;
    const contentEl = currentResponseEl.querySelector('.message-content') || currentResponseEl;
    try {
        contentEl.innerHTML = parseMarkdown(currentResponseContent);
        // parseMarkdown() already unwraps markdown code blocks before parsing
        // Just apply syntax highlighting to code blocks
        contentEl.querySelectorAll('pre code').forEach((block) => {
            if (block.textContent.length <= MAX_HIGHLIGHT_SIZE) {
                hljs.highlightElement(block);
            }
        });
        // Add response time if requested
        if (showTime && responseStartTime > 0) {
            const elapsed = ((Date.now() - responseStartTime) / 1000).toFixed(1);
            const timeEl = document.createElement('div');
            timeEl.className = 'response-time';
            timeEl.textContent = elapsed + 's';
            contentEl.appendChild(timeEl);
        }
    } catch (e) {
        console.error('Full render error:', e);
        contentEl.innerHTML = simpleFormat(currentResponseContent);
    }
    scrollToBottom();
}

// Autocomplete functions
function showAutocomplete(items, mode) {
    autocompleteItems = items;
    autocompleteMode = mode;
    autocompleteSelectedIndex = items.length > 0 ? 0 : -1;
    renderAutocomplete();
}

function hideAutocomplete() {
    autocompleteDropdown.classList.remove('visible');
    autocompleteItems = [];
    autocompleteMode = null;
    autocompleteSelectedIndex = -1;
}

function renderAutocomplete() {
    if (autocompleteItems.length === 0) {
        hideAutocomplete();
        return;
    }

    const headers = { file: 'Files', command: 'Commands', path: 'Path' };
    const header = headers[autocompleteMode] || 'Suggestions';
    let html = '<div class="autocomplete-header">' + header + '</div>';

    autocompleteItems.forEach((item, index) => {
        const selectedClass = index === autocompleteSelectedIndex ? ' selected' : '';
        if (autocompleteMode === 'file') {
            html += '<div class="autocomplete-item' + selectedClass + '" data-index="' + index + '">' +
                '<span class="icon">📄</span>' +
                '<span class="name">' + item.name + '</span>' +
                '<span class="path">' + (item.path || '') + '</span>' +
            '</div>';
        } else {
            const icon = (item.kind === 'dir') ? '📁' : (item.kind === 'file') ? '📄' : '⌘';
            html += '<div class="autocomplete-item' + selectedClass + '" data-index="' + index + '">' +
                '<span class="icon">' + icon + '</span>' +
                '<span class="name">' + item.name + '</span>' +
                '<span class="description">' + (item.description || '') + '</span>' +
            '</div>';
        }
    });

    autocompleteDropdown.innerHTML = html;
    autocompleteDropdown.classList.add('visible');

    // Add click handlers
    autocompleteDropdown.querySelectorAll('.autocomplete-item').forEach(el => {
        el.addEventListener('click', () => {
            const idx = parseInt(el.dataset.index);
            selectAutocompleteItem(idx);
        });
    });
}

function selectAutocompleteItem(index) {
    if (index < 0 || index >= autocompleteItems.length) return;

    const item = autocompleteItems[index];
    const value = messageInput.value;
    const cursorPos = messageInput.selectionStart;

    if (autocompleteMode === 'file') {
        // @file mode — replace from autocompleteStartPos
        const beforeTrigger = value.substring(0, autocompleteStartPos);
        const afterCursor = value.substring(cursorPos);
        // v1.13.8: Don't add @ prefix if name already has it (e.g., @git, @tree)
        const insertText = item.name.startsWith('@') ? item.name : '@' + item.name;
        messageInput.value = beforeTrigger + insertText + ' ' + afterCursor;
        const newPos = beforeTrigger.length + insertText.length + 1;
        messageInput.setSelectionRange(newPos, newPos);
    } else if (item.replace_start !== undefined && item.replace_start < 0) {
        // v1.17.4: Server completion with replace_start (negative offset from cursor)
        const replaceFrom = cursorPos + item.replace_start;
        const before = value.substring(0, replaceFrom);
        const afterCursor = value.substring(cursorPos);
        const text = item.text || item.name;
        // For directories, don't add trailing space (user continues typing path)
        const suffix = item.kind === 'dir' ? '' : ' ';
        messageInput.value = before + text + suffix + afterCursor;
        const newPos = before.length + text.length + suffix.length;
        messageInput.setSelectionRange(newPos, newPos);
        // If a directory was selected, trigger another completion round
        if (item.kind === 'dir') {
            setTimeout(() => checkAutocomplete(), 50);
        }
    } else {
        // Legacy fallback — replace from start
        const insertText = item.text || item.name;
        messageInput.value = insertText + ' ';
        const newPos = insertText.length + 1;
        messageInput.setSelectionRange(newPos, newPos);
    }

    hideAutocomplete();
    messageInput.focus();
}

function handleAutocompleteNavigation(e) {
    if (!autocompleteDropdown.classList.contains('visible')) return false;

    if (e.key === 'ArrowDown') {
        e.preventDefault();
        autocompleteSelectedIndex = Math.min(autocompleteSelectedIndex + 1, autocompleteItems.length - 1);
        renderAutocomplete();
        return true;
    } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        autocompleteSelectedIndex = Math.max(autocompleteSelectedIndex - 1, 0);
        renderAutocomplete();
        return true;
    } else if (e.key === 'Enter' || e.key === 'Tab') {
        e.preventDefault();
        selectAutocompleteItem(autocompleteSelectedIndex);
        return true;
    } else if (e.key === 'Escape') {
        e.preventDefault();
        hideAutocomplete();
        return true;
    }
    return false;
}

// v1.17.4: Request ID to discard stale completion responses
let _completeRequestId = 0;

function checkAutocomplete() {
    const value = messageInput.value;
    const cursorPos = messageInput.selectionStart;
    const textBeforeCursor = value.substring(0, cursorPos);

    // Check for @ file reference
    const atMatch = textBeforeCursor.match(/@([\w.\-\/]*)$/);
    if (atMatch) {
        autocompleteStartPos = cursorPos - atMatch[0].length;
        autocompleteQuery = atMatch[1];
        autocompleteDisabled = false;
        // v1.13.8: Request file suggestions (now includes @git, @tree)
        vscode.postMessage({ type: 'searchFiles', query: autocompleteQuery || '' });
        return;
    }

    // Check for / command or /command <path-arg> — delegate to server
    const cmdMatch = textBeforeCursor.match(/^(\/[\w]*.*)$/);
    if (cmdMatch) {
        autocompleteStartPos = 0;
        autocompleteQuery = cmdMatch[1];
        _completeRequestId++;
        vscode.postMessage({
            type: 'complete',
            buffer: textBeforeCursor,
            cursor: cursorPos,
            requestId: _completeRequestId
        });
        return;
    }

    // No autocomplete trigger found
    hideAutocomplete();
}

// Auto-resize textarea
messageInput.addEventListener('input', () => {
    messageInput.style.height = 'auto';
    messageInput.style.height = Math.min(messageInput.scrollHeight, 120) + 'px';
    // Check for autocomplete triggers
    checkAutocomplete();
});

// v1.13.2: Flag-based input control (matches web app pattern)
// This prevents out-of-order messages while keeping input focused
let isStreaming = false;
let isSending = false;

// === File attachment staging (v1.17.4 Phase 6.1) ===
let pendingFiles = [];

const attachBtn = document.getElementById('attachBtn');
const fileInput = document.getElementById('fileInput');
const attachmentBadgesEl = document.getElementById('attachmentBadges');

if (attachBtn && fileInput) {
    attachBtn.addEventListener('click', () => fileInput.click());
    fileInput.addEventListener('change', () => {
        for (const file of fileInput.files) {
            stageFile(file);
        }
        fileInput.value = '';
    });
}

// Drag-drop on the input container + body-level overlay
const inputContainer = document.querySelector('.input-container');
let bodyDragCounter = 0;

document.addEventListener('dragenter', (e) => {
    e.preventDefault();
    bodyDragCounter++;
    if (bodyDragCounter === 1) showDragOverlay();
});
document.addEventListener('dragover', (e) => e.preventDefault());
document.addEventListener('dragleave', () => {
    bodyDragCounter--;
    if (bodyDragCounter <= 0) { bodyDragCounter = 0; hideDragOverlay(); }
});
document.addEventListener('drop', (e) => {
    e.preventDefault();
    bodyDragCounter = 0;
    hideDragOverlay();
    if (e.dataTransfer.files.length > 0) {
        for (const file of e.dataTransfer.files) {
            stageFile(file);
        }
    }
});

function showDragOverlay() {
    if (document.getElementById('drag-overlay')) return;
    const overlay = document.createElement('div');
    overlay.id = 'drag-overlay';
    overlay.className = 'drag-overlay';
    overlay.innerHTML = '<div class="drag-overlay-text">\u{1F4CE} Drop files to attach</div>';
    document.body.appendChild(overlay);
}
function hideDragOverlay() {
    const overlay = document.getElementById('drag-overlay');
    if (overlay) overlay.remove();
}

function stageFile(file) {
    if (file.size > 10 * 1024 * 1024) {
        addMessage('system', `❌ ${file.name} exceeds the 10 MB limit.`);
        return;
    }
    const reader = new FileReader();
    reader.onload = () => {
        const b64 = reader.result.split(',')[1] || '';
        pendingFiles.push({
            name: file.name,
            media_type: file.type || 'application/octet-stream',
            data: b64,
            size: file.size,
        });
        renderPendingBadges();
    };
    reader.readAsDataURL(file);
}

function renderPendingBadges() {
    if (!attachmentBadgesEl) return;
    if (pendingFiles.length === 0) {
        attachmentBadgesEl.classList.add('hidden');
        attachmentBadgesEl.innerHTML = '';
        return;
    }
    attachmentBadgesEl.classList.remove('hidden');
    attachmentBadgesEl.innerHTML = pendingFiles.map((f, i) => {
        const isImage = f.media_type.startsWith('image/');
        const thumb = isImage
            ? `<img class="badge-thumb" src="data:${f.media_type};base64,${f.data}" alt="${f.name}">`
            : `<span class="badge-icon">\u{1F4C4}</span>`;
        const sizeKB = (f.size / 1024).toFixed(1);
        const shortName = f.name.length > 25 ? f.name.slice(0, 22) + '...' : f.name;
        return `<span class="file-badge">
            ${thumb} ${shortName} (${sizeKB} KB)
            <span class="badge-remove" onclick="removePendingFile(${i})">×</span>
        </span>`;
    }).join('');
}

function removePendingFile(index) {
    pendingFiles.splice(index, 1);
    renderPendingBadges();
}

// v1.17.4: Brief "sent" badge shown after files are submitted, before
// server pushes context_attachments via SSE state_sync.
function showSentFilesBadge(count) {
    let badge = document.getElementById('sentFilesBadge');
    if (!badge) {
        badge = document.createElement('span');
        badge.id = 'sentFilesBadge';
        badge.className = 'sent-files-badge';
        const statusRow = document.querySelector('.badge-row') || contextBadge?.parentElement;
        if (statusRow) statusRow.appendChild(badge);
    }
    badge.textContent = '\u{2705} ' + count + ' file(s) sent';
    badge.style.display = '';
    // Auto-hide after server badge appears or after timeout
    clearTimeout(badge._timer);
    badge._timer = setTimeout(() => { badge.style.display = 'none'; }, 8000);
}

// v1.17.4: Preview attached files from user message bubbles.
// Images with inline base64 data open in a lightbox overlay.
// Everything else (PDFs, Office docs, images without data) delegates
// to VSCode's native preview via the extension host.
function showAttachLightbox(file) {
    const isImage = file.media_type && file.media_type.startsWith('image/');

    // Images with inline base64 — show in webview lightbox
    if (isImage && file.data) {
        const overlay = document.createElement('div');
        overlay.className = 'attach-lightbox';
        overlay.addEventListener('click', () => overlay.remove());

        const img = document.createElement('img');
        img.src = `data:${file.media_type};base64,${file.data}`;
        img.alt = file.name;
        img.addEventListener('click', (e) => e.stopPropagation());
        overlay.appendChild(img);

        const caption = document.createElement('div');
        caption.className = 'attach-lightbox-caption';
        caption.textContent = file.name + ' — click outside to close';
        overlay.appendChild(caption);
        document.body.appendChild(overlay);

        const onKey = (e) => { if (e.key === 'Escape') { overlay.remove(); document.removeEventListener('keydown', onKey); } };
        document.addEventListener('keydown', onKey);
        return;
    }

    // All other files — delegate to VSCode native preview via extension host
    if (file.file_id) {
        vscode.postMessage({ type: 'previewFile', fileId: file.file_id, name: file.name });
    }
}

// Send message
function sendMessage() {
    const content = messageInput.value.trim();
    // v1.13.2: Use flags instead of disabled state to prevent concurrent requests
    if (!content || isStreaming || isSending) return;

    // Set sending flag immediately to prevent double-sends
    isSending = true;

    // Add to history
    if (commandHistory.length === 0 || commandHistory[commandHistory.length - 1] !== content) {
        commandHistory.push(content);
        if (commandHistory.length > MAX_HISTORY) {
            commandHistory.shift();
        }
    }
    historyIndex = -1;
    currentInput = '';

    // v1.17.4 Phase 6.1: include pending file attachments in the message
    const files = [...pendingFiles];
    pendingFiles = [];
    renderPendingBadges();

    // v1.17.4: Show brief "sent" badge so user sees confirmation before
    // server-side context_attachments badge appears via SSE state_sync
    if (files.length > 0) {
        showSentFilesBadge(files.length);
    }

    const msg = files.length > 0
        ? { type: 'chat', content, files }
        : { type: 'chat', content };
    vscode.postMessage(msg);

    messageInput.value = '';
    messageInput.style.height = 'auto';
    hideAutocomplete();
}

sendBtn.addEventListener('click', sendMessage);
messageInput.addEventListener('keydown', (e) => {
    // Check autocomplete navigation first
    if (handleAutocompleteNavigation(e)) {
        return;
    }

    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
    } else if (e.key === 'ArrowUp' && commandHistory.length > 0) {
        // Navigate to older command
        e.preventDefault();
        if (historyIndex === -1) {
            // Save current input before navigating
            currentInput = messageInput.value;
            historyIndex = commandHistory.length - 1;
        } else if (historyIndex > 0) {
            historyIndex--;
        }
        messageInput.value = commandHistory[historyIndex];
        // Move cursor to end
        messageInput.setSelectionRange(messageInput.value.length, messageInput.value.length);
    } else if (e.key === 'ArrowDown' && historyIndex !== -1) {
        // Navigate to newer command
        e.preventDefault();
        if (historyIndex < commandHistory.length - 1) {
            historyIndex++;
            messageInput.value = commandHistory[historyIndex];
        } else {
            // Back to current input
            historyIndex = -1;
            messageInput.value = currentInput;
        }
        // Move cursor to end
        messageInput.setSelectionRange(messageInput.value.length, messageInput.value.length);
    }
});

clearBtn.addEventListener('click', () => {
    vscode.postMessage({ type: 'clear' });
});

// Menu button click handler - toggle dropdown
menuBtn.addEventListener('click', (e) => {
    e.stopPropagation();
    menuDropdown.classList.toggle('visible');
});

// Close menu when clicking outside
document.addEventListener('click', (e) => {
    if (!menuBtn.contains(e.target) && !menuDropdown.contains(e.target)) {
        menuDropdown.classList.remove('visible');
    }
});

// Save Session menu item click handler
saveSessionMenuItem.addEventListener('click', () => {
    vscode.postMessage({ type: 'save' });
    menuDropdown.classList.remove('visible');
});

// Save Answer menu item click handler
saveAnswerMenuItem.addEventListener('click', () => {
    if (lastAssistantMessage) {
        vscode.postMessage({ type: 'saveAnswer', content: lastAssistantMessage });
    } else {
        vscode.postMessage({ type: 'error', message: 'No answer to save yet' });
    }
    menuDropdown.classList.remove('visible');
});

// Verbose Tools menu item click handler
verboseToolsMenuItem.addEventListener('click', () => {
    const isActive = verboseToolsIndicator.classList.contains('active');
    vscode.postMessage({ type: 'toggleVerboseTools', enable: !isActive });
    menuDropdown.classList.remove('visible');
});

// Debug Log menu item click handler
debugLogMenuItem.addEventListener('click', () => {
    const isActive = debugLogIndicator.classList.contains('active');
    vscode.postMessage({ type: 'toggleDebugLog', enable: !isActive });
    menuDropdown.classList.remove('visible');
});

// Tools badge click handler - toggle tools on/off
// Server badge click handler - toggle server on/off (v1.13.1)
serverBadge.addEventListener('click', () => {
    console.log('[ppxai webview] serverBadge clicked');
    const isConnected = serverBadge.classList.contains('connected');
    console.log(`[ppxai webview] isConnected=${isConnected}, sending toggleServer`);
    vscode.postMessage({ type: 'toggleServer', stop: isConnected });
});

// v1.17.4: Track context attachments for badge + click behavior
let _contextAttachments = [];

function updateContextAttachmentsBadge(count, attachments) {
    _contextAttachments = attachments || [];
    // Hide the transient "sent" badge once the real server-side badge arrives
    if (count > 0) {
        const sentBadge = document.getElementById('sentFilesBadge');
        if (sentBadge) sentBadge.style.display = 'none';
    }
    let badge = document.getElementById('contextAttachBadge');
    if (count > 0) {
        if (!badge) {
            badge = document.createElement('span');
            badge.id = 'contextAttachBadge';
            badge.className = 'context-attach-badge';
            badge.addEventListener('click', () => {
                // Show list of attached files, let user click to open
                if (_contextAttachments.length > 0) {
                    const names = _contextAttachments.map(a => a.name).join(', ');
                    vscode.postMessage({
                        type: 'chat',
                        content: '/context'
                    });
                }
            });
            // Insert near the context badge
            const statusRow = document.querySelector('.badge-row') || contextBadge?.parentElement;
            if (statusRow) statusRow.appendChild(badge);
        }
        badge.textContent = '\u{1F4CE} ' + count + ' in context';
        badge.title = count + ' file(s) attached — click to show details';
        badge.style.display = '';
    } else if (badge) {
        badge.style.display = 'none';
    }
}

// Function to update server status (v1.13.1)
function updateServerStatus(connected, connecting = false) {
    serverBadge.classList.remove('connected', 'disconnected', 'connecting');
    if (connecting) {
        serverBadge.classList.add('connecting');
        serverStatus.textContent = 'Connecting...';
        serverBadge.title = 'Connecting to server...';
    } else if (connected) {
        serverBadge.classList.add('connected');
        serverStatus.textContent = 'Connected';
        serverBadge.title = 'Click to stop server';
    } else {
        serverBadge.classList.add('disconnected');
        serverStatus.textContent = 'Disconnected';
        serverBadge.title = 'Click to start server';
    }
}

toolsBadge.addEventListener('click', () => {
    const isEnabled = toolsBadge.classList.contains('enabled');
    vscode.postMessage({ type: 'toggleTools', enable: !isEnabled });
});

// Agent badge click handler - toggle agent mode on/off (v1.11.8)
const agentBadge = document.getElementById('agentBadge');
agentBadge.addEventListener('click', () => {
    const isEnabled = agentBadge.classList.contains('enabled');
    vscode.postMessage({ type: 'toggleAgent', enable: !isEnabled });
});

// Undo badge click handler - undo last checkpoint (v1.12.0, v1.12.1: stale check)
const undoBadge = document.getElementById('undoBadge');
undoBadge.addEventListener('click', () => {
    // Block clicks on disabled (no checkpoint) or stale checkpoints
    if (!undoBadge.classList.contains('disabled') && !undoBadge.classList.contains('stale')) {
        vscode.postMessage({ type: 'undoCheckpoint' });
    }
});

// Streaming badge click handler - interrupt streaming
streamingBadge.addEventListener('click', () => {
    vscode.postMessage({ type: 'interrupt' });
});

// Context badge click handler - clear injected contexts (v1.13.9)
contextBadge.addEventListener('click', () => {
    vscode.postMessage({ type: 'clearContext' });
});

// Handle link clicks - open external URLs
messagesContainer.addEventListener('click', (e) => {
    // Use closest() to catch clicks on elements inside links
    const link = e.target.closest('a');
    if (link && link.href) {
        e.preventDefault();
        e.stopPropagation();
        console.log('Opening link:', link.href);
        vscode.postMessage({ type: 'openLink', url: link.href });
    }
});

// Handle Esc key - interrupt current streaming
// Inspired by Claude Code's interrupt functionality (https://claude.ai/code)
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
        e.preventDefault();
        vscode.postMessage({ type: 'interrupt' });
    }
});

// Handle messages from extension
window.addEventListener('message', (event) => {
    const message = event.data;

    switch (message.type) {
        case 'userMessage':
            addMessage('user', message.content, false, message.files);
            break;

        case 'commandMessage':
            addMessage('command', message.content, false);
            break;

        case 'systemMessage':
            addMessage('system', message.content, true);
            // v1.13.2: Reset flags after system message (e.g., /help, /status)
            isStreaming = false;
            isSending = false;
            break;

        case 'toolGroupStart':
            onToolGroupStart(message.data);
            break;

        case 'toolGroupEnd':
            onToolGroupEnd(message.data);
            break;

        case 'toolCall':
            typingIndicator.textContent = 'Using tool: ' + message.tool + '...';
            typingIndicator.classList.add('visible');
            // v1.12.0: Use collapsible tool message
            addToolMessage('tool-call', '🔧 Calling tool: ' + message.tool, JSON.stringify(message.arguments, null, 2), message.verbose);

            // BUGFIX: Strip tool call JSON from current response content
            // When Gemini includes tool JSON in its response, remove it from display
            if (currentResponseContent) {
                // Remove trailing JSON code blocks that match tool call pattern
                // Pattern: \\\`\\\`\\\`json\\n{\\n  "tool": "...",\\n  "arguments": {...}\\n}\\n\\\`\\\`\\\`
                const toolJsonPattern = /\\\`\\\`\\\`(?:json)?\\s*\\{[^\\\`]*?"tool"\\s*:\\s*"[^"]+?"[^\\\`]*?\\}\\s*\\\`\\\`\\\`\\s*$/;
                const beforeStrip = currentResponseContent;
                currentResponseContent = currentResponseContent.replace(toolJsonPattern, '').trimEnd();

                // If we stripped something, re-render to remove the JSON from UI
                if (beforeStrip !== currentResponseContent && currentResponseEl) {
                    const contentEl = currentResponseEl.querySelector('.message-content') || currentResponseEl;
                    contentEl.innerHTML = simpleFormat(currentResponseContent);
                }
            }
            break;

        case 'toolResult':
            typingIndicator.textContent = 'Processing tool result...';
            // v1.12.0: Use collapsible tool message with verbose support
            const resultPreview = typeof message.result === 'string'
                ? (message.result.length > 2000 ? message.result.slice(0, 2000) + '...' : message.result)
                : JSON.stringify(message.result, null, 2);
            addToolMessage('tool-result', '📋 Result from ' + message.tool, resultPreview, message.verbose);
            break;

        case 'contextInjected':
            const sizeStr = formatFileSize(message.size);
            const truncNote = message.truncated ? ' (truncated)' : '';
            addMessage('system', '📎 Attached: \`' + message.source + '\` (' + sizeStr + ')' + truncNote, true);
            break;

        case 'startResponse':
            typingIndicator.textContent = 'Thinking... (Press Esc to stop)';
            typingIndicator.classList.add('visible');
            streamingBadge.style.display = 'block';  // Show streaming indicator
            // v1.13.2: Set streaming flag, clear sending flag (matches web app pattern)
            isStreaming = true;
            isSending = false;
            currentResponseEl = null;
            currentResponseContent = '';
            responseStartTime = Date.now();
            break;

        case 'thinking':
            // Backend received request or iteration progress
            typingIndicator.textContent = message.content || 'Processing...';
            typingIndicator.classList.add('visible');
            break;

        case 'started':
            // API call started, waiting for first token
            typingIndicator.textContent = 'Waiting for response...';
            break;

        case 'reasoning_chunk':
            // v1.13.9: Reasoning tokens from DeepSeek R1, GPT-OSS 120B
            typingIndicator.classList.remove('visible');
            if (!currentResponseEl) {
                currentResponseEl = addMessage('assistant', '', false);
            }
            // Append to reasoning section (collapsible)
            appendReasoningChunk(currentResponseEl, message.content);
            break;

        case 'chunk':
            if (!currentResponseEl) {
                currentResponseEl = addMessage('assistant', '', false);
                typingIndicator.classList.remove('visible');
            }
            // v1.13.9: Close reasoning section when content starts
            closeReasoningSection(currentResponseEl);
            currentResponseContent += message.content;
            scheduleRender(); // Throttled simple render during streaming
            break;

        case 'fullResponse':
            // Handle complete response from stream_end (used when tools are called)
            // This arrives BEFORE endResponse with the full content
            if (!currentResponseEl) {
                currentResponseEl = addMessage('assistant', '', false);
                typingIndicator.classList.remove('visible');
            }
            currentResponseContent = message.content;
            scheduleRender();
            break;

        case 'emptyResponse':
            // v1.13.2: Handle empty responses (common with GPT-OSS 120B after tool iterations)
            typingIndicator.classList.remove('visible');
            if (!currentResponseEl) {
                currentResponseEl = addMessage('assistant', '', false);
            }
            // Show placeholder message for empty response
            if (!currentResponseContent) {
                currentResponseContent = '*Task completed. (No additional response from AI)*';
                scheduleRender();
            }
            break;

        case 'endResponse':
            typingIndicator.classList.remove('visible');
            streamingBadge.style.display = 'none';  // Hide streaming indicator
            // v1.13.2: Reset flags after response (matches web app pattern)
            isStreaming = false;
            isSending = false;
            // Full markdown render with syntax highlighting at the end
            fullRender(true);
            // Save last assistant message for export
            lastAssistantMessage = currentResponseContent;
            currentResponseEl = null;
            currentResponseContent = '';
            responseStartTime = 0;
            break;

        case 'error':
            typingIndicator.classList.remove('visible');
            streamingBadge.style.display = 'none';  // Hide streaming indicator
            addMessage('error', message.content, false);
            // v1.13.2: Reset flags after error (matches web app pattern)
            isStreaming = false;
            isSending = false;
            break;

        case 'status':
            providerSpan.textContent = message.provider;
            modelSpan.textContent = message.model;
            if (message.toolsEnabled) {
                toolsBadge.textContent = 'Tools: ' + message.toolCount;
                toolsBadge.classList.remove('disabled');
                toolsBadge.classList.add('enabled');
                toolsBadge.title = 'Click to disable tools';
            } else {
                toolsBadge.textContent = 'Tools: off';
                toolsBadge.classList.add('disabled');
                toolsBadge.classList.remove('enabled');
                toolsBadge.title = 'Click to enable tools';
            }
            // Update usage badge (v1.12.0)
            if (message.usage && usageBadge) {
                const formatTokens = (count) => count >= 1000 ? (count/1000).toFixed(1) + 'K' : count.toString();
                const promptStr = formatTokens(message.usage.promptTokens);
                const completionStr = formatTokens(message.usage.completionTokens);
                const cost = message.usage.estimatedCost;
                if (cost > 0) {
                    usageBadge.textContent = promptStr + '↓/' + completionStr + '↑ $' + cost.toFixed(4);
                    usageBadge.classList.add('has-cost');
                } else {
                    usageBadge.textContent = promptStr + '↓/' + completionStr + '↑';
                    usageBadge.classList.remove('has-cost');
                }
                usageBadge.title = 'Session: ' + message.usage.totalTokens.toLocaleString() + ' tokens, $' + cost.toFixed(4);
            }
            // Sync verbose/debug indicators from full status
            if (message.toolsVerbose !== undefined) {
                verboseToolsIndicator.classList.toggle('active', message.toolsVerbose);
            }
            if (message.debugLog !== undefined) {
                debugLogIndicator.classList.toggle('active', message.debugLog);
            }
            break;

        case 'verboseToolsStatus':
            verboseToolsIndicator.classList.toggle('active', message.enabled);
            break;

        case 'hintsStatus':
            if (!message.loaded || message.total === 0) {
                hintsBadge.style.display = 'none';
            } else {
                hintsStatus.textContent = 'Hints: ' + message.total;
                hintsBadge.title = message.provCount + ' provider + ' + message.modelCount + ' model hints\nSource: ' + message.source;
                hintsBadge.style.display = '';
                hintsBadge.classList.toggle('enabled', message.total > 0);
            }
            break;

        case 'stateSync':
            // SSE state_sync — update UI elements for changed fields
            if (message.changes) {
                const c = message.changes;
                if (c.currentProvider !== undefined) { providerSpan.textContent = c.currentProvider; }
                if (c.currentModel !== undefined) { modelSpan.textContent = c.currentModel; }
                if (c.toolsEnabled !== undefined) {
                    if (c.toolsEnabled) {
                        toolsBadge.classList.remove('disabled');
                        toolsBadge.classList.add('enabled');
                    } else {
                        toolsBadge.classList.add('disabled');
                        toolsBadge.classList.remove('enabled');
                        toolsBadge.textContent = 'Tools: off';
                    }
                }
                if (c.toolsVerbose !== undefined) {
                    verboseToolsIndicator.classList.toggle('active', c.toolsVerbose);
                }
                if (c.debugLog !== undefined) {
                    debugLogIndicator.classList.toggle('active', c.debugLog);
                }
                // v1.17.4: Show context attachments count badge
                if (c.contextAttachments !== undefined) {
                    const arr = Array.isArray(c.contextAttachments)
                        ? c.contextAttachments : [];
                    updateContextAttachmentsBadge(arr.length, arr);
                }
            }
            break;

        case 'debugLogStatus':
            if (message.enabled) {
                debugLogIndicator.classList.add('active');
            } else {
                debugLogIndicator.classList.remove('active');
            }
            break;

        case 'agentStatus':
            // v1.11.8, v1.12.0: Handle agent mode + checkpoint status updates
            const agentBadgeEl = document.getElementById('agentBadge');
            const undoBadgeEl = document.getElementById('undoBadge');

            if (message.enabled) {
                // Agent mode is ON
                agentBadgeEl.classList.remove('disabled');
                agentBadgeEl.classList.add('enabled');

                // Remove all checkpoint classes first
                agentBadgeEl.classList.remove('checkpoint-git', 'checkpoint-file', 'checkpoint-none');

                // Update based on checkpoint backend (v1.12.0)
                if (message.checkpoint) {
                    const backend = message.checkpoint.backend;
                    const lastCheckpoint = message.checkpoint.last_checkpoint;

                    if (backend === 'git') {
                        agentBadgeEl.classList.add('checkpoint-git');
                        agentBadgeEl.textContent = 'Agent 🔒';
                        agentBadgeEl.title = 'Agent mode ON (Checkpoints: git)\n• Auto-commits before tasks\n• Use Undo button to revert';
                    } else if (backend === 'file') {
                        agentBadgeEl.classList.add('checkpoint-file');
                        agentBadgeEl.textContent = 'Agent ⚠️';
                        agentBadgeEl.title = 'Agent mode ON (Checkpoints: file)\n• Snapshots saved to ~/.ppxai/checkpoints\n• Use Undo button to revert\n• Tip: Init git repo for atomic commits';
                    } else {
                        agentBadgeEl.classList.add('checkpoint-none');
                        agentBadgeEl.textContent = 'Agent ⚠️';
                        agentBadgeEl.title = 'Agent mode ON (Checkpoints: DISABLED)\n• Changes CANNOT be undone\n• Initialize git repo to enable checkpoints';
                    }

                    // Update undo button (v1.12.1: validity-aware styling)
                    const isValid = message.checkpoint.is_valid !== false;  // Default true for backward compat
                    undoBadgeEl.classList.remove('enabled', 'disabled', 'stale');

                    if (lastCheckpoint) {
                        const shortId = lastCheckpoint.length > 8 ? lastCheckpoint.substring(0, 8) : lastCheckpoint;
                        undoBadgeEl.classList.add('visible');

                        if (isValid) {
                            // Valid checkpoint: blue enabled
                            undoBadgeEl.classList.add('enabled');
                            undoBadgeEl.title = `Undo Last Agent Task\nCheckpoint: ${shortId} (${backend})`;
                        } else {
                            // Stale checkpoint: red disabled
                            undoBadgeEl.classList.add('stale');
                            const reason = message.checkpoint.validity_reason || 'Checkpoint is stale';
                            undoBadgeEl.title = `Cannot Undo: ${reason}\nCheckpoint: ${shortId} (STALE)\nUse 'git revert ${shortId}' manually if needed`;
                        }
                    } else {
                        // No checkpoint: grey disabled
                        undoBadgeEl.classList.add('visible', 'disabled');
                        undoBadgeEl.title = 'No checkpoint to undo';
                    }
                } else {
                    // No checkpoint info (old server or disabled)
                    agentBadgeEl.textContent = 'Agent: on';
                    agentBadgeEl.title = 'Agent mode enabled - click to disable';
                    undoBadgeEl.classList.remove('visible');
                }
            } else {
                // Agent mode is OFF
                agentBadgeEl.textContent = 'Agent: off';
                agentBadgeEl.classList.add('disabled');
                agentBadgeEl.classList.remove('enabled', 'checkpoint-git', 'checkpoint-file', 'checkpoint-none');
                agentBadgeEl.title = 'Click to enable agent mode';

                // Hide undo button when agent is off (v1.12.1: also clear stale class)
                undoBadgeEl.classList.remove('visible', 'enabled', 'stale');
                undoBadgeEl.classList.add('disabled');
            }
            break;

        case 'workspaceInfo':
            const workspaceInfoEl = document.getElementById('workspaceInfo');
            const workspacePathEl = document.getElementById('workspacePath');
            const workspaceNameEl = document.getElementById('workspaceName');

            if (message.hasWorkspace) {
                workspacePathEl.textContent = message.path;
                workspacePathEl.title = message.path;  // Show full path on hover
                workspaceNameEl.textContent = message.name;
                workspaceInfoEl.style.display = 'flex';
            } else {
                workspaceInfoEl.style.display = 'none';
            }
            break;

        case 'workingDirChanged':
            // v1.13.2: Update workspace display when AI changes working directory
            const wdInfoEl = document.getElementById('workspaceInfo');
            const wdPathEl = document.getElementById('workspacePath');
            const wdNameEl = document.getElementById('workspaceName');

            if (message.path && wdInfoEl && wdPathEl && wdNameEl) {
                const parts = message.path.split('/');
                const name = parts[parts.length - 1] || message.path;
                wdPathEl.textContent = message.path;
                wdPathEl.title = message.path;
                wdNameEl.textContent = name;
                wdInfoEl.style.display = 'flex';
            }
            break;

        case 'updateContext':
            // v1.13.9: Update context usage badge
            if (contextBadge && contextUsage) {
                const percent = message.percent || 0;
                contextUsage.textContent = 'Ctx: ' + percent.toFixed(0) + '%' + (message.suffix || '');
                contextBadge.classList.remove('warning', 'critical');
                if (message.badgeClass) {
                    contextBadge.classList.add(message.badgeClass);
                }
                contextBadge.title = 'Context: ' + percent.toFixed(1) + '% used - Click to clear injected files';
            }
            break;

        case 'serverStatus':
            // Update server status badge (v1.13.1)
            updateServerStatus(message.connected, message.connecting);
            break;

        case 'history':
            // Clear existing messages except typing indicator
            messagesContainer.innerHTML = '';
            typingIndicator = document.createElement('div');
            typingIndicator.className = 'typing-indicator';
            typingIndicator.id = 'typingIndicator';
            typingIndicator.textContent = 'Thinking... (Press Esc to stop)';
            messagesContainer.appendChild(typingIndicator);
            lastMessageTime = null; // Reset time tracking for history

            message.messages.forEach(msg => {
                if (msg.role !== 'system') {
                    addMessage(msg.role, msg.content, msg.role === 'assistant');
                }
            });
            break;

        case 'cleared':
            messagesContainer.innerHTML = '';
            typingIndicator = document.createElement('div');
            typingIndicator.className = 'typing-indicator';
            typingIndicator.id = 'typingIndicator';
            typingIndicator.textContent = 'Thinking... (Press Esc to stop)';
            messagesContainer.appendChild(typingIndicator);
            lastMessageTime = null; // Reset time tracking
            break;

        case 'fileSuggestions':
            // Received file suggestions for autocomplete
            // v1.13.8: Don't show if input was cleared (message sent during async request)
            if (!messageInput.value.includes('@')) {
                break;
            }
            // Don't show if autocomplete is disabled (e.g., @git, @tree special providers)
            if (!autocompleteDisabled && (autocompleteMode === 'file' || message.files.length > 0)) {
                showAutocomplete(message.files, 'file');
            }
            break;

        case 'completionItems':
            // v1.17.4: Server-side completion results (commands + path args)
            if (!messageInput.value.startsWith('/')) break;
            if (message.items && message.items.length > 0) {
                // Map server items to autocomplete format
                const items = message.items.map(item => ({
                    name: item.display || item.text,
                    description: item.description || '',
                    text: item.text,
                    kind: item.kind,
                    replace_start: item.replace_start || 0,
                }));
                const mode = items[0].kind === 'dir' || items[0].kind === 'file' ? 'path' : 'command';
                showAutocomplete(items, mode);
            } else {
                hideAutocomplete();
            }
            break;
    }
});

function formatFileSize(bytes) {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
}

function formatTimestamp() {
    const now = new Date();
    const h = now.getHours().toString().padStart(2, '0');
    const m = now.getMinutes().toString().padStart(2, '0');
    const s = now.getSeconds().toString().padStart(2, '0');
    const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                   'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
    const mon = months[now.getMonth()];
    const day = now.getDate();
    return h + ':' + m + ':' + s + ' ' + mon + ' ' + day;
}

function formatDividerLabel(date) {
    const now = new Date();
    const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    const msgDate = new Date(date.getFullYear(), date.getMonth(), date.getDate());
    const diffDays = Math.floor((today - msgDate) / (1000 * 60 * 60 * 24));

    const timeStr = date.getHours().toString().padStart(2, '0') + ':' +
                   date.getMinutes().toString().padStart(2, '0');

    if (diffDays === 0) {
        return 'Today ' + timeStr;
    } else if (diffDays === 1) {
        return 'Yesterday ' + timeStr;
    } else if (diffDays < 7) {
        const days = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
        return days[date.getDay()] + ' ' + timeStr;
    } else {
        const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                       'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
        return months[date.getMonth()] + ' ' + date.getDate() + ' ' + timeStr;
    }
}

function shouldShowTimeDivider(currentTime) {
    if (!lastMessageTime) return true; // First message always shows divider

    const lastDate = new Date(lastMessageTime.getFullYear(), lastMessageTime.getMonth(), lastMessageTime.getDate());
    const currDate = new Date(currentTime.getFullYear(), currentTime.getMonth(), currentTime.getDate());

    // Always show if date changed
    if (lastDate.getTime() !== currDate.getTime()) return true;

    // Show if gap is more than threshold
    return (currentTime - lastMessageTime) >= TIME_GAP_THRESHOLD_MS;
}

function addTimeDivider(date) {
    const divider = document.createElement('div');
    divider.className = 'time-divider';
    const label = document.createElement('span');
    label.className = 'time-divider-label';
    label.textContent = formatDividerLabel(date);
    divider.appendChild(label);
    messagesContainer.insertBefore(divider, typingIndicator);
}

// Flatten multimodal content (string | array of content blocks) to plain
// text for display. Mirrors Message.text_content() in the Python engine.
// SSE stream chunks always arrive as strings — this matters only for
// messages loaded from a saved session that contain attachments.
function normalizeContent(content) {
    if (typeof content === 'string') return content;
    if (!Array.isArray(content)) return content == null ? '' : String(content);
    const parts = [];
    for (const block of content) {
        if (!block || typeof block !== 'object') continue;
        if (block.type === 'text') {
            parts.push(block.text || '');
        } else if (block.type === 'image_url') {
            parts.push(`[Image: ${block.name || 'image'}]`);
        } else if (block.type === 'input_file' || block.type === 'file') {
            parts.push(`[File: ${block.name || block.filename || 'file'}]`);
        } else {
            parts.push(`[${block.type || 'part'}]`);
        }
    }
    return parts.join('\n');
}

function addMessage(role, content, useMarkdown = true, files = null) {
    content = normalizeContent(content);
    const now = new Date();

    // Check if we should show a time divider before this message
    // Only show dividers for user messages (start of new interaction)
    if (role === 'user' && shouldShowTimeDivider(now)) {
        addTimeDivider(now);
    }

    const el = document.createElement('div');
    el.className = 'message ' + role;

    // Add timestamp
    const timestamp = document.createElement('span');
    timestamp.className = 'message-timestamp';
    timestamp.textContent = formatTimestamp();
    el.appendChild(timestamp);

    // Add copy button for assistant messages (v1.15.0)
    if (role === 'assistant') {
        const copyBtn = document.createElement('button');
        copyBtn.className = 'copy-btn';
        copyBtn.title = 'Copy to clipboard';
        copyBtn.textContent = '📋';
        copyBtn.onclick = function() {
            const contentEl = el.querySelector('.message-content');
            if (contentEl) {
                const text = contentEl.innerText || contentEl.textContent;
                navigator.clipboard.writeText(text).then(() => {
                    copyBtn.textContent = '✓';
                    copyBtn.classList.add('copied');
                    setTimeout(() => {
                        copyBtn.textContent = '📋';
                        copyBtn.classList.remove('copied');
                    }, 1500);
                }).catch(err => {
                    console.error('Failed to copy:', err);
                });
            }
        };
        el.appendChild(copyBtn);
    }

    // Update last message time
    lastMessageTime = now;

    // Add content
    const contentEl = document.createElement('div');
    contentEl.className = 'message-content';
    if (useMarkdown && content) {
        try {
            contentEl.innerHTML = parseMarkdown(content);
            // parseMarkdown() already extracts and renders markdown code blocks
            // Just apply syntax highlighting to regular code blocks (skip rendered markdown content)
            contentEl.querySelectorAll('pre code').forEach((block) => {
                // Skip code blocks inside rendered markdown divs
                if (block.closest('.rendered-markdown-content')) return;

                hljs.highlightElement(block);
            });
        } catch (e) {
            console.error('Markdown parse error:', e);
            contentEl.textContent = content;
        }
    } else {
        contentEl.textContent = content;
    }
    el.appendChild(contentEl);

    // v1.17.4: Inline attachment thumbnails for user messages with files
    if (files && files.length > 0) {
        const attachDiv = document.createElement('div');
        attachDiv.className = 'message-attachments';
        files.forEach(f => {
            const isImage = f.media_type && f.media_type.startsWith('image/');
            if (isImage && f.data) {
                const img = document.createElement('img');
                img.className = 'attach-thumb';
                img.src = `data:${f.media_type};base64,${f.data}`;
                img.alt = f.name;
                img.title = `${f.name} — click to preview`;
                img.addEventListener('click', () => showAttachLightbox(f));
                attachDiv.appendChild(img);
            } else {
                const badge = document.createElement('span');
                badge.className = 'attach-file-badge';
                badge.title = `${f.name} — click to preview`;
                badge.textContent = '\u{1F4C4} ' + f.name;
                badge.addEventListener('click', () => showAttachLightbox(f));
                attachDiv.appendChild(badge);
            }
        });
        el.appendChild(attachDiv);
    }

    messagesContainer.insertBefore(el, typingIndicator);
    scrollToBottom();
    return el;
}

// v1.13.9: Append reasoning chunk to collapsible section
function appendReasoningChunk(messageEl, chunk) {
    if (!messageEl || !chunk) return;

    const contentEl = messageEl.querySelector('.message-content');
    if (!contentEl) return;

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
        contentEl.insertBefore(reasoningSection, contentEl.firstChild);
    }

    // Append chunk to reasoning content
    const reasoningContent = reasoningSection.querySelector('.reasoning-content');
    if (reasoningContent) {
        reasoningContent.textContent += chunk;
    }
    scrollToBottom();
}

// v1.13.9: Close reasoning section when main content starts
function closeReasoningSection(messageEl) {
    if (!messageEl) return;
    const contentEl = messageEl.querySelector('.message-content');
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

// v1.16.0: Tool group state
let currentToolGroup = null;

function onToolGroupStart(data) {
    const iteration = data?.iteration || 0;
    const count = data?.count || 0;
    const groupEl = document.createElement('div');
    groupEl.className = 'tool-group collapsed';

    const header = document.createElement('div');
    header.className = 'tool-group-header';
    header.innerHTML = '<span class="tool-group-toggle">&#9654;</span>' +
        '<span class="tool-group-label">Iteration ' + iteration + ': ' + count + ' tool' + (count !== 1 ? 's' : '') + '</span>' +
        '<span class="tool-group-status"></span>';
    header.addEventListener('click', function() {
        groupEl.classList.toggle('collapsed');
    });
    groupEl.appendChild(header);

    const body = document.createElement('div');
    body.className = 'tool-group-body';
    groupEl.appendChild(body);

    messagesContainer.insertBefore(groupEl, typingIndicator);
    currentToolGroup = groupEl;
    scrollToBottom();
}

function onToolGroupEnd(data) {
    if (!currentToolGroup) return;
    const allOk = data?.all_succeeded !== false;
    const tools = data?.tools || [];
    const status = allOk ? '\u2713' : '\u2717';
    const statusClass = allOk ? 'success' : 'failure';

    const label = currentToolGroup.querySelector('.tool-group-label');
    const statusEl = currentToolGroup.querySelector('.tool-group-status');
    if (label && tools.length) {
        label.textContent = 'Iteration ' + (data?.iteration || 0) + ': ' + tools.join(', ');
    }
    if (statusEl) {
        statusEl.textContent = status;
        statusEl.className = 'tool-group-status ' + statusClass;
    }
    currentToolGroup = null;
    scrollToBottom();
}

// v1.12.0: Add tool message with collapsible details
function addToolMessage(role, title, details, verbose) {
    const now = new Date();
    const el = document.createElement('div');
    el.className = 'message ' + role;

    // Add timestamp
    const timestamp = document.createElement('span');
    timestamp.className = 'message-timestamp';
    timestamp.textContent = formatTimestamp();
    el.appendChild(timestamp);

    // Update last message time
    lastMessageTime = now;

    // Tool title (clickable to toggle details)
    const titleEl = document.createElement('div');
    const isCollapsed = verbose !== true;
    titleEl.className = 'tool-title' + (details ? ' clickable' : '') + (isCollapsed ? ' collapsed' : '');
    titleEl.textContent = title;
    el.appendChild(titleEl);

    // Details (always created, collapsed by default unless verbose ON)
    if (details) {
        const contentEl = document.createElement('pre');
        contentEl.className = 'tool-details-content' + (isCollapsed ? ' collapsed' : '');
        const codeEl = document.createElement('code');
        codeEl.textContent = details;
        contentEl.appendChild(codeEl);
        el.appendChild(contentEl);

        // Click title to toggle collapse
        titleEl.addEventListener('click', () => {
            contentEl.classList.toggle('collapsed');
            titleEl.classList.toggle('collapsed');
        });
    }

    // v1.16.0: Insert into tool group body if active
    if (currentToolGroup) {
        currentToolGroup.querySelector('.tool-group-body').appendChild(el);
    } else {
        messagesContainer.insertBefore(el, typingIndicator);
    }
    scrollToBottom();
    return el;
}

function scrollToBottom() {
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
}

// Signal ready
vscode.postMessage({ type: 'ready' });
