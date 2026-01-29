# Release Notes: v1.15.1

**Release Date:** 2026-01-29
**Branch:** feature/1-15-1 → master
**Focus:** ppxaide TUI performance fixes and code cleanup

---

## Overview

Version 1.15.1 is a feature and bug-fix release that adds AI tool integration for proactive file viewing, addresses critical performance issues in the ppxaide TUI, and removes technical debt from the VSCode extension. The primary feature allows AI to autonomously display generated files in the split view. The primary fix resolves UI freezing during long AI streaming responses by implementing Textual's worker thread pattern with `call_from_thread()`.

**Key Highlights:**
- **`display_file` tool** - AI can now proactively show files in split view after creating/modifying them
- **UI responsiveness during streaming** - Event loop no longer blocked during 30+ second HTTP waits
- **Footer status widget** - Live elapsed timer shows streaming progress
- **CPU usage fix** - Timer cleanup prevents runaway processes
- **VSCode cleanup** - Removed 10 unused imports
- **Copy button UX** - Moved to bottom of message bubble (matches VSCode)

---

## What's New

### 1. AI Tool Integration - `display_file` Tool ⭐ NEW FEATURE

**Feature:**
AI can now proactively display files in the split view after creating or modifying them, improving the user experience by automatically showing relevant artifacts.

**Use Cases:**
- **After code generation**: AI shows the generated file in split view
- **After file editing**: AI displays the modified file for review
- **Reference files**: AI can show relevant documentation or config files during conversation

**How It Works:**
```
User: "Create a FastAPI endpoint for user authentication"
AI: *generates auth.py*
AI: *calls display_file tool*
Result: auth.py opens in split view with syntax highlighting
```

**Implementation:**
- New built-in tool: `display_file` (ppxai/engine/tools/builtin/display.py)
- Reuses existing `/show` command infrastructure across all clients
- DISPLAY_FILE event emitted by chat.py after successful tool execution
- Works in TUI, VSCode, and Web App (all have `/show` handlers)

**Technical Details:**
```python
# Tool definition
{
    "name": "display_file",
    "description": "Display a file in the split view panel",
    "parameters": {
        "filepath": "Path to file (relative or absolute)"
    }
}

# Event flow
AI → display_file tool → chat.py emits DISPLAY_FILE event → Client handlers execute /show

# Event emission (ppxai/engine/chat.py)
if tool_name == "display_file" and "filepath" in tool_args:
    yield Event(EventType.DISPLAY_FILE, {"filepath": resolved_path})

# Client handlers
# - ppxaide (Textual): _on_display_file() → executes /show command
# - ppxai (Rich): EventType.DISPLAY_FILE → executes /show command
# - VSCode: Receives via SSE → opens in native editor
# - Web: Receives via SSE → Monaco editor with syntax highlighting
```

**Why This Works:**
All clients already have `/show` command support:
- **ppxaide (Textual TUI)**: Receives DISPLAY_FILE → executes `/show` → FileViewResult → side panel
- **ppxai (Rich TUI)**: Receives DISPLAY_FILE → executes `/show` → RichRenderer → console display
- **VSCode**: Receives DISPLAY_FILE via SSE → opens in native editor
- **Web**: Receives DISPLAY_FILE via SSE → Monaco editor with syntax highlighting

The tool leverages existing `/show` infrastructure instead of creating parallel event systems.

