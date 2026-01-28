# Release Plan: v1.15.x Series

**Created:** January 24, 2026
**Last Updated:** January 28, 2026 (Phase 7 Complete - Ready for Release)
**Status:** ✅ COMPLETE - Ready for Merge to Master
**Branch:** feature/new-tui-command
**Tests:** 1105 passing

---

## Theme: Next Generation TUI (ppxaide)

**Tagline:** Textual-based TUI replacing Rich-based TUI as the primary terminal interface

## Overview

The v1.15.x series introduces `ppxaide` - a new terminal UI built on the Textual framework. This replaces the current Rich-based TUI (`ppxai`) which has reached its feature ceiling due to framework limitations.

**Why a new TUI?**
- Rich framework cannot handle proper editor workflows (keyboard input, cursor navigation)
- No mouse support in Rich-based TUI
- Limited widget-based composition
- CSS theming not possible with Rich

## Release Strategy

**v1.15.0** is a comprehensive release that ships when ready. It includes:
- All UI platform work (widgets, themes, layouts)
- Visual validation (stress tests, edge cases)
- Data visualization widgets (DataViewer, ImageViewer, TableViewer)
- Engine integration (EngineClient, streaming, commands)
- Full feature parity with Rich TUI
- Polish and performance optimization

**v1.15.1** - Bug fixes and cross-platform validation

**v1.15.2** - Additional features after stabilization:
- PDFViewer widget (PyMuPDF integration, cross-platform tested)
- Cursor position preservation across view toggles (DataViewer, TableViewer) - *if requested by users*

**Philosophy:** Validate the new Textual framework thoroughly before connecting to the proven engine layer.
The engine is already battle-tested in Rich TUI, Web App, and VSCode. What's new is the UI.

**Migration Path:**
- v1.15.0: ppxaide launches as separate command (`ppxaide` vs `ppxai`)
- v1.16.x: ppxaide becomes `ppxai`, old TUI deprecated

## Architecture

```
ppxai/tui/                     # New module (Textual-based)
├── __init__.py                # Entry point: ppxaide command
├── app.py                     # PPXAIDEApp(textual.App)
├── widgets/                   # Custom widgets
│   ├── chat_view.py           # Chat message container
│   ├── message_box.py         # Individual message display
│   ├── streaming.py           # Streaming response widget (TODO)
│   ├── status_bar.py          # Status badges (provider, model, context)
│   └── input_box.py           # Multi-line input with history
├── screens/                   # Application screens (TODO)
└── themes/                    # Theme system
    ├── __init__.py            # Theme exports
    ├── themes.py              # Custom theme definitions (tron-legacy, matrix)
    └── layout.tcss            # Layout CSS using Textual design tokens
```

**Note:** Uses Textual's 17+ built-in themes (catppuccin-mocha, nord, dracula, etc.)
plus 2 custom themes unique to ppxaide. Ctrl+P shows all themes, Ctrl+T cycles curated list.

**Key Design Decisions:**
- **Separate command** - `ppxaide` coexists with `ppxai` during transition
- **Shared engine** - Uses existing `EngineClient` via composition (no duplication)
- **CSS-first theming** - Leverage Textual's CSS for consistent, maintainable styling
- **Widget composition** - Build complex UI from reusable components
- **Incremental parity** - Match current TUI and Desktop Web App features over multiple releases

## Prerequisites

**v1.14.x Complete:**
- Bootstrap context (AGENTS.md) support
- Context scopes (global, project, subdirectory)
- `/edit` command (VSCode + Web App)
- Documentation site (GitHub Pages)

**Dependencies:**
- `textual>=0.47.0` (added to optional extras)
- Install: `pip install ppxai[tui]`

---

## v1.15.0 Implementation Phases

All phases below are part of v1.15.0. See [tui-side-panel-refactor.md](design/tui-side-panel-refactor.md) for detailed specifications.

---

### Phase 0: Foundation (Complete + In Progress)

**Goal:** Clean codebase with zero technical debt

| Phase | Focus | Status |
|-------|-------|--------|
| 0.0 | Rich TUI isolation (move to `ppxai/rich/`) | ✅ Done |
| 0.1.1 | Error handling cleanup | ✅ Done |
| 0.1.2 | CSS consolidation | ✅ Done |
| 0.1.3 | SafeQueryMixin helper | ✅ Done |
| 0.1.4 | Content factory | ✅ Done |
| 0.1.5 | Input validation | ✅ Done |

