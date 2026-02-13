# ppxai Live HTML Preview — Implementation Plan

## Overview

Add a `/preview` command across all ppxai clients (Web App, VSCode Extension, TUI) that opens a live-reloading HTML preview with **zero new dependencies**. Each client uses its native mechanism for rendering and file-watching.

---

## Goals

- Live preview of HTML files generated or edited by the AI
- Auto-reload on file changes
- Zero new Python or npm dependencies
- Minimal code footprint per client
- Session-aware path resolution (respects working directory)

---

## Architecture

```
┌─────────────┐     ┌─────────────┐     ┌──────────────────────┐
│   Web App   │     │   VSCode    │     │  TUI (Rich/Textual)  │
│  (iframe +  │     │ (Webview +  │     │  (stdlib HTTPServer   │
│ Web Worker) │     │ FSWatcher)  │     │   + webbrowser.open)  │
└──────┬──────┘     └──────┬──────┘     └──────────┬───────────┘
       │                   │                       │
       │ polls /preview/   │ reads file            │ daemon thread
       │ poll/{path}       │ directly              │ serves on :0
       │                   │                       │ browser tab
       ▼                   ▼                       ▼
┌──────────────────────────────────────┐  ┌────────────────────┐
│       ppxai-server (FastAPI)         │  │  PreviewServer     │
│                                      │  │  (stdlib, in-proc) │
│  GET /preview/{filepath}   → HTML    │  │  GET /       → HTML│
│  GET /preview/poll/{path}  → mtime   │  │  GET /poll   → mtime│
│  GET /preview/static/{path}→ assets  │  │  GET /*      → assets│
└──────────────────────────────────────┘  └────────────────────┘
```

**Key insight:** The FastAPI endpoints serve the Web App (via Worker polling). TUI clients are standalone and spawn their own stdlib `HTTPServer` in a daemon thread — same reload script, no server dependency. VSCode bypasses any server entirely using native APIs.

---

## Phase 1: Server-Side Endpoints

**File:** `ppxai/server_preview.py`  
**Dependencies:** None (FastAPI already in stack)

### Tasks

- [ ] Create `APIRouter` with prefix `/preview`
- [ ] `GET /preview/{filepath:path}` — read HTML file, inject reload `<script>` before `</body>`
- [ ] `GET /preview/poll/{filepath:path}` — return `{ "mtime": <float> }` from `os.stat()`
- [ ] `GET /preview/static/{filepath:path}` — serve CSS/JS/images referenced by the HTML
- [ ] Path resolution: resolve relative paths against session working directory
- [ ] Path traversal guard: reject paths that escape working directory
- [ ] Register router in main server app

### Injected Reload Script

Appended before `</body>` in served HTML:

```javascript
(function() {
  let lastMtime = null;
  const path = window.location.pathname.replace('/preview/', '');
  async function poll() {
    try {
      const res = await fetch('/preview/poll/' + path);
      const data = await res.json();
      if (lastMtime !== null && data.mtime !== lastMtime) {
        window.location.reload();
      }
      lastMtime = data.mtime;
    } catch(e) {}
    setTimeout(poll, 500);
  }
  poll();
})();
```

### Session Awareness

- Use `request.app.state` or session header to resolve the correct working directory
- Consistent with existing file editing tool path resolution (v1.13.3 fix)

---

## Phase 2: Web App — Inline iframe + Blob Web Worker

**File:** `ppxai/web/js/preview.js` + minor CSS  
**Dependencies:** None (browser-native APIs)

### Tasks

- [ ] `openPreview(filepath)` — create split-panel UI with iframe pointing at `/preview/{filepath}`
- [ ] Spawn inline Web Worker from `Blob` URL (no separate worker file)
- [ ] Worker polls `/preview/poll/{filepath}` every 500ms
- [ ] On mtime change, `postMessage('reload')` → parent reloads iframe `src`
- [ ] `closePreview()` — terminate worker, remove panel DOM
- [ ] Wire `/preview` command in Web App command handler
- [ ] CSS: absolute-positioned right panel, 50% width, resizable border (optional)

### Implementation Notes

