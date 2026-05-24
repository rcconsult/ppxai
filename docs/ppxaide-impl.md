# ppxaide TUI Implementation

The `ppxaide` command launches a Textual-based TUI with syntax-highlighted code editing. This document captures implementation details that MUST be preserved.

## Syntax highlighting requirements

Tree-sitter packages in `pyproject.toml`:

```
tree-sitter>=0.23
tree-sitter-python>=0.25.0
tree-sitter-javascript>=0.25.0
tree-sitter-json>=0.24.8
tree-sitter-yaml>=0.7.2
tree-sitter-toml>=0.7.0
tree-sitter-html>=0.23.2
tree-sitter-css>=0.25.0
tree-sitter-markdown>=0.5.1
tree-sitter-bash>=0.25.1
```

Without these packages, TextArea shows plain text with no syntax colors.

## Two theme systems

The TUI has **two separate theme systems** that must stay synchronized:

| System | Purpose | Available |
|--------|---------|-----------|
| **App theme** | Overall UI colors (Textual CSS) | 17+ themes (catppuccin-mocha, dracula, etc.) |
| **Syntax theme** | Code highlighting (TextArea) | 5 only: dracula, github_light, monokai, vscode_dark, css |

## Theme synchronization

Key files:
- `ppxai/tui/widgets/code_editor.py` — `APP_THEME_TO_SYNTAX` mapping and `get_syntax_theme_for_app_theme()`
- `ppxai/tui/app.py` — `watch_theme()` updates all CodeEditor widgets

Flow:
1. `CodeEditor.compose()` gets current app theme and selects matching syntax theme.
2. `PPXAIDEApp.watch_theme()` is called automatically when theme changes (Ctrl+T or Ctrl+P).
3. All mounted CodeEditor widgets have their `syntax_theme` property updated.

Mapping logic:
```python
# Dark app themes → dark syntax themes
"catppuccin-mocha": "dracula"
"dracula": "dracula"
"tokyo-night": "dracula"
"tron-legacy": "vscode_dark"
"matrix": "vscode_dark"
# Light app themes → light syntax theme
"textual-light": "github_light"
"solarized-light": "github_light"
```

**Framework limitation:** custom app themes (tron-legacy, matrix) cannot have matching custom syntax themes — Textual's TextArea only supports the 5 built-in syntax themes. Map to the closest built-in (vscode_dark for cyan/green themes).

## Why Markdown renders nicely but code needs manual sync

| Content | Widget | Theme source | Behavior |
|---------|--------|--------------|----------|
| **Markdown** | `Markdown` widget | CSS variables (`$primary`, `$secondary`, ...) | Auto-syncs with app theme |
| **Code** | `TextArea` widget | Internal syntax themes (dracula, etc.) | Needs manual `watch_theme()` sync |

The `Markdown` widget styles via CSS rules that reference `$primary`, `$secondary` — those variables are redefined by each app theme, so Markdown automatically updates. The `TextArea` widget has its own internal rendering engine with hardcoded color palettes that don't use CSS variables, hence the `watch_theme()` → `syntax_theme` chain.

## Key bindings

All key bindings are in `ppxai/tui/keys.py` (single source of truth). Widget `BINDINGS` lists are generated via `get_widget_bindings()`. Use `/keys` at runtime to see all effective bindings, `/keys conflicts` for known conflicts.

- `Ctrl+Enter` — submit message (plain Enter inserts newlines)
- `Ctrl+J` — submit message (universal fallback for all terminals)
- `Ctrl+B` — toggle file tree browser (Norton Commander style)
- `Ctrl+T` — cycle through 8 curated themes
- `Ctrl+P` — command palette (all 17+ themes)
- `Ctrl+W` — close side panel
- `Ctrl+S` — save side panel content
- `Escape` — close help panel / modal screen / side panel (priority order)
- `F6` / `Ctrl+Tab` — cycle focus: input → file tree → side panel → input
- `-` / `=` — resize split panes (primary, works in all terminals)
- `Ctrl+[` / `Ctrl+]` — resize split panes (fallback, Ghostty/Kitty only)

File tree bindings (when file tree focused):
- `Enter` — preview file read-only in side panel
- `Ctrl+Enter` — open file for editing in side panel
- `Space` — inject `@file:path ` at cursor in chat input
- `Escape` — return focus to chat input

## Kitty keyboard protocol

Textual 8.1.1 does NOT auto-negotiate Kitty keyboard protocol (upstream issue #6074 open). Ctrl+Enter only works in terminals that send CSI u sequences:
- **Kitty** — works natively
- **Ghostty** — requires `ctrl+enter=text:\x1b[13;5u` in config
- **WezTerm** — requires `enable_kitty_keyboard = true`
- **All others** — use `Ctrl+J` fallback

No changes planned — fallback keys cover all terminals.

## DO NOT BREAK

1. **Key registry:** `ppxai/tui/keys.py` → `get_app_bindings()` / `get_widget_bindings()` → all BINDINGS
2. **Theme sync chain:** `watch_theme()` → `get_syntax_theme_for_app_theme()` → `CodeEditor.syntax_theme`
3. **Tree-sitter dependencies** in `pyproject.toml`
4. **Language detection** via `EXTENSION_TO_LANGUAGE` in `code_editor.py`

## Terminal image rendering (v1.15.2)

ppxai supports high-resolution inline image display in terminals that support image protocols.

| Terminal | Protocol | ppxaide (Textual) | ppxai (Rich) |
|----------|----------|-------------------|--------------|
| Windows Terminal | Sixel | textual-image | textual-image |
| WezTerm | iTerm2 | ITerm2ImageWidget | ITerm2Image |
| iTerm2 (macOS) | TGP/iTerm2 | textual-image | ITerm2Image |
| Kitty | TGP | textual-image | Fallback |

**Textual TUI:** uses `render_lines()` override to inject escape sequences. Cannot use Rich renderables directly because Textual processes segments differently. See `ppxai/tui/widgets/iterm2_widget.py`.

**Rich TUI:** uses Rich renderables with the `_NULL_CONTROL` trick to pass escape sequences through:
```python
_NULL_CONTROL = [(ControlType.CURSOR_FORWARD, 0)]
yield Segment(escape_sequence, control=_NULL_CONTROL)
```

WezTerm requires `TERM_PROGRAM` environment variable for detection:
```lua
-- ~/.wezterm.lua
config.set_environment_variables = { TERM_PROGRAM = 'WezTerm' }
```

Key files:
- `ppxai/tui/renderable/iterm2.py` — ITerm2Image Rich renderable
- `ppxai/tui/widgets/iterm2_widget.py` — Textual widget using `render_lines()` injection
- `ppxai/tui/widgets/image_handlers.py` — terminal detection and widget selection
- `ppxai/rendering/rich_renderer.py` — Rich TUI image rendering