**Architecture:**
- Tools return strings (can't yield events directly)
- chat.py detects display_file execution and yields DISPLAY_FILE event
- Event contains resolved filepath for client handlers
- No callback mechanism needed - standard event stream flow

---

## What's Fixed

### 2. ppxaide TUI - Event Loop Blocking During Streaming ⭐ CRITICAL FIX

**Problem:**
The `async for` loop in `_stream_response()` blocked Textual's event loop while waiting for HTTP responses from AI providers (30+ second waits). During this time:
- Screen appeared frozen
- Scroll events not processed
- Status bar updates didn't render
- Input felt unresponsive

**Root Cause:**
Engine client's HTTP streaming didn't properly yield to event loop during network waits, even though marked as async.

**Attempted Fixes:**
- ❌ `asyncio.create_task()` - still blocks in same event loop
- ❌ `loop.run_in_executor()` - can't update Textual widgets from thread
- ❌ Explicit `asyncio.sleep(0)` - HTTP client doesn't yield between calls
- ❌ Custom `queue.Queue` + `set_interval()` consumer - over-engineered

**Final Solution:**
✅ **Textual's `call_from_thread()`** - Native framework pattern for thread-safe UI updates
- Worker thread runs HTTP streaming without blocking main event loop
- Uses `self.call_from_thread()` to schedule UI updates in main thread
- UI stays responsive: scrolling, history navigation, etc. all work during streaming
- Input box disabled during streaming to prevent concurrent request race conditions

**Implementation:**
```python
# Thread: _stream_response_thread() creates event loop, runs _stream_response()
thread = threading.Thread(
    target=self._stream_response_thread,
    args=(message, self._engine_client),
    daemon=True
)
thread.start()

# Events: self.call_from_thread(self._handle_stream_event, type, data)
# Completion: self.call_from_thread(self._handle_stream_end)
# Errors: self.call_from_thread(self._handle_stream_error, msg)
```

**Concurrency Protection:**
- Submission blocked during streaming (notification shown if attempted)
- Input box remains enabled - users can type, navigate history, prepare next prompt
- Prevents overlapping requests that would confuse the AI provider

### 3. Footer Status Widget - Live Progress Indicator

**New Features:**
- **"⏳ Thinking..." status** - Shows when request sent, before first chunk arrives
- **"● Streaming response..." status** - Shows during content generation
- **Live elapsed timer** - Updates every 100ms, shows time in seconds (e.g., "12.3s")
- **"Ready" idle state** - Clear feedback when AI is not active

**CSS Layout:**
```css
FooterStatus {
    height: 1;
    background: $surface-darken-1;
    color: $warning;
    padding: 0 1;
}
```

**Timer Implementation:**
```python
def set_thinking(self) -> None:
    """Show 'Thinking...' indicator and start timer."""
    # Stop existing timer if any (prevent multiple timers)
    if self._timer is not None:
        self._timer.stop()

    self.status_message = "⏳ Thinking..."
    self._start_time = time.time()
    self.elapsed_time = 0.0
    # Update timer every 100ms
    self._timer = self.set_interval(0.1, self._update_timer)
```

### 4. CPU Usage Fix - Timer Cleanup Safeguard

**Problem:**
Runaway ppxaide process consuming 98.8% CPU due to accumulating timers.

**Root Cause:**
Multiple timers accumulating when `set_thinking()` called without stopping previous timer.

**Fix:**
Added safeguard to stop existing timer before starting new one:
```python
# Stop existing timer if any (prevent multiple timers)
if self._timer is not None:
    self._timer.stop()
```

**Result:**
CPU usage dropped to 0.0% when idle.

### 5. VSCode Extension - Unused Imports Cleanup

**File:** `vscode-extension/src/chatPanel.ts`

**Removed Imports:**
- `SLASH_COMMANDS` - only imported, never used
- `isAIForwardedCommand` - only imported, never used
- `parseCommand` - only imported, never used
- `formatToolsStatus` - only imported, never used
- `formatToolsList` - only imported, never used
- `formatToolConfig` - only imported, never used
- `formatToolHelp` - only imported, never used
- `formatAgentStatus` - only imported, never used
- `formatCheckpointStatus` - only imported, never used
- `formatCheckpointList` - only imported, never used

**Verification:**
- ✅ TypeScript compilation successful with 0 warnings
- ✅ All remaining imports actively used in the code

### 6. Consent Response Normalization - Unified Across All Clients

**Problem:**
Consent responses were inconsistent across clients:
- TUI dialogs returned "yes"/"no" but engine expected "y"/"n"
- Some clients used full words ("yes", "always"), others abbreviations ("y", "a")
- Case sensitivity issues ("YES" vs "yes" vs "Yes")
- Manual conversion in each client was error-prone

**Solution:**
Created `normalize_consent_response()` function in [ppxai/common/consent.py](ppxai/common/consent.py) that accepts all variations:

```python
normalize_consent_response("yes") → "y"
normalize_consent_response("YES") → "y"
normalize_consent_response("y") → "y"
normalize_consent_response("always") → "always"
normalize_consent_response("ALWAYS") → "always"
normalize_consent_response("no") → "n"
normalize_consent_response("N") → "n"
```

**Updated Clients:**
- **ppxaide (Textual TUI)**: `_show_consent_dialog()` now uses normalization
- **ppxai (Rich TUI)**: `tui_consent_handler()` and `tui_shell_consent_handler()` use normalization
- **HTTP Server**: `/consent` and `/shell-consent` endpoints normalize before resolving
- **All clients**: Consistent behavior regardless of user input format

**Benefits:**
- Users can type "yes", "Yes", "YES", "y", or "Y" - all work
- No more "permission denied" bugs due to response format mismatch
- Single source of truth for consent response handling
- Future clients automatically get consistent behavior

### 7. Copy Button Layout - Matches VSCode UX

**Change:**
Moved copy button from message header to message footer (bottom-right).

**Before:**
```
[🤖 Assistant 12:34] [📋]  <- Header with button
Message content here...
```

**After:**
```
[🤖 Assistant 12:34]        <- Header (no button)
Message content here...
              [📋 Copy]     <- Footer with button
```

**CSS:**
```css
/* v1.15.1: Message footer with copy button (matches VSCode layout) */
MessageBox .message-footer {
    height: 1;
    width: 100%;
    layout: horizontal;
    margin: 1 0 0 0;
    align: right middle;
}

MessageBox .copy-btn {
    width: 8;
    min-width: 8;
    height: 1;
    padding: 0 1;
}
```

### 8. Rich TUI - DISPLAY_FILE Event Handler Fix

**Problem:**
When AI called `display_file` tool in Rich TUI (ppxai), the DISPLAY_FILE event handler failed with:
- `✗ Engine client not available` - /show command requires engine_client to get working directory
- `RichRenderer() takes no arguments` - RichRenderer uses class method dispatch, not instantiation

**Root Causes:**
1. **Missing engine_client**: TUIEventHandler was created without access to engine_client, but /show command requires it (line 142 checks, line 176 uses `get_working_dir()`)
2. **Wrong renderer pattern**: Code tried to instantiate RichRenderer (`RichRenderer(console)`) instead of using class method (`RichRenderer.render(result)`)

**Fixes:**
1. Added optional `engine_client` parameter to `TUIEventHandler.__init__()`
2. Updated all instantiation sites to pass engine_client:
   - `ppxai/rich/main.py:748` - Pass `handler.engine_client`
   - `ppxai/commands/agent.py:632` - Pass `context.engine_client`
3. Updated DISPLAY_FILE event handler to:
   - Pass engine_client to SimpleContext
   - Use `RichRenderer.render(result)` class method

**Implementation:**
```python
# TUIEventHandler with engine_client support
def __init__(self, console, logger, verbose=False, theme_name=None,
             emoji_mode=False, engine_client=None):
    self.engine_client = engine_client  # for /show command

# DISPLAY_FILE event handler
class SimpleContext:
    def __init__(self, console, engine_client):
        self.console = console
        self.engine_client = engine_client  # Now available

context = SimpleContext(self.console, self.engine_client)
result = spec.handler(context, filepath)
RichRenderer.render(result)  # Class method - no instantiation
```

**Result:**
✅ display_file tool now works in Rich TUI
✅ File contents displayed with syntax highlighting
✅ All 1105 tests passing

---

## Breaking Changes

None. This is a bug-fix release with no API or configuration changes.

---

## Upgrade Notes

### From v1.15.0

No migration steps required. All v1.15.0 features continue to work as expected.

### From v1.14.x or Earlier

First upgrade to v1.15.0, then upgrade to v1.15.1. See [RELEASE-NOTES-v1.15.0.md](RELEASE-NOTES-v1.15.0.md) for v1.15.0 upgrade instructions.

---

## Testing Summary

### Test Results

```
All 1105 tests passed in 68.70s
TypeScript compilation: 0 warnings
```

### Manual Testing Checklist

- [x] UI stays responsive during 30+ second streaming responses
- [x] Scrolling works during streaming
- [x] Footer status shows live elapsed timer
- [x] CPU usage remains at 0% when idle
- [x] Copy button appears at bottom of messages
- [x] VSCode extension compiles without warnings

---

## Known Issues

None. All reported issues in v1.15.1 scope have been resolved.

---

## Download

**Binaries:**
- `ppxai-linux-amd64` - TUI for Linux
- `ppxai-macos-arm64` - TUI for macOS (Apple Silicon)
- `ppxai-macos-intel` - TUI for macOS (Intel)
- `ppxai-windows.exe` - TUI for Windows
- `ppxai-server-{platform}` - HTTP server binaries
- `ppxai-desktop-{platform}` - Desktop web app binaries

**VSCode Extension:**
- `ppxai-1.15.1.vsix` - Install via `code --install-extension ppxai-1.15.1.vsix`

**macOS Installer:**
- `ppxai-1.15.1-macos-arm64.dmg` - Drag-and-drop app bundle

---

## Contributors

- ppxai development team

---

## References

- Previous release: [v1.15.0](https://github.com/rcconsult/ppxai/releases/tag/v1.15.0)
- Issue tracker: https://github.com/rcconsult/ppxai/issues
- Documentation: https://github.com/rcconsult/ppxai/tree/master/docs
