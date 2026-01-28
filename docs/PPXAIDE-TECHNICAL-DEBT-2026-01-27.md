# ppxaide Technical Debt & Incomplete Implementation Analysis

**Date:** 2026-01-27
**Branch:** `feature/new-tui-command`
**Commit:** 186f910

## 1. Code Changes in Last 48h Impacting ppxai/ppxaide

**Committed changes:** Mostly documentation updates. No core code changes since `911c3a6` (revert autocomplete).

**Changes committed in 186f910:**

| File | Change |
|------|--------|
| `ppxai/commands/factory.py` | Added `generate_help()` and `get_command_help()` for dynamic help |
| `ppxai/commands/handler.py` | Added `/<cmd> help` → `/help <cmd>` redirect |
| `ppxai/commands/system.py` | `/help` now uses CommandFactory, supports `/help <command>` |
| `ppxai/common/file_type.py` | Switched from python-magic to `filetype` library (PyInstaller fix) |
| `ppxai/tui/app.py` | **Major:** Consent dialog callbacks, debug logging, STREAM_END fix |
| `ppxai/tui/themes/dialog.tcss` | Dark overlay background for modals |
| `ppxai/tui/themes/layout.tcss` | Header/Footer/StatusBar color tweaks |
| `ppxai/tui/widgets/dialog.py` | DEFAULT_CSS for ConsentDialog styling |
| `ppxai/tui/widgets/message_box.py` | Added timestamps like Rich TUI |

---

## 2. Technical Debt & Incomplete Implementation Review

Based on `docs/FEATURE-PARITY-ANALYSIS.md` and code inspection:

### CRITICAL (Blocking Basic Functionality)

| Issue | Status | File | Problem |
|-------|--------|------|---------|
| **AI Responses Not Displayed** | BROKEN | `ppxai/tui/app.py:891-920` | STREAM_END.data ignored when no chunks accumulated (non-streaming providers) |
| **Tool Consent Broken** | BROKEN | `ppxai/tui/app.py:257-298` | Consent callbacks wired but **not being triggered** - needs debugging |
| **Tab Autocomplete** | DISABLED | `ppxai/tui/widgets/input_box.py` | Disabled in 87785e9 - needs complete refactoring |

### MEDIUM (Feature Gaps)

| Issue | Status | Files | Notes |
|-------|--------|-------|-------|
| Status bar toggles | ✅ DONE | `app.py` lines 1165-1198 | `/status version/cwd/datetime` toggles working |
| Agent mode badge | ✅ DONE | `app.py` lines 1137-1155 | Shows "Agent: ACTIVE" when enabled |
| Checkpoint badge | ✅ DONE | `app.py` lines 1142-1151 | Shows ↶ (valid) or ↶! (stale) |
| Reasoning tokens | Not impl | N/A | DeepSeek R1 / GPT-OSS thinking display |
| @file completion | Not impl | `completer.py` | Disabled with autocomplete |
| @clipboard/@url | Not impl | N/A | Context providers |

### LOW (Polish/Enhancement)

| Issue | Notes |
|-------|-------|
| Emoji mode | Rich-only feature, not critical |
| Debug log display | `/debug-log show` works but could be improved |
| Auto-save interval | Config-based, mostly working |

---

## 3. ppxai/tui Code Structure (31 Python files)

```
ppxai/tui/
├── __init__.py          # Entry point, main()
├── app.py               # PPXAIDEApp - CORE (1500+ lines, needs refactoring)
├── clipboard.py         # Clipboard utilities
├── commands.py          # TUI-specific command handlers
├── completer.py         # Tab completion (DISABLED)
├── hyperlinks.py        # Hyperlink support
├── images.py            # Image handling utilities
├── terminal.py          # Terminal detection
├── validation.py        # Input validation
├── screens/             # Full-screen views
│   ├── editor.py        # File editor screen
│   └── viewer.py        # File viewer screen
├── themes/              # Theme system
│   ├── themes.py        # Theme definitions (17+ themes)
│   ├── layout.tcss      # Main layout CSS
│   └── dialog.tcss      # Dialog CSS
└── widgets/             # Reusable widgets (14 files)
    ├── chat_view.py     # Message display
    ├── code_editor.py   # Syntax-highlighted editor
    ├── data_viewer.py   # Tree/JSON viewer
    ├── dialog.py        # Modal dialogs
    ├── image_viewer.py  # Image display
    ├── input_box.py     # User input
    ├── message_box.py   # Chat bubbles
    ├── side_panel.py    # Collapsible panel
    ├── status_bar.py    # Status badges
    ├── table_viewer.py  # CSV/TSV display
    └── tree_viewer.py   # Tree widget
```

---

## 4. Root Cause of Current Issues

The **consent dialog and streaming issues** share a common problem:

1. **Consent callbacks are wired** in `_initialize_engine()` but the EngineClient may not be invoking them properly during tool execution
2. **Non-streaming providers** (like GPT-OSS) may send the full response in `STREAM_END.data` instead of streaming chunks
3. The **event handling chain** needs debugging: `EngineClient.chat()` → events → `_handle_event()` → display

---

## 5. Recommended Next Steps

Before adding more features, focus on fixing the core chat loop:

1. **Add debug logging** to trace where responses get lost
2. **Test with a simple provider** (ollama local) first
3. **Verify consent callback invocation** with logging
4. **Build ppxaide.exe** and test interactively

### Debugging Checklist

- [ ] Verify EngineClient receives chat messages
- [ ] Trace event emission from provider
- [ ] Confirm STREAM_CHUNK vs STREAM_END handling
- [ ] Test consent callback invocation path
- [ ] Check if modal dialog blocks event loop

---

## 6. Key Files to Review

| Priority | File | Why |
|----------|------|-----|
| 1 | `ppxai/tui/app.py` | Core app, consent handlers, streaming |
| 2 | `ppxai/engine/client.py` | EngineClient, consent callback wiring |
| 3 | `ppxai/engine/tools/manager.py` | Tool execution, consent invocation |
| 4 | `ppxai/tui/widgets/dialog.py` | ConsentDialog implementation |
| 5 | `ppxai/tui/widgets/chat_view.py` | Message display |

---

## 7. Config Notes

Current user config (`~/.ppxai/ppxai-config.json`):
- `native_tool_calling: false` for custom provider (GPT-OSS)
- `auto_restore: "prompt"` for session management
- `show_datetime: true` in TUI config

---

## 8. Reference Documents

- `docs/FEATURE-PARITY-ANALYSIS.md` - Full feature comparison
- `docs/WIP-v1.15.0-FEATURE-PARITY.md` - Work in progress tracking
- `docs/RELEASE-NOTES-v1.15.0.md` - Release notes
- `CLAUDE.md` - Project context and guidelines
