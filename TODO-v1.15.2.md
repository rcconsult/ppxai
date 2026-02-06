# TODO: v1.15.2 Planned Improvements

**Created:** 2026-01-30
**Branch:** feature/1-15-2
**Status:** In Progress
**Previous Release:** v1.15.1

---

## Planned Features

### 1. Gemini Native Tool Calling Support

**Priority:** Medium
**Status:** ✅ Done

**Implemented:**
- Native function calling enabled by default (`native_tool_calling=True` in capabilities)
- ppxai tools converted from OpenAI format to Gemini `function_declarations`
- `TOOL_CALL` events emitted for function calls (streaming and non-streaming)
- `_convert_tools_to_gemini()` converts OpenAI tool format to Gemini format
- `_parse_function_call()` extracts tool calls from response parts
- Backward compatible - prompt-based mode still works if `native_tool_calling=False`

**Limitation (Gemini Standard API constraint):**
- Multi-tool use (combining GoogleSearch + function_declarations) is **Live API only**
- Standard `generate_content` API returns 400 INVALID_ARGUMENT if both are used
- When ppxai tools are enabled, native function calling takes priority
- Grounding is automatically disabled when tools are active
- Reference: https://ai.google.dev/gemini-api/docs/live-tools

**Workaround for agent mode web search:**
- `web_search` tool now available for Gemini in agent mode (removed from exclusion list)
- Uses premium web search (Perplexity → Gemini grounding API → DuckDuckGo fallback)
- Agent can call `web_search(query)` which makes separate grounding-only API call
- No user action needed - works automatically

**Files Updated:**
- `ppxai/engine/providers/gemini.py` - Full native tool calling implementation
- `ppxai/engine/tools/builtin/web_premium.py` - Removed Gemini from exclusion list

**Key Changes:**
- `default_capabilities` now includes `native_tool_calling=True`
- `_build_config()` accepts `tools` parameter and creates `function_declarations`
- Streaming and non-streaming paths handle `function_call` parts
- Tool calls emitted as `EventType.TOOL_CALL` with `native=True` flag

---

## Backlog

### 2. NvChad-Style File Tree for ppxaide

**Priority:** Medium
**Status:** ⏳ Planned

**Current State:**
- ppxaide has no built-in file browser or project explorer
- Users must use `/show` command or `@file` context injection to view files
- No visual directory navigation in the TUI

**Goal:**
Implement a NvChad-inspired file tree explorer for ppxaide:
- **File/folder icons** - Visual indicators for file types and directories
- **Expandable tree** - Click to expand/collapse folders
- **Clean hierarchy** - Indented structure with clear parent-child relationships
- **Keyboard navigation** - Arrow keys, Enter to open, Space to expand
- **Integration** - Open files in CodeEditor side panel on selection
- **Git awareness** - Show modified/untracked files (optional)

**Implementation Notes:**
- Use Textual's `DirectoryTree` widget as base
- Add custom rendering for icons (Nerd Font support or Unicode fallbacks)
- Integrate with existing CodeEditor widget
- Add keybinding to toggle file tree (e.g., Ctrl+B)
- Consider file filtering (hide .git, __pycache__, etc.)
- Respect .gitignore patterns

**Files to Update:**
- `ppxai/tui/widgets/` - Create `file_tree.py` widget
- `ppxai/tui/app.py` - Add file tree panel to layout
- `ppxai/tui/widgets/code_editor.py` - Handle file tree selection events

**Testing:**
- Test with large repositories (performance)
- Test icon rendering across different terminals
- Verify keyboard navigation
- Test file opening integration with CodeEditor

**Reference:**
- NvChad file tree screenshot (user-provided)
- Textual DirectoryTree: https://textual.textualize.io/widgets/directory_tree/
- Nerd Fonts for icons: https://www.nerdfonts.com/

---

### 3. Verify display_file Tool in Web App and VSCode

**Priority:** High
**Status:** ✅ **COMPLETE** (v1.15.2)

