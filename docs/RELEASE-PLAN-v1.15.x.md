# Release Plan: v1.15.x Series

**Created:** January 24, 2026
**Last Updated:** January 24, 2026
**Status:** In Progress
**Branch:** feature/new-tui-command

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

**Migration Path:**
- v1.15.0: ppxaide launches as separate command (`ppxaide` vs `ppxai`)
- v1.15.x: Feature parity achieved incrementally
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

## Release Schedule

### v1.15.0 - ppxaide Platform Foundation

**Goal:** Build the UI platform with Textual's rich widget ecosystem before adding functional logic

| Feature | Description | Status |
|---------|-------------|--------|
| **Textual SDK integration** | Build on current `ppxai/engine/` architecture | [x] Done |
| **New entry point** | `ppxaide` command (separate from `ppxai`) | [x] Done |
| **Themes** | 17+ built-in (Textual) + 2 custom (tron-legacy, matrix) | [x] Done |
| **Basic commands** | `/help`, `/quit`, `/clear`, `/theme` | [x] Done |
| **Status bar** | Provider, model, tools, context badges | [x] Done |
| **Chat view** | Message display with role indicators | [x] Done |
| **Input box** | Multi-line input with command history | [x] Done |
| **Round borders** | Unicode box-drawing corners (╭╮╯╰) | [x] Done |
| **Mouse support** | Click-to-scroll, selectable text, clickable links | [ ] Planned |
| **Clipboard** | Text copy/paste via pyperclip | [x] Done |
| **Tree widget** | JSON/YAML/TOML hierarchical display | [x] Done |
| **TextArea widget** | Code editor with syntax highlighting | [x] Done |
| **Split panes** | Horizontal/Vertical container layouts | [x] Done |

**Textual Framework Capabilities:**

| Capability | Textual Support | Notes |
|------------|----------------|-------|
| Rounded corners | ✅ `round` border style | Unicode: ╭╮╯╰ |
| Clipboard (text) | ✅ Built-in + pyperclip | Cross-platform |
| Clipboard (images) | ❌ Not supported | Text-only |
| Inline images | ⚠️ Plugin: `textual-image` | Kitty/iTerm2/Sixel |
| Tree data viewer | ✅ Built-in `Tree` widget | JSON example in repo |
| Code editor | ✅ `TextArea` widget | tree-sitter highlighting |
| Split panes | ✅ Container layouts | Horizontal/Vertical/Grid |

**Implementation Tasks:**

*Core (Done):*
- [x] Create `ppxai/tui/` module structure
- [x] Implement `PPXAIDEApp(textual.App)` main application class
- [x] Create `ChatView` widget for message display
- [x] Create `StatusBar` widget with provider/model/context badges
- [x] Create `InputBox` widget with multi-line support
- [x] Integrate Textual's built-in themes (catppuccin-mocha, nord, dracula, etc.)
- [x] Create custom themes: tron-legacy, matrix
- [x] Add `ppxaide` entry point to `pyproject.toml`
- [x] Add `[tui]` optional dependency group
- [x] Create PyInstaller spec and build binary

*Platform Widgets (In Progress):*
- [x] Update `layout.tcss` to use `round` borders where appropriate
- [x] Add pyperclip integration for clipboard support (`/copy`, `/paste` commands)
- [x] Create `TreeViewer` widget wrapping Textual's Tree
- [x] Create `CodeEditor` widget wrapping Textual's TextArea
- [x] Create `SplitPane` layout for side-by-side views
- [ ] Add mouse-clickable file links (OSC 8 hyperlinks)
- [ ] Basic integration tests

**Deliverable:** Complete UI platform with rich widgets, ready for functional features

---

### v1.15.1 - Commands & Sessions

**Goal:** Full command parity with current TUI

| Feature | Description | Status |
|---------|-------------|--------|
| **Provider commands** | `/provider`, `/model`, `/tools` | [ ] Planned |
| **Agent commands** | `/agent`, `/consent` | [ ] Planned |
| **Session commands** | `/session`, `/save`, `/load`, `/export` | [ ] Planned |
| **Checkpoint commands** | `/checkpoint`, `/undo` | [ ] Planned |
| **Context commands** | `/context`, `/context hints`, `/context clear`, `/context show` | [ ] Planned |
| **Command history** | Arrow key navigation, persistent history | [ ] Planned |
| **Tab completion** | Autocomplete for commands and arguments | [ ] Planned |

**Implementation Tasks:**

- [ ] Create `CommandPalette` widget with autocomplete
- [ ] Port all slash command handlers from `ppxai/commands/`
- [ ] Implement command history with persistence
- [ ] Add keyboard shortcuts (Ctrl+C, Ctrl+D, etc.)
- [ ] Create modal dialogs for consent prompts
- [ ] Add `/config` command for settings
- [ ] Integration tests for all commands