- Inline Blob Worker avoids a separate `.js` file and CSP issues
- iframe `sandbox="allow-scripts allow-same-origin"` for basic security
- iframe reload via `src += ''` trick (cache-busted by server mtime)

---

## Phase 3: VSCode Extension — Native WebviewPanel

**File:** `vscode-extension/src/previewPanel.ts`  
**Dependencies:** None (VSCode API only)

### Tasks

- [ ] `openHtmlPreview(filePath)` — create `WebviewPanel` in `ViewColumn.Beside`
- [ ] Read HTML file via `fs.readFileSync()`
- [ ] Rewrite relative asset paths (`src=`, `href=`) to `webview.asWebviewUri()` 
- [ ] Set `localResourceRoots` to file's parent directory
- [ ] Create `FileSystemWatcher` on the file path
- [ ] On `onDidChange`, re-read and update `webview.html`
- [ ] Dispose watcher when panel closes
- [ ] Wire `/preview` command in extension command handler

### Implementation Notes

- No server dependency — reads file directly from disk
- VSCode's `FileSystemWatcher` is efficient (inotify/FSEvents under the hood)
- Asset rewriting regex: `/(src|href)="(?!https?:\/\/|data:)([^"]+)"/g`

---

## Phase 4: TUI Clients (Rich & Textual) — Stdlib Mini-Server + Browser Tab

**File:** `ppxai/preview_server.py` (new, shared by both TUI clients)  
**Dependencies:** None — `http.server`, `threading`, `webbrowser` are all stdlib

The Rich TUI and Textual TUI are standalone clients that do **not** use the FastAPI server. They need their own lightweight preview mechanism.

### Approach

Spawn a minimal `http.server.HTTPServer` in a daemon thread that:
- Serves the HTML file with the injected reload script
- Serves a `/poll` endpoint returning file mtime
- Serves sibling static assets (CSS/JS/images)
- Auto-picks a free port
- Shuts down when preview is closed or TUI exits

### Tasks

- [ ] Create `PreviewServer` class wrapping `HTTPServer` + `SimpleHTTPRequestHandler`
- [ ] Custom request handler: intercept the HTML file path, inject reload script; pass-through everything else as static assets
- [ ] `/poll` route returning `{ "mtime": <float> }` JSON
- [ ] `start()` — bind to `localhost:0` (OS picks free port), spawn daemon thread
- [ ] `stop()` — call `server.shutdown()`
- [ ] `open_preview(filepath, working_dir)` — start server, call `webbrowser.open()`
- [ ] Wire into Rich TUI command handler (`ppxai/commands.py`)
- [ ] Wire into Textual TUI command handler
- [ ] Track active preview server instance; `/preview close` or new `/preview` kills previous

### Implementation Sketch

```python
# ppxai/preview_server.py
import os, json, re, threading, webbrowser
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

class PreviewHandler(SimpleHTTPRequestHandler):
    """Serves HTML with injected reload script + poll endpoint."""

    def do_GET(self):
        if self.path == '/poll':
            mtime = self.server.target_file.stat().st_mtime
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"mtime": mtime}).encode())
            return

        if self.path == '/' or self.path == '/index':
            content = self.server.target_file.read_text('utf-8')
            content = _inject_reload_script(content)
            self.send_response(200)
            self.send_header('Content-Type', 'text/html')
            self.end_headers()
            self.wfile.write(content.encode())
            return

        # Fallback: serve static assets from working dir
        super().do_GET()

    def log_message(self, format, *args):
        pass  # silence logs

class PreviewServer:
    def __init__(self, filepath: str, working_dir: str):
        self.target = Path(working_dir, filepath).resolve()
        self.server = HTTPServer(('127.0.0.1', 0), PreviewHandler)
        self.server.target_file = self.target
        # Serve static assets relative to file's directory
        os.chdir(self.target.parent)
        self.port = self.server.server_address[1]
        self._thread = None

    def start(self):
        self._thread = threading.Thread(
            target=self.server.serve_forever, daemon=True
        )
        self._thread.start()
        url = f"http://localhost:{self.port}/"
        webbrowser.open(url)
        return url

    def stop(self):
        self.server.shutdown()
```

### Implementation Notes

