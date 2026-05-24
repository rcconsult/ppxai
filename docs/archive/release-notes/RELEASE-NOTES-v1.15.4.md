# Release Notes: v1.15.4

**Release Date:** 2026-02-13
**Branch:** bugfix/v1.15.4
**Focus:** Live HTML Preview, Corporate SSL Fixes, Debug Logging, VSCode Improvements

---

## Overview

v1.15.4 introduces the `/preview` command for live-reloading HTML previews across all three clients (TUI, Web App, VSCode), fixes corporate SSL/proxy issues in web tools, improves debug logging, and adds new syntax highlighting languages to the VSCode extension.

**Key Improvements:**
- `/preview` command with live reload across TUI, Web App, and VSCode
- Corporate SSL support with `_create_ssl_context()` and HTTP fallback
- Debug logging now enables ALL logger instances (`Logger.enable_all()`)
- highlight.js rebuilt with PowerShell, Dockerfile, DOS, AppleScript
- 34 new preview tests + 16 new SSL tests (1,227 total)

---

## Major Features

### 1. Live HTML Preview (`/preview` command)

**What it does:**
The `/preview <file.html>` command opens an HTML file in a live-reloading preview. Changes to the HTML file or its referenced assets (CSS, JS, JSON, images) are automatically detected and the preview refreshes.

**Implementation across clients:**

| Client | Server | Reload Method | Opens In |
|--------|--------|---------------|----------|
| **TUI** | Stdlib `PreviewServer` (daemon thread) | mtime polling at `/poll` | Default browser |
| **Web App** | FastAPI endpoints | SSE polling | Iframe split panel |
| **VSCode** | ppxai-server + `FileSystemWatcher` | Native file watcher | WebviewPanel |

**Shared utilities** (`ppxai/common/preview.py`):
- `inject_reload_script(html, poll_url)` - Auto-injects JavaScript polling script into HTML
- `rewrite_asset_paths(html, base_dir, cache_buster)` - Rewrites relative asset paths with cache-busting query strings (`?_t=<mtime>`)
- `resolve_preview_path(path, working_dir)` - Resolves and validates preview file paths

**Cache busting:**
Browser caching is the biggest obstacle to live-reload. Even when the HTML is reloaded, browsers serve stale CSS/JS from cache. The `rewrite_asset_paths()` function appends `?_t=<mtime>` to all asset URLs, forcing the browser to re-fetch on every file change. All preview responses also include `Cache-Control: no-cache` headers.

**Non-HTML file serving:**
JavaScript `fetch()` calls from within the preview iframe (e.g., `fetch('data.json')`) resolve against the iframe's page URL. The FastAPI catch-all endpoint now serves non-HTML files as `FileResponse` with correct MIME types, enabling dynamic data loading in previewed apps.

**Session resolution:**
JS `fetch()` calls from the preview iframe don't include the `X-Session-Id` header. The server resolves the session from the `Referer` header instead, ensuring the correct working directory is used.

**Files:**
- `ppxai/common/preview.py` - Shared preview utilities
- `ppxai/preview_server.py` - Stdlib HTTP preview server for TUI
- `ppxai/server/http.py` - FastAPI preview endpoints
- `ppxai/commands/display.py` - Preview command handler
- `vscode-extension/src/previewPanel.ts` - VSCode WebviewPanel implementation

### 2. Corporate SSL Support for Web Tools

**Problem:**
Corporate proxies that perform SSL inspection cause `ssl.SSLCertVerificationError` in web tools (`get_weather`, `fetch_url`, `web_search`).

**Solution:**
- New `_create_ssl_context()` function respects `SSL_VERIFY` and `SSL_CERT_FILE` environment variables
- `get_weather` tool tries HTTPS first, falls back to HTTP when corporate proxy stalls HTTPS
- All web tools now have configurable timeouts via `tools.<name>.timeout` in `ppxai-config.json` (default 15s)

**Files:**
- `ppxai/engine/tools/builtin/web.py` - SSL context, HTTP fallback, timeout configuration

### 3. Debug Logging Improvements

**Problem:**
`/debug-log on` only enabled the "tui" logger. Components using other logger names (chat, session, validator, gemini) remained silent.

**Solution:**
- `Logger.enable_all()` and `Logger.disable_all()` class methods enable/disable ALL logger instances at once
- `/debug-log on` now calls `Logger.enable_all()` for comprehensive logging