**Deliverable:** Full command support matching current TUI

---

### v1.15.2 - Visual Enhancements

**Goal:** Rich visual features leveraging Textual capabilities

| Feature | Description | Status |
|---------|-------------|--------|
| **Data viewers** | CSV/JSON/YAML tree views (port from Web App) | [ ] Planned |
| **`/show` command** | File preview with syntax highlighting | [ ] Planned |
| **`/edit` command** | Textual TextArea widget for file editing | [ ] Planned |
| **Image preview** | Inline image display (if terminal supports) | [ ] Planned |
| **Split panes** | Code preview alongside chat | [ ] Planned |
| **Tool call accordion** | Expandable tool execution history | [ ] Planned |
| **Markdown tables** | Proper table rendering in responses | [ ] Planned |

**Implementation Tasks:**

- [ ] Create `DataTableViewer` widget for CSV/TSV
- [ ] Create `TreeViewer` widget for JSON/YAML/TOML
- [ ] Implement `/show` command with syntax highlighting
- [ ] Implement `/edit` command using Textual's TextArea
- [ ] Create `ToolCallAccordion` widget
- [ ] Add split pane layout for file preview
- [ ] Image support via Kitty/iTerm2 protocols (optional)
- [ ] Integration tests for visual components

**Deliverable:** Visual parity with Desktop Web App

---

### v1.15.3 - Polish & Performance

**Goal:** Production-ready release

| Feature | Description | Status |
|---------|-------------|--------|
| **Performance optimization** | Efficient rendering for long conversations | [ ] Planned |
| **Accessibility** | Screen reader support, high contrast themes | [ ] Planned |
| **Error handling** | Graceful degradation, clear error messages | [ ] Planned |
| **Configuration** | TUI-specific settings in ppxai-config.json | [ ] Planned |
| **Documentation** | User guide, keyboard shortcuts reference | [ ] Planned |

**Implementation Tasks:**

- [ ] Profile and optimize rendering performance
- [ ] Add virtual scrolling for long conversations
- [ ] Implement high contrast theme variant
- [ ] Add `tui` section to config schema
- [ ] Create keyboard shortcuts quick reference
- [ ] Update installation docs for `pip install ppxai[tui]`
- [ ] End-to-end testing on Linux, macOS, Windows
- [ ] Performance benchmarks vs current TUI

**Deliverable:** Production-ready ppxaide

---

## Feature Parity Checklist

**Current TUI (`ppxai`) features to port:**

### Core Chat
- [ ] Streaming responses with Markdown rendering
- [ ] Multi-line input with history
- [ ] Provider/model switching mid-session
- [ ] Token usage display
- [ ] Cost estimation

### Commands
- [ ] `/help` - Command reference
- [ ] `/model` - Switch model
- [ ] `/provider` - Switch provider
- [ ] `/tools` - Enable/disable tools
- [ ] `/agent` - Start agent mode
- [ ] `/consent` - Manage consent settings
- [ ] `/session` - Session management
- [ ] `/save` - Save session
- [ ] `/load` - Load session
- [ ] `/export` - Export to markdown
- [ ] `/checkpoint` - Checkpoint management
- [ ] `/undo` - Revert last agent task
- [ ] `/context` - Context management
- [ ] `/usage` - Usage statistics
- [ ] `/show` - File preview
- [ ] `/edit` - File editing (NEW in ppxaide)
- [ ] `/theme` - Theme switching
- [ ] `/config` - Configuration
- [ ] `/clear` - Clear conversation
- [ ] `/quit` - Exit application

### Visual Features
- [ ] 4 color themes
- [ ] Status bar with badges
- [ ] Clickable file links (OSC 8)
- [ ] Markdown tables
- [ ] Code block syntax highlighting
- [ ] Tool call display

### Desktop Web App features to port
- [ ] Data viewers (CSV, JSON, YAML, TOML)
- [ ] File editor with syntax highlighting
- [ ] Image preview
- [ ] PDF preview (if terminal supports)

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

- [ ] ppxaide launches and connects to ppxai-server
- [ ] All slash commands work as expected
- [ ] Streaming responses render correctly
- [ ] Theme switching works
- [ ] No performance regression vs current TUI
- [ ] Works on Linux, macOS, Windows

---

## References

- [Textual Documentation](https://textual.textualize.io/)
- [Textual CSS Reference](https://textual.textualize.io/guide/CSS/)
- [ROADMAP.md v1.15.x section](../ROADMAP.md)
- [v1.14.x Release Plan](RELEASE-PLAN-v1.14.x.md) (completed series)
