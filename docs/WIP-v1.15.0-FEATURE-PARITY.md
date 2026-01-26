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

## TODO: Phase 1 - Critical Missing Features (User-Visible)

### 1.1 Tab Autocomplete
- [ ] Command completion (slash commands)
- [ ] @file/@clipboard/@url context providers
- [ ] File path completion with ignore patterns (.git, node_modules, __pycache__, .venv)
- [ ] Model/provider name completion
- [ ] Subcommand completion (tools, usage, checkpoint, status, theme)

**Reference:** `ppxai/rich/main.py:PPXAICompleter` class

### 1.2 Status Bar Toggles
- [ ] `/status version` - toggle version display
- [ ] `/status cwd` - toggle working directory display
- [ ] `/status datetime` - toggle date/time display

**Reference:** Rich TUI has these in `ppxai/rich/ui_components.py`

### 1.3 Agent Mode Badges
- [ ] Agent mode indicator badge
- [ ] Checkpoint status badge (↶ valid, ↶! stale)

**Reference:** `ppxai/rich/ui_components.py:render_status_panel()`

### 1.4 Reasoning Token Display
- [ ] DeepSeek R1 reasoning tokens
- [ ] GPT-OSS thinking display
- [ ] Collapsible reasoning sections

**Reference:** `ppxai/rich/event_handler.py:on_reasoning_chunk()`

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
