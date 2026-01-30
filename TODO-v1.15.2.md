# TODO: v1.15.2 Planned Improvements

**Created:** 2026-01-30
**Branch:** TBD
**Status:** Planning
**Previous Release:** v1.15.1

---

## Planned Features

### 1. Gemini Native Tool Calling Support

**Priority:** Medium
**Status:** ⏳ Planned

**Current State:**
- Gemini provider uses prompt-based tool calling (tools described in system message)
- Only Google Search Grounding is passed as a native Gemini tool
- Other ppxai tools (search_files, read_file, etc.) are NOT passed as Gemini function definitions
- The `native_tool_calling` config option has no effect on Gemini provider

**Goal:**
Implement native Gemini function calling API support to:
- Pass ppxai tools as proper Gemini function definitions
- Allow Gemini to use structured tool calling instead of prompt-based
- Improve tool call reliability and reduce hallucination
- Support both grounding AND native tools simultaneously

**Implementation Notes:**
- Update `ppxai/engine/providers/gemini.py` to support native function calling
- Check the `native_tool_calling` config option and switch between modes
- Convert ppxai tool definitions to Gemini's function calling format
- Test compatibility with grounding enabled
- Ensure backward compatibility with prompt-based mode

**Files to Update:**
- `ppxai/engine/providers/gemini.py` - Add native tool calling logic
- Config docs to explain the difference between modes

**Testing:**
- Test with grounding enabled + native tools
- Test with grounding disabled + native tools
- Verify backward compatibility with prompt-based mode
- Test across different Gemini models (2.0, 2.5, 3.0)

**Reference:**
- User config: `~/.ppxai/ppxai-config.json` - Gemini section
- Current workaround: Using `generation_params` with `temperature: 0.2` for better prompt-based tool calling

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