---

### Phase 0 (Complete): Platform Widgets

**Previously done work:**

| Feature | Status |
|---------|--------|
| Textual SDK integration | ✅ Done |
| `ppxaide` entry point | ✅ Done |
| 17+ built-in themes + 2 custom | ✅ Done |
| Basic commands (`/help`, `/quit`, `/clear`, `/theme`) | ✅ Done |
| StatusBar with badges | ✅ Done |
| ChatView message display | ✅ Done |
| InputBox multi-line input | ✅ Done |
| TreeViewer widget | ✅ Done |
| CodeEditor widget | ✅ Done |
| SplitPane layouts | ✅ Done |
| Mouse support, clipboard | ✅ Done |
| Basic tests (22 in `tests/test_tui.py`) | ✅ Done |

---

### Phase 1: Core Visual Validation (Complete)

**Goal:** Prove core widgets work reliably before adding complexity

| Test Area | Coverage | Status |
|-----------|----------|--------|
| StatusBar stress test | Rapid updates, long text, Unicode, themes | ✅ Done |
| ChatView scrolling | 1000+ messages, long content, Unicode | ✅ Done |
| InputBox edge cases | History storage, Unicode, multi-line | ✅ Done |
| Theme switching | All themes, syntax highlighting mapping | ✅ Done |
| Keybinding conflicts | No collisions, all actions have methods | ✅ Done |
| MessageBox | Content storage, streaming support | ✅ Done |

**Deliverable:** Core widget tests (96 → 113 with DataViewer tests) proving core widgets work reliably

---

### Phase 2: DataViewer Widget (Complete)

**Goal:** Complex widget for structured data

| Feature | Description | Status |
|---------|-------------|--------|
| Tree mode | JSON/YAML/TOML hierarchical display | ✅ Done |
| Source mode | CodeEditor with syntax highlighting | ✅ Done |
| Toggle | Ctrl+V switches between tree/source | ✅ Done |
| State preservation | View mode state preserved | ✅ Done |
| Large files | Performance with 10K+ nodes tested | ✅ Done |
| Format detection | Auto-detect from file extension | ✅ Done |
| Unicode support | Full Unicode data handling | ✅ Done |

**Deliverable:** DataViewer widget with 17 tests in `tests/test_tui.py`

---

### Phase 3: ImageViewer Widget (Complete)

**Goal:** Terminal image support with graceful degradation

| Feature | Description | Status |
|---------|-------------|--------|
| Fallback mode | File info when library not installed | ✅ Done |
| Full mode | textual-image integration (factory pattern) | ✅ Done |
| Controls | +/- zoom, WASD pan, 0 reset | ✅ Done |
| Properties | path, dimensions, file_size, format, is_loaded | ✅ Done |
| Large files | check_file_size() validation | ✅ Done |
| **Image display fixes** | **CSS selector, aspect ratio, centering** | **✅ Done (commit f777028)** |

**Deliverable:** ImageViewer widget with 15 tests + 21 handler tests in `tests/test_image_handlers.py`

**Critical fixes applied (Jan 25, 2026):**
- Fixed CSS selector: `AutoImage` → `Image` (textual-image uses `Image` class)
- Fixed aspect ratio: `height: 1fr` → `height: auto` (preserve proportions)
- Added vertical centering: Wrapped image in `Center` container
- Images now display correctly without overflow or distortion

---

### Phase 4: Side Panel Integration (Complete)

**Goal:** Unified file viewing experience

| Feature | Description | Status |
|---------|-------------|--------|
| DataViewer integration | Tree/source toggle for JSON/YAML/TOML | ✅ Done |
| ImageViewer integration | Zoom/pan controls for images | ✅ Done |
| `/show` polish | All file types via content factory | ✅ Done |
| `/edit` command | CodeEditor in edit mode | ✅ Done |
| Split pane UX | Resize (Ctrl+[/]), focus switching (F6) | ✅ Done |
| State management | Open/close, content tracking | ✅ Done |

**Deliverable:** 16 integration tests in `tests/test_tui.py` (Total: 144 tests)

---

### Phase 4.5: TableViewer Widget (Complete)

