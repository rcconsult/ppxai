# Work In Progress: v1.15.0 Feature Parity

**Branch:** `feature/new-tui-command`
**Last Updated:** 2026-01-26
**Status:** In Progress

## Completed This Session

- [x] Type-based file display migration for /show command
- [x] TreeResult uses DataViewer with Ctrl+V toggle (tree ↔ source)
- [x] TableResult uses TableViewer with Ctrl+V toggle (table ↔ source)
- [x] MarkdownResult renders in side panel
- [x] ImageResult uses ImageViewer
- [x] FileViewResult uses CodeEditor
- [x] python-magic dependency for file type detection
- [x] All 1105 tests passing
- [x] FEATURE-PARITY-ANALYSIS.md created

---

## Phase 1 - Critical Missing Features (User-Visible) ✅ COMPLETED

### 1.1 Tab Autocomplete ✅
- [x] Command completion (slash commands) - All 30+ commands from CommandFactory
- [x] @file/@clipboard/@url context providers - With descriptions
- [x] File path completion with ignore patterns (.git, node_modules, __pycache__, .venv)
- [x] Model/provider name completion - Dynamic from config
- [x] Subcommand completion (tools, usage, checkpoint, status, theme)

**Implementation:**
- `ppxai/tui/completer.py` - TextualCompleter with 440 lines of completion logic
- `ppxai/tui/widgets/completion_popup.py` - Visual popup widget with arrow key navigation
- Press Tab to show completions, arrow keys to navigate, Enter/Tab to select
- File cache with 5-second TTL for performance
- **Commit:** 4400480

### 1.2 Status Bar Toggles ✅
- [x] `/status version` - toggle version display (v1.15.0)
- [x] `/status cwd` - toggle working directory display (ppxai/utils)
- [x] `/status datetime` - toggle date/time display (2026-01-26 20:30)

**Implementation:**
- Config stored in `ppxai-config.json` under `tui.show_version`, `show_cwd`, `show_datetime`
- Badges added on app startup from config
- Toggle commands update config and show/hide badges dynamically
- DateTime badge updates every minute when enabled

### 1.3 Agent Mode Badges ✅
- [x] Agent mode indicator badge - Shows "Agent: ACTIVE" in green
- [x] Checkpoint status badge (↶ valid, ↶! stale) - Unicode arrows

**Implementation:**
- Agent badge shows when `/agent on` is executed
- Checkpoint badge shows ↶ for valid checkpoint (undo available)
- Checkpoint badge shows ↶! for stale checkpoint (undo may not work)
- Badges update dynamically when agent mode changes

### 1.4 Reasoning Token Display
- [ ] DeepSeek R1 reasoning tokens - DEFERRED (not in Rich TUI yet)
- [ ] GPT-OSS thinking display - DEFERRED (requires special handling)
- [ ] Collapsible reasoning sections - DEFERRED

**Note:** Reasoning token display is not yet implemented in Rich TUI either, so this is not a parity gap. Will be added in future version when provider support is more mature.

---

## TODO: Phase 2 - Consistency Fixes

### 2.1 Debug Log Display
- [ ] Show debug log output in TUI (side panel or chat)
- [ ] `/debug-log [on|off]` command integration

### 2.2 Tools Config
- [ ] Verify `/tools config` works correctly in Textual TUI

### 2.3 Auto-save Interval
- [ ] Implement configurable auto-save interval
- [ ] Match Rich TUI behavior

### 2.4 Crash Recovery
- [ ] Dirty session detection
- [ ] Crash recovery prompt on startup

---

## TODO: Phase 3 - Rich-Only Features (Consider Adding)

### 3.1 Emoji Mode (Optional)
- [ ] Text symbol fallback for terminal alignment
- [ ] `/theme emoji on|off` command

---

## TODO: Release Prep

- [ ] Run full test suite
- [ ] Update CHANGELOG.md for v1.15.0
- [ ] Create release notes: `docs/RELEASE-NOTES-v1.15.0.md`
- [ ] Version bump in all files
- [ ] Merge to master

---

## Files Modified in This Work

| File | Changes |
|------|---------|
| `ppxai/common/file_type.py` | NEW - File type detection |
| `ppxai/common/__init__.py` | Export file_type module |
| `ppxai/commands/display.py` | /show returns typed results |
| `ppxai/commands/results.py` | Add MarkdownResult |
| `ppxai/rendering/textual_renderer.py` | Use DataViewer/TableViewer |
| `ppxai/rendering/rich_renderer.py` | Add MarkdownResult renderer |
| `ppxai/tui/themes/layout.tcss` | Markdown styles for SidePanel |
| `pyproject.toml` | Add python-magic dependency |
| `tests/test_tui.py` | Update test assertions |
| `docs/FEATURE-PARITY-ANALYSIS.md` | Full comparison document |

---

## Quick Start for Next Session

```bash
# Checkout the branch
git checkout feature/new-tui-command
git pull

# Sync dependencies
uv sync --all-extras

# Run tests to verify state
uv run pytest tests/test_commands.py tests/test_tui.py -v

# Build and test TUI
uv run ppxaide
```

---

## Reference Documents

- [FEATURE-PARITY-ANALYSIS.md](FEATURE-PARITY-ANALYSIS.md) - Full comparison
- [TUI-COMMAND-REFACTORING-PLAN.md](TUI-COMMAND-REFACTORING-PLAN.md) - Architecture plan
- [ARCHITECTURE.md](ARCHITECTURE.md) - Transactional state pattern