- Daemon thread dies automatically when TUI exits — no cleanup needed on crash
- `HTTPServer('127.0.0.1', 0)` lets the OS pick a free port — no conflicts
- `SimpleHTTPRequestHandler` serves CSS/JS/images from the file's directory for free
- Same injected reload script as Phase 1 (reuse `_inject_reload_script()`)
- Both Rich TUI and Textual TUI import the same `PreviewServer` class

---

## Phase 5: Command Registration & Help

### All Clients

- [ ] Register `/preview` in shared command module
- [ ] Autocomplete: suggest `.html` files in working directory
- [ ] Help text: `/preview <file.html>` — Open live HTML preview

### Command Behavior

```
/preview index.html          → open preview
/preview                     → show usage
/preview close               → close preview (Web App only, others close tab/panel)
```

---

## Testing

### Server Tests (FastAPI)

- [ ] `test_preview_serves_html` — returns HTML with injected script
- [ ] `test_preview_poll_returns_mtime` — returns valid mtime JSON
- [ ] `test_preview_path_traversal_blocked` — `../../../etc/passwd` returns 403
- [ ] `test_preview_file_not_found` — returns 404
- [ ] `test_preview_static_assets` — CSS/JS files served correctly
- [ ] `test_preview_respects_working_dir` — resolves against session directory

### TUI PreviewServer Tests (stdlib)

- [ ] `test_preview_server_starts_on_free_port` — binds to random port
- [ ] `test_preview_server_serves_html_with_reload` — injected script present
- [ ] `test_preview_server_poll_mtime` — returns valid JSON
- [ ] `test_preview_server_static_assets` — sibling files served
- [ ] `test_preview_server_stop` — clean shutdown

### Integration Tests

- [ ] Web App: iframe loads, worker polls, reload triggers on file touch
- [ ] VSCode: panel opens beside editor, content updates on save
- [ ] Rich TUI: PreviewServer starts, browser opens correct URL
- [ ] Textual TUI: PreviewServer starts, browser opens correct URL

---

## Dependency Audit

| Component | New Dependencies | Mechanism Used |
|-----------|-----------------|----------------|
| Server (`server_preview.py`) | None | FastAPI (existing), pathlib, os.stat |
| Web App (`preview.js`) | None | iframe, Blob Worker, fetch |
| VSCode (`previewPanel.ts`) | None | WebviewPanel, FileSystemWatcher, fs |
| TUI (`preview_server.py`) | None | http.server, threading, webbrowser (all stdlib) |

**Total new dependencies: 0**

---

## File Changes Summary

| File | Change |
|------|--------|
| `ppxai/server_preview.py` | **New** — FastAPI router with 3 endpoints |
| `ppxai/server.py` | Add `app.include_router(preview_router)` |
| `ppxai/preview_server.py` | **New** — Stdlib PreviewServer for TUI clients |
| `ppxai/commands.py` | Add `/preview` command handler (Rich TUI) |
| `ppxai/textual_app.py` | Wire `/preview` command (Textual TUI) |
| `ppxai/web/js/preview.js` | **New** — openPreview/closePreview functions |
| `ppxai/web/css/preview.css` | **New** — preview panel styles (~15 lines) |
| `ppxai/web/index.html` | Add script/css includes, wire command |
| `vscode-extension/src/previewPanel.ts` | **New** — WebviewPanel + FSWatcher |
| `vscode-extension/src/extension.ts` | Wire `/preview` command |
| `tests/test_server_preview.py` | **New** — 6+ server endpoint tests |
| `tests/test_preview_server.py` | **New** — stdlib PreviewServer tests |

**Estimated total new code:** ~250 lines across all components

---

## Milestones

1. **Shared reload script utility** — `_inject_reload_script()` reusable by both server types
2. **TUI preview working** — `PreviewServer` + `webbrowser.open()` (fastest end-to-end test)
3. **FastAPI server endpoints working** — curl returns HTML with injected script, poll returns mtime
4. **Web App split-panel preview** — iframe + Worker polling
5. **VSCode native preview** — Webview + FileSystemWatcher
6. **Tests passing** — server endpoint tests + PreviewServer tests + smoke tests per client