**Goal:** Tabular data display for CSV/TSV files (parity with Desktop Web App)

| Feature | Description | Status |
|---------|-------------|--------|
| DataTable core | Textual's DataTable for grid display | ✅ Done |
| Format support | CSV, TSV, PSV (delimiter detection) | ✅ Done |
| Header detection | Auto-detect heuristics | ✅ Done |
| Table/source toggle | Ctrl+V switches views (like DataViewer) | ✅ Done |
| Column sizing | Auto-width with max 50 chars | ✅ Done |
| Large files | Row limit (1000 initial rows) | ✅ Done |
| SidePanel integration | `/show data.csv` displays table | ✅ Done |

**Deliverable:** 24 TableViewer tests in `tests/test_tui.py` (Total: 168 tests)

---

### Phase 5: End-to-End Validation (Complete)

**Goal:** Prove UI shell works WITHOUT engine

| Phase | Focus | Tests | Status |
|-------|-------|-------|--------|
| 5.1 | Widget lifecycle (mount/unmount, focus, events) | 20 | ✅ Done |
| 5.2 | Theme consistency (all themes, all widgets) | 13 | ✅ Done |
| 5.3 | Keyboard navigation (no dead-ends, focus mgmt) | 16 | ✅ Done |
| 5.4 | Edge cases (empty states, Unicode, large files) | 19 | ✅ Done |
| 5.5 | App integration (commands, multi-widget) | 18 | ✅ Done |

**Deliverable:** 86 comprehensive tests proving UI reliability (Total: 275 tests including image handlers)

**Test Coverage:**
- Platform widgets: 254 tests
- Image handlers: 21 tests (factory pattern, delegation, fallback modes)
- **Total: 275 tests passing**

---

### Phase 6: Engine Integration (Complete ✅)

**Goal:** Connect validated UI to proven backend

**Rationale:** Engine is already battle-tested. Integration is mechanical once UI is stable.

**Status:** ✅ Complete

| Feature | Description | Status |
|---------|-------------|--------|
| Factory pattern | `PPXAIDEApp.initialize()` | ✅ Done |
| Config loading | `get_default_provider()`, etc. | ✅ Done |
| EngineClient | Composition, event subscription | ✅ Done |
| Streaming | Progressive rendering | ✅ Done |
| Provider/model switching | Reactive StatusBar updates | ✅ Done |
| Command handlers | Full parity with Rich TUI | ✅ Done |
| Feature parity | Token usage, cost, context injection | ✅ Done |
| Blinker event bus | Decoupled component communication | ✅ Done |
| Type-based renderer | 17 CommandResult types | ✅ Done |

**Deliverable:** ✅ Fully functional AI assistant

**Key Files to Modify:**
- `ppxai/tui/app.py` - Add `initialize()`, EngineClient composition
- `ppxai/tui/commands.py` - Wire up slash commands to engine
- `ppxai/tui/widgets/chat_view.py` - Stream event handlers
- `ppxai/tui/widgets/status_bar.py` - Reactive provider/model updates

---

### Phase 7: Polish & Release (Complete ✅)

**Goal:** Production-ready v1.15.0

| Task | Description | Status |
|------|-------------|--------|
| Performance | Optimize rendering | ✅ Done |
| Accessibility | Screen reader, high contrast | ✅ Done |
| Documentation | User guide, shortcuts | ✅ Done |
| Cross-platform | Linux, macOS, Windows testing | ✅ Done (1105 tests) |
| Binaries | PyInstaller builds | ✅ Done |
| Release notes | Changelog, migration guide | ✅ Done |
| Copy-to-clipboard | All clients | ✅ Done |
| Generation params | Provider/model settings | ✅ Done |
| Markdown rendering | Chat bubbles | ✅ Done |
| Thinking indicators | Reasoning models | ✅ Done |

**Deliverable:** ✅ v1.15.0 ready for release

---

## Feature Parity Checklist

**Current TUI (`ppxai`) features to port:**

### Core Chat
- [x] Streaming responses with Markdown rendering
- [x] Multi-line input with history
- [x] Provider/model switching mid-session
- [x] Token usage display
- [x] Cost estimation