**Files:**
- `ppxai/common/logger.py` - `enable_all()` / `disable_all()` class methods

### 4. highlight.js Language Support

Rebuilt `highlight.min.js` for both Web App and VSCode extension with additional languages:
- **PowerShell** - Windows scripting
- **Dockerfile** - Container definitions
- **DOS/Batch** - Windows batch files
- **AppleScript** - macOS automation

**Files:**
- `vscode-extension/build-hljs.cjs` - Build script for custom highlight.js bundle
- `vscode-extension/media/highlight.min.js` - VSCode extension bundle
- `ppxai/web/lib/highlight.min.js` - Web App bundle

---

## VSCode Extension Changes

### Consent EventBus Migration
Consent dialog handling migrated from direct function calls to EventBus pattern, matching the architecture established in v1.13.10.

### Preview Auto-Refresh
`FileSystemWatcher` monitors all sibling assets (CSS, JS, JSON, SVG, PNG, JPG) relative to the previewed HTML file. Changes trigger automatic WebviewPanel refresh.

### Autocomplete Fixes
Improved slash command autocomplete reliability in the chat input.

---

## Bug Fixes

### Session Restore
- Provider and model are correctly restored from session metadata
- Prevents falling back to default provider/model after loading a session

### Gemini Provider
- Fixed content handling for tool responses with `None` content field

### Tool Parsing
- Improved detection of partial/malformed tool calls in streaming responses

---

## Benchmarks & Testing

### Qwen3-Coder-Next FP8 Evaluation
Three benchmark runs with different configurations:
1. **60.9%** (hermes parser, temperature=0.2)
2. **57.8%** (qwen3_coder parser, temperature=1.0)
3. **54.7%** (qwen3_coder parser, temperature=0.2)

**Verdict:** Not competitive with production Qwen3-Coder-30B FP8 (81.2%). High variance across runs, persistent weaknesses in hallucination resistance and tool calling.

### Test Results
- **Preview tests:** 34 new tests covering utilities, server, cache-busting, and data file serving
- **SSL tests:** 16 new tests for corporate proxy, timeout, and fallback scenarios
- **Total:** 1,227 tests passing

---

## New Files

| File | Purpose |
|------|---------|
| `ppxai/common/preview.py` | Shared preview utilities (inject_reload_script, rewrite_asset_paths, resolve_preview_path) |
| `ppxai/preview_server.py` | Stdlib HTTP preview server for TUI client |
| `vscode-extension/src/previewPanel.ts` | VSCode WebviewPanel with FileSystemWatcher |
| `vscode-extension/build-hljs.cjs` | highlight.js custom build script |
| `tests/test_preview.py` | 34 preview tests |
| `tests/test_web_tools_ssl.py` | 16 SSL/proxy tests |
| `docs/archive/v1.15.4/PLAN-live-html-preview.md` | Implementation plan for preview feature |

## Changed Files (Key)

| File | Change |
|------|--------|
| `ppxai/server/http.py` | Added `/preview/*` FastAPI endpoints with session-scoped working directory |
| `ppxai/engine/tools/builtin/web.py` | SSL context, HTTP fallback, configurable timeouts |
| `ppxai/common/logger.py` | `Logger.enable_all()` / `Logger.disable_all()` |
| `ppxai/commands/display.py` | Preview command handler |
| `ppxai/commands/results.py` | PreviewResult type |
| `ppxai/rendering/rich_renderer.py` | Preview rendering for Rich TUI |
| `ppxai/rendering/textual_renderer.py` | Preview rendering for Textual TUI |
| `vscode-extension/src/chatPanel.ts` | Consent EventBus migration, code extraction |
| `vscode-extension/src/handlers/stream.ts` | Preview event handling |
| `ppxai/web/app.js` | Preview iframe UI in Web App |

---

## Migration Notes

No breaking changes. All existing configurations continue to work.

**New configuration options (optional):**
```json
{
  "tools": {
    "get_weather": {
      "timeout": 15
    },
    "fetch_url": {
      "timeout": 15
    }
  }
}
```

**Environment variables:**
- `SSL_VERIFY=false` - Disable SSL verification for corporate proxies
- `SSL_CERT_FILE=/path/to/cert.pem` - Custom SSL certificate for corporate proxies