**Current State:**
- `display_file` tool was added in v1.15.1 for AI to proactively show files
- Tool emits DISPLAY_FILE event after successful execution
- ppxaide (Textual TUI) handles the event and opens files in side panel
- **Web App:** ✅ WORKING - Files open in Monaco editor correctly
- **VSCode:** ❌ NOT WORKING - Debug logs show issue with event handling

**Goal:**
Fix display_file tool integration in VSCode extension:
- **Web App** - ✅ Confirmed working with Monaco editor
- **VSCode** - ❌ Needs fix - debug logs enabled, investigating event handler
- **Error handling** - Verify graceful degradation if file doesn't exist
- **Event flow** - DISPLAY_FILE events propagate correctly through HTTP/SSE

**Testing Checklist:**
- [x] Test display_file tool in Web App with agent mode ✅ WORKING
- [x] Test display_file tool in VSCode extension with agent mode ✅ **WORKING - VERIFIED**
- [x] Verify file paths (relative vs absolute) work correctly ✅ Server resolves paths correctly
- [x] Test with non-existent files (error handling) ✅ Gracefully fails silently
- [x] Test with binary files (images, PDFs) ✅ VSCode handles natively
- [x] Verify event is emitted after tool execution completes ✅ WORKING
- [x] Check server logs for DISPLAY_FILE event transmission ✅ WORKING

**Deployment & Testing (2026-02-06 15:10):**
- ✅ VSCode extension v1.15.2 packaged and installed (ppxai-1.15.2.vsix, 1.1MB)
- ✅ ppxai-server.exe rebuilt and deployed to `~/.ppxai/bin/` (44MB)
- ✅ BUGFIX: Added missing `display_file` case in `mapServerEvent()` - was returning null!
- ✅ **USER TESTED:** File successfully displayed in VSCode split view (ViewColumn.Beside)
- ✅ Debug logging removed (clean production code)

**Root Cause (Discovered):**
The `httpClient.ts:mapServerEvent()` function had no case for `'display_file'`, so it was
returning `null` instead of creating a StreamEvent. The event was received from server but
silently dropped before reaching the stream handler. Fix: Added case that maps server's
`event.data` (containing `{filepath: string}`) to StreamEvent's `metadata` field.

**Files to Check:**
- `ppxai/engine/tools/builtin/display.py` - Tool implementation ✅
- `ppxai/engine/chat.py` - DISPLAY_FILE event emission (lines 389-409) ✅
- `ppxai/server/http.py` - Event streaming to clients ✅
- `vscode-extension/src/chatPanel.ts` - VSCode event handler ❌ MISSING
- `ppxai/web/app.js` - Web App event handler ✅ WORKING (lines 982-987, 3128-3155)

**Root Cause Analysis:**
1. Server emits `EventType.DISPLAY_FILE` with `{"filepath": str(path)}` ✅
2. Web app handles `case 'display_file'` in `handleStreamEvent()` ✅
3. VSCode `stream.ts` has NO case for `display_file` event ❌
4. VSCode `eventBus.ts` has NO event type for display_file ❌
5. VSCode `chatPanel.ts` has NO subscriber for display_file ❌

**Fix Applied (v1.15.2):**
- ✅ Added `'stream:display_file': (filepath: string) => void` to StreamEvents interface (eventBus.ts:69)
- ✅ Added `case 'display_file'` to processStreamEvent() in stream.ts (lines 51-53)
- ✅ Added `processDisplayFile()` helper function in stream.ts (lines 160-173)
- ✅ Added subscriber in chatPanel.ts to open file in VSCode editor (lines 200-211)
- Opens file in `ViewColumn.Beside` (split view, not replacing current file)

**Expected Behavior:**
1. AI calls `display_file(filepath="path/to/file.py")`
2. Tool validates file exists and returns success message
3. `chat.py` emits DISPLAY_FILE event with resolved path
4. Server streams event to client via SSE
5. Client opens file in appropriate viewer/editor

**Reference:**
- display_file implementation: `ppxai/engine/tools/builtin/display.py:44-94`
- Event emission: Added in v1.15.1 (check chat.py for DISPLAY_FILE)
