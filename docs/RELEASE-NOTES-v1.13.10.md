# Release Notes - v1.13.10

**Release Date:** 2026-01-19

This is a stabilization release focusing on web app enhancements, session restore fixes, and tool loop detection before the v1.14.x series.

## Highlights

### Web App File Preview

The `/show` command in the web app now supports previewing images, PDFs, and structured data files directly in the preview panel:

**Image Preview**
- Supported formats: PNG, JPG, JPEG, GIF, WebP, SVG, BMP, ICO
- Images display centered with proper scaling
- Shows file size in the header

**PDF Preview**
- Uses browser's native PDF viewer
- Full navigation, zoom, and search capabilities
- Shows file size in the header

**Structured Data Preview (Tree Viewer)**
- **JSON** - Collapsible tree with syntax highlighting
- **YAML** - Parsed via js-yaml library with tree navigation
- **TOML** - Parsed via toml-js library with tree navigation
- **HCL/Terraform** - Parsed via hcl2-parser with tree navigation
- Expand/collapse all, search within tree, type indicators
- Rendered/Source toggle to switch between formatted view and raw text

```
/show ./docs/architecture.png
/show ~/documents/report.pdf
/show ./config.yaml
/show ./terraform/main.tf
```

### Tool Loop Detection

New `max_same_tool_calls` configuration prevents models from calling the same tool repeatedly:

```json
{
  "tools": {
    "agent": {
      "max_same_tool_calls": 3
    }
  }
}
```

When a model calls the same tool 3 times consecutively, ppxai injects a message forcing the model to synthesize results instead of continuing the loop. This prevents infinite loops with models that have poor tool-stopping behavior (common with some Ollama models).

## New Features

### Image Preview (Web App)
- Base64-encoded images served via `/files/read` API
- Automatic MIME type detection
- Responsive display with shadow styling

### PDF Preview (Web App)
- Base64-encoded PDFs served via `/files/read` API
- Native browser PDF viewer via `<embed>` element
- Works with all modern browsers

### Structured Data Tree Viewer (Web App)
- **DataTreeViewer component** - Collapsible tree with expand/collapse all controls
- **Multi-format support** - JSON (native), YAML (js-yaml), TOML (toml-js), HCL (hcl2-parser)
- **Type indicators** - Visual badges for string, number, boolean, null, array, object
- **Search within tree** - Filter nodes by key or value
- **Rendered/Source toggle** - Switch between tree view and raw text
- **Parsing libraries** - Bundled in `ppxai/web/lib/` directory

### Tool Loop Detection
- Configurable threshold (0 = disabled)
- Tracks consecutive calls to the same tool
- Injects synthesis prompt when threshold exceeded
- Resets tracking on different tool calls or user messages

## Bug Fixes

### Session Restore
- **Working directory** - `set_working_dir()` now updates both `context_injector.working_dir` and `session.working_dir`
- **Tools state** - Session saves and restores `tools_enabled` state. Tools are automatically re-enabled when restoring a session that had tools enabled.

### Tool Parameter Handling
- **Duplicate parameter names** - Fixed issue where models send both canonical and alias names in same call (e.g., both `file_path` AND `filepath`). Now removes duplicate aliases instead of passing them to tool execution.

## Configuration

### New Settings

Add to `ppxai-config.json`:

```json
{
  "tools": {
    "agent": {
      "max_same_tool_calls": 3
    }
  }
}
```

- `max_same_tool_calls`: Maximum consecutive calls to the same tool before forcing synthesis (default: 3, 0 = disabled)

## VSCode Extension Architecture

Major refactoring of `chatPanel.ts` using EventBus + State Machine patterns:

**handlers/ Module (1,658 lines)**
- `eventBus.ts` - Type-safe pub/sub communication between components
- `stream.ts` - Stream event processing with EventBus integration
- `agentStateMachine.ts` - Explicit agent loop state machine (idle→validating→iterating→complete)
- `consent.ts` - Consent dialog handlers with IoC pattern for testability
- `commands.ts` - /tools and /checkpoint command handlers
- `types.ts` - HandlerContext interface for dependency injection

**Architectural Benefits**
- Decoupled event producers from consumers (stream → EventBus → UI)
- Explicit state transitions replace implicit local variables
- Testable handlers via context injection
- chatPanel.ts reduced from 5,123 to 2,773 lines (46% reduction)

## Files Changed

### Server
- `ppxai/server/http.py` - Image and PDF preview support in `/files/read` endpoint

### Web App
- `ppxai/web/app.js` - New `showImagePreview()`, `showPdfPreview()`, and `showDataTreePreview()` methods
- `ppxai/web/components/tree-viewer.js` - `DataTreeViewer` class for structured data
- `ppxai/web/styles/data-viewers.css` - Styling for tree viewer components
- `ppxai/web/lib/js-yaml.min.js` - YAML parsing library
- `ppxai/web/lib/toml.min.js` - TOML parsing library
- `ppxai/web/lib/hcl2-parser.min.js` - HCL/Terraform parsing library

### Engine
- `ppxai/engine/tools/manager.py` - Tool loop detection (`is_tool_loop_detected()`, `get_loop_message()`)
- `ppxai/engine/client.py` - Loop detection integration in tool execution flow

### VSCode Extension
- `src/chatPanel.ts` - Orchestrator with EventBus + State Machine integration
- `src/handlers/eventBus.ts` - Type-safe ChatEventBus (211 lines)
- `src/handlers/stream.ts` - Stream event processor (212 lines)
- `src/handlers/agentStateMachine.ts` - Agent state machine (375 lines)
- `src/handlers/consent.ts` - Consent handlers with IoC (246 lines)
- `src/handlers/commands.ts` - Command handlers (496 lines)
- `src/handlers/types.ts` - HandlerContext interface (58 lines)
- `src/handlers/index.ts` - Barrel exports (60 lines)

## Upgrade Instructions

1. **Download new binaries** from GitHub Releases
2. **Replace existing binaries**:
   - Linux/macOS: `~/.local/bin/ppxai`, `~/.local/bin/ppxai-server`
   - Windows: Update executables in your install location
3. **Update VSCode extension**: Install `ppxai-1.13.10.vsix`
4. **Optional**: Add `max_same_tool_calls` to config if using tools with Ollama models

## What's Next (v1.14.x)

The v1.14.x series focuses on **Session Bootstrap & Context** - reproducible starting points for every session:

- **AGENTS.md / CLAUDE.md support** - Load project instructions from markdown files on startup
- **Bootstrap context hierarchy** - Global (`~/.ppxai/`) → Project → Subdirectory context merging
- **`/context` extensions** - Show, reload, and edit bootstrap context files
- **Enhanced context providers** - `@url` for web content, `@clipboard` support, conditional sections

See [ROADMAP.md](../ROADMAP.md) for detailed v1.14.x planning.
