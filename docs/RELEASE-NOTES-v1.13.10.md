# Release Notes - v1.13.10

**Release Date:** 2026-01-14

This is a stabilization release focusing on web app enhancements, session restore fixes, and tool loop detection before the v1.14.x series.

## Highlights

### Web App File Preview

The `/show` command in the web app now supports previewing images and PDFs directly in the preview panel:

**Image Preview**
- Supported formats: PNG, JPG, JPEG, GIF, WebP, SVG, BMP, ICO
- Images display centered with proper scaling
- Shows file size in the header

**PDF Preview**
- Uses browser's native PDF viewer
- Full navigation, zoom, and search capabilities
- Shows file size in the header

```
/show ./docs/architecture.png
/show ~/documents/report.pdf
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

## Files Changed

### Server
- `ppxai/server/http.py` - Image and PDF preview support in `/files/read` endpoint

### Web App
- `ppxai/web/app.js` - New `showImagePreview()` and `showPdfPreview()` methods

### Engine
- `ppxai/engine/tools/manager.py` - Tool loop detection (`is_tool_loop_detected()`, `get_loop_message()`)
- `ppxai/engine/client.py` - Loop detection integration in tool execution flow

## Upgrade Instructions

1. **Download new binaries** from GitHub Releases
2. **Replace existing binaries**:
   - Linux/macOS: `~/.local/bin/ppxai`, `~/.local/bin/ppxai-server`
   - Windows: Update executables in your install location
3. **Update VSCode extension**: Install `ppxai-1.13.10.vsix`
4. **Optional**: Add `max_same_tool_calls` to config if using tools with Ollama models

## What's Next (v1.14.x)

- Session isolation for multi-client support
- Enhanced MCP server integration
- Improved agent mode with conversation branching