### Commands
- [x] `/help` - Command reference
- [x] `/model` - Switch model
- [x] `/provider` - Switch provider
- [x] `/tools` - Enable/disable tools
- [x] `/agent` - Start agent mode
- [x] `/consent` - Manage consent settings
- [x] `/session` - Session management
- [x] `/save` - Save session
- [x] `/load` - Load session
- [x] `/export` - Export to markdown
- [x] `/checkpoint` - Checkpoint management
- [x] `/undo` - Revert last agent task
- [x] `/context` - Context management
- [x] `/usage` - Usage statistics
- [x] `/show` - File preview
- [x] `/edit` - File editing (NEW in ppxaide)
- [x] `/theme` - Theme switching
- [x] `/config` - Configuration
- [x] `/clear` - Clear conversation
- [x] `/quit` - Exit application
- [x] `/copy` - Copy to clipboard (NEW in v1.15.0)

### Visual Features
- [x] 17+ color themes (vs 4 in Rich TUI)
- [x] Status bar with badges
- [x] Clickable file links (OSC 8)
- [x] Markdown tables
- [x] Code block syntax highlighting
- [x] Tool call display
- [x] Thinking indicators for reasoning models

### Desktop Web App features to port
- [x] Data viewers (JSON, YAML, TOML) - DataViewer widget
- [x] Data viewers (CSV, TSV) - TableViewer widget
- [x] File editor with syntax highlighting - CodeEditor widget
- [x] Image preview - ImageViewer widget
- [ ] PDF preview - **Deferred to v1.15.2** (requires PyMuPDF, cross-platform testing)

---

## Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| Textual learning curve | Start with simple widgets, iterate |
| Terminal compatibility | Test on major terminals (iTerm2, Windows Terminal, GNOME Terminal) |
| Performance with long conversations | Virtual scrolling, message pagination |
| Feature creep | Strict scope per release, defer nice-to-haves |
| Migration friction | Keep `ppxai` available throughout v1.15.x |

## Success Metrics

### Phase 0-5 (UI Validation) - COMPLETE ✅
- [x] All widgets mount/unmount cleanly (275 tests passing)
- [x] Widget lifecycle tested (mount, unmount, focus, events, state)
- [x] Theme consistency validated (all 17+ themes work)
- [x] Keyboard navigation tested (Tab, Escape, arrows, no dead-ends)
- [x] Edge cases covered (Unicode, large files, empty states, errors)
- [x] App integration verified (commands, multi-widget, state preservation)
- [x] DataViewer tree/source toggle works
- [x] ImageViewer displays correctly (aspect ratio, centering, no overflow)
- [x] ImageViewer fallback modes work (library/terminal/error reasons)
- [x] TableViewer table/source toggle works
- [x] Side panel `/show` and `/edit` work
- [x] Performance acceptable with 1000+ messages (stress tests)
- [x] Handler factory pattern validated (21 tests)
- [x] Terminal capability detection works (iTerm2, Kitty, Sixel)

**Image Display Validation (Jan 25, 2026):**
- [x] textual-image widget integration (uses `Image` class, not `AutoImage`)
- [x] CSS width constraints applied (`width: 100%`, `max-width: 100%`)
- [x] Aspect ratio preserved (`height: auto` instead of `height: 1fr`)
- [x] Vertical centering works (`Center` container with `align: center middle`)
- [x] No horizontal overflow in side panel

### Phase 6-7 (Engine Integration) - COMPLETE ✅
- [x] ppxaide connects to EngineClient
- [x] Streaming responses render correctly
- [x] All slash commands work as expected (32 commands)
- [x] Provider/model switching works
- [x] Full feature parity with Rich TUI
- [x] Works on Linux, macOS, Windows (1105 tests passing)
- [x] Blinker event bus integrated
- [x] Type-based renderer dispatch (17 CommandResult types)
- [x] Copy-to-clipboard across all clients
- [x] Generation parameters support
- [x] Markdown rendering in chat
- [x] Thinking indicators

---

## References

- [Textual Documentation](https://textual.textualize.io/)
- [Textual CSS Reference](https://textual.textualize.io/guide/CSS/)
- [TUI Side Panel Refactor Design Doc](design/tui-side-panel-refactor.md) (detailed specs)
- [ROADMAP.md v1.15.x section](../ROADMAP.md)
- [v1.14.x Release Plan](RELEASE-PLAN-v1.14.x.md) (completed series)
