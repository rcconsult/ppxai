# TUI Markdown Rendering & Developer Workspace Vision

**Document Version:** 2.1
**Last Updated:** 2025-12-18
**Target Releases:** v1.10.4 (bug fixes), v1.12.0 (workspace), v1.14.0+ (full NvChad-like experience)

This document catalogs the current TUI (Terminal User Interface) markdown rendering capabilities, known issues, technology decisions, and a roadmap for transforming ppxai's TUI into a true developer workspace comparable to Neovim/NvChad.

**Related Documents:**
- [gemini3-features-roadmap.md](../gemini3-features-roadmap.md) - Agentic workflow roadmap (v1.11.0-v1.13.0)
- [sonar-features-proposal.md](../sonar-features-proposal.md) - Competitive analysis and strategic positioning

---

## Part 1: Current Implementation (v1.10.2)

### 1.1 Technology Stack

| Component | Library | Purpose |
|:----------|:--------|:--------|
| Console Output | `rich.console.Console` | All terminal output, colors, styles |
| Markdown | `rich.markdown.Markdown` | AI response rendering |
| Panels | `rich.panel.Panel` | Welcome screen, spec templates |
| Tables | `rich.table.Table` | Sessions, usage, models, tools |
| Syntax | `rich.syntax.Syntax` | Code file highlighting (`/show`) |
| Prompts | `rich.prompt.Prompt` | Model/provider selection |
| Input | `prompt_toolkit.PromptSession` | User input with history |
| Completion | `prompt_toolkit.completion` | Tab completion for commands/files |
| History | `prompt_toolkit.history` | Command history with arrow keys |

### 1.2 Implemented Features

#### A. Markdown Rendering in AI Responses

**Location:** `ppxai/client.py:180`, `ppxai/client.py:217`

```python
console.print(Markdown(full_response))
```

**Supported Elements:**
- Headers (`#`, `##`, `###`, etc.)
- Bold (`**text**`) and italic (`*text*`)
- Code blocks with syntax highlighting (` ```lang `)
- Inline code (`` `code` ``)
- Bullet lists (`-`, `*`)
- Numbered lists (`1.`, `2.`)
- Blockquotes (`>`)
- Horizontal rules (`---`)
- Links (`[text](url)`)

#### B. Panel-Based UI Components

**Location:** `ppxai/ui.py:61`, `ppxai/ui.py:68`

```python
console.print(Panel(Markdown(welcome_text), title="Welcome", border_style="cyan"))
```

**Used For:**
- Welcome screen (`display_welcome()`)
- Specification guidelines (`display_spec_help()`)
- Specification templates (`SPEC_TEMPLATES`)

#### C. Rich Tables (Application Data)

**Location:** `ppxai/ui.py:84-233`

Tables are used for structured application data:
- Model selection (`display_models()`)
- Provider selection (`select_provider()`)
- Session listing (`display_sessions()`)
- Usage statistics (`display_usage()`, `display_global_usage()`)
- Tool listing (`display_tools_table()`)

#### D. Syntax Highlighting for Files

**Location:** `ppxai/commands.py:707`

```python
from rich.syntax import Syntax
syntax = Syntax(content, lang, theme="monokai", line_numbers=True)
```

**Used For:**
- `/show <file>` command
- `/cat <file>` command (alias)

**Supported Languages:** All languages supported by Pygments (Python, JavaScript, TypeScript, Go, Rust, etc.)

#### E. Interactive Input Features

**Location:** `ppxai/main.py:176-181`

```python
session = PromptSession(
    history=InMemoryHistory(),
    completer=completer,
    complete_while_typing=True,
    auto_suggest=AutoSuggestFromHistory(),
)
```

**Features:**
- Tab completion for `/commands`
- Tab completion for `@filename` references
- Up/down arrow for command history
- Auto-suggest from history (gray ghost text)

#### F. Clickable Citations

**Location:** `ppxai/client.py:247`

```python
clickable_link = f"[link={citation}]{citation}[/link]"
```

**Works in:** Terminals that support OSC 8 hyperlinks (iTerm2, Windows Terminal, GNOME Terminal 3.26+, etc.)

#### G. Streaming Progress Indicator

**Location:** `ppxai/client.py:163`

During streaming responses, dots are printed as progress:
```python
console.print(".", end="", style="dim")
```

---

## Part 2: Known Issues (Historical)

### 2.1 ✅ FIXED (v1.10.4): Markdown Tables Not Rendering

**Severity:** High
**Status:** ✅ FIXED in v1.10.4 (2025-12-19)
**Affected:** AI response rendering
**Screenshot:** `../tui-md-render-bug.png` (historical bug documentation)

**Description:**
When AI responses contain markdown tables, they are displayed as raw text instead of formatted tables:

```
# What users see (broken):
| Feature | Status |
|:---|:---|
| Multi-step autonomy | Yes |

# What users should see (formatted):
+-----------------+--------+
| Feature         | Status |
+-----------------+--------+
| Multi-step autonomy | Yes |
+-----------------+--------+
```

**Root Cause:**
Rich's `Markdown` class has limited table support. The `rich.markdown.Markdown` renderer does not fully parse GitHub-Flavored Markdown (GFM) tables.

**Workaround:**
- Use VSCode extension for table-heavy content
- Export conversation to markdown (`/save`) and view externally

**Fix Options:**

1. **Use `rich-rst` or custom parser** - Pre-process markdown tables and convert to `rich.table.Table` objects ✅ **IMPLEMENTED in v1.10.4**
2. **Upgrade to `rich` v13+** - Check if newer Rich versions have improved table support
3. **Use `mdformat` + custom renderer** - Parse markdown AST and render tables explicitly
4. **Switch to `textual`** - Textual (by same author) has better markdown table support

**✅ How It Was Fixed (v1.10.4):**

Implemented Option 1 - Custom table parser with Rich Table objects:

- Created `ppxai/markdown_tables.py` module
- `parse_markdown_table()` - Parses markdown table strings → Rich Table objects
- `split_markdown_content()` - Separates tables from other markdown content
- `render_markdown_with_tables()` - Renders mixed content (tables + markdown)
- Supports alignment markers (`:---`, `:---:`, `---:`) for left/center/right alignment
- Handles emojis, inline code, and complex content in cells
- Updated `ppxai/client.py` to use new renderer
- Added 27 regression tests in `tests/test_markdown_tables.py`

**Result:** Tables now render correctly with proper formatting, alignment, and styling. No more raw markdown syntax visible.

### 2.2 No Code Block Copy Button

**Severity:** Low
**Description:** Unlike VSCode extension, TUI has no way to copy code blocks easily.

### 2.3 No Message Editing

**Severity:** Medium
**Description:** Cannot edit or regenerate previous messages in TUI (VSCode extension supports this).

### 2.4 No Diff View

**Severity:** Medium
**Description:** When AI suggests code changes, there's no side-by-side diff view.

### 2.5 Limited Terminal Width Handling

**Severity:** Low
**Description:** Very wide tables or code blocks may wrap awkwardly on narrow terminals.

---

## Part 3: Technology Decision - Textual Framework

### 3.1 Framework Choice

**Decision:** Migrate from pure Rich to **Textual** for workspace features.

**Why Textual:**

| Criterion | Rich (Current) | Textual (Target) |
|:----------|:---------------|:-----------------|
| Author | Will McGugan | Will McGugan (same) |
| Markdown tables | Limited | Full GFM support |
| Widget system | None | Full (Tree, Tabs, TextArea, etc.) |
| Layout system | None | Docking, splits, grids |
| Styling | Inline styles | TCSS (CSS-like) |
| Async support | Manual | Built-in |
| Event handling | None | Full event system |
| Mouse support | Limited | Full |
| Web deployment | No | Yes (`textual serve`) |

**Key Textual Widgets for ppxai:**

| Widget | Purpose | NvChad Equivalent |
|:-------|:--------|:------------------|
| `Markdown` | AI responses with table support | - |
| `MarkdownViewer` | + TOC and navigation | - |
| `DirectoryTree` | File explorer | nvim-tree |
| `TabbedContent` | Multi-session tabs | bufferline |
| `TextArea` | Code editing with syntax | treesitter |
| `Header` | App title, clock | statusline (top) |
| `Footer` | Keybindings | which-key hints |

### 3.2 Performance Guarantees

From Textual's architecture:

1. **Segment-based compositor**: Handles unicode/emoji widths correctly
2. **Spatial indexing**: O(1) widget lookup regardless of count
3. **Partial updates**: Only redraws changed screen regions
4. **60fps cap**: Smooth animations without CPU waste

### 3.3 Dependency Addition

```toml
# pyproject.toml
[project.optional-dependencies]
workspace = [
    "textual>=1.0.0",
    "textual-dev>=1.0.0",  # Dev tools
]
```

---

## Part 4: NvChad-like Workspace Vision

### 4.1 Target Experience

The goal is to create a terminal experience comparable to **Neovim + NvChad**:
- Split panes with resizable regions
- File tree navigation
- Tabbed sessions
- Statusline with context info
- Which-key style command hints
- Theming via CSS-like syntax
- Keyboard-driven workflow

### 4.2 Layout Design

```
+------------------------------------------------------------------+
|                         ppxai v1.14.0                 12:34:56   |
+------------------+-----------------------------------------------+
| Files            | Chat 1 | Chat 2* | + New                      |
+------------------+-----------------------------------------------+
| ppxai/           |                                               |
|   client.py      | You: explain @main.py                         |
|   main.py     M  |                                               |
|   ui.py          | AI: This file contains the main entry point   |
| tests/           | for the ppxai application. It initializes...  |
|   test_*.py      |                                               |
+------------------+-----------------------------------------------+
| [/] Search       | def main():                                   |
| [g] Git status   |     """Main entry point."""                   |
+------------------+     config = load_config()                    |
                   |     ...                                       |
+------------------------------------------------------------------+
| CHAT | perplexity/sonar-pro | 1,234 tokens | Tools: ON | @git   |
+------------------------------------------------------------------+
```

**Components:**
- **Header**: App name, clock
- **Sidebar**: DirectoryTree with git status indicators
- **Tabs**: TabbedContent for multiple chat sessions
- **Main pane**: Markdown chat with streaming
- **Preview pane**: TextArea for file/diff preview
- **Statusline**: Mode, provider, model, tokens, tools status
- **Footer**: Active keybindings

### 4.3 Statusline (like lualine.nvim)

```python
# ppxai/workspace/widgets/statusline.py
from textual.widgets import Static
from textual.reactive import reactive

class Statusline(Static):
    """NvChad-like statusline with mode, model, tokens."""

    mode = reactive("CHAT")
    provider = reactive("perplexity")
    model = reactive("sonar-pro")
    tokens = reactive(0)
    tools_enabled = reactive(True)
    context_tags = reactive([])  # @git, @tree, etc.

    def render(self) -> str:
        tools = "ON" if self.tools_enabled else "OFF"
        tags = " ".join(f"@{t}" for t in self.context_tags)
        return (
            f" {self.mode} | {self.provider}/{self.model} | "
            f"{self.tokens:,} tokens | Tools: {tools} | {tags} "
        )
```

### 4.4 Which-Key Style Hints

When user presses leader key (e.g., `Space`):

```
+-------------------------------------+
| Space+f  Find file                  |
| Space+g  Git status (@git context)  |
| Space+t  Toggle tools               |
| Space+s  Save session               |
| Space+a  Agent mode (/agent)        |
| Space+p  Command palette            |
+-------------------------------------+
```

### 4.5 Theme System (TCSS)

```css
/* ppxai/workspace/themes/nvchad_dark.tcss */
Screen {
    background: #1e1e2e;
}

#sidebar {
    width: 25%;
    min-width: 20;
    background: #181825;
    border-right: solid #313244;
}

#chat-panel {
    background: #1e1e2e;
}

.statusline {
    background: #89b4fa;
    color: #1e1e2e;
}

.diff-add { color: #a6e3a1; }
.diff-del { color: #f38ba8; }
.diff-hunk { color: #89b4fa; }

Header {
    background: #1e1e2e;
    color: #cdd6f4;
}

Footer {
    background: #181825;
}

DirectoryTree {
    background: #181825;
}

DirectoryTree > .directory-tree--folder {
    color: #89b4fa;
}

DirectoryTree > .directory-tree--file {
    color: #cdd6f4;
}

.git-modified {
    color: #fab387;
}

.git-staged {
    color: #a6e3a1;
}
```

---

## Part 5: Implementation Roadmap

### 5.0 What Shipped in v1.10.3 (Released 2025-12-18)

**Focus:** Pre-built Server Binaries

-   ✅ Standalone `ppxai-server` executables for all platforms
-   ✅ No Python required for VSCode extension users
-   ✅ GitHub Actions CI/CD for automated binary builds
-   ✅ Updated installation documentation

**Note:** Markdown table rendering fix and `@git`/`@tree` context moved to v1.10.4.

### 5.1 ✅ Phase 1: Fix Core Rendering (v1.10.4 - COMPLETED)

**Status:** ✅ COMPLETED (2025-12-19)
**Priority:** Critical

| Task | Status | Implementation |
|:-----|:-------|:---------------|
| Fix markdown tables | ✅ Done | `ppxai/markdown_tables.py` with Rich Table parser |
| Fix table alignment | ✅ Done | Alignment parser for `:---`, `---:`, `:---:` markers |
| Add table borders | ✅ Done | Configurable via Rich Table `border_style` |
| Regression tests | ✅ Done | 27 tests in `tests/test_markdown_tables.py` |

**What Was Implemented:**

Created a new module `ppxai/markdown_tables.py` with:

-   `parse_markdown_table()` - Converts markdown table strings to Rich Table objects
-   `parse_table_alignment()` - Parses alignment markers (left/center/right)
-   `is_table_block()` - Detects markdown table blocks
-   `split_markdown_content()` - Separates tables from other markdown content
-   `render_markdown_with_tables()` - Main rendering function for mixed content

**Integration:**

Updated `ppxai/client.py` to use `render_markdown_with_tables()` instead of `console.print(Markdown())` for AI responses. This ensures tables are rendered as Rich Table objects while other markdown content uses the standard Rich Markdown renderer.

**Test Coverage:**

Added comprehensive regression tests (`tests/test_markdown_tables.py`):

-   Table alignment parsing (left/center/right/mixed)
-   Table detection and content splitting
-   Tables with emojis, inline code, and complex content
-   Multiple tables in one response
-   Edge cases (empty cells, uneven columns)
-   Specific regression test for the original bug from tui-md-render-bug.png

All 228 tests pass (including 27 new table tests).

### 5.2 Phase 2: Textual Foundation (v1.11.0)

**Priority:** High
**Sync with:** v1.11.0 "The Agent Release" (agentic workflow)

| Task | Description | Dependency |
|:-----|:------------|:-----------|
| Add Textual dependency | `textual>=1.0.0` in `[workspace]` extra | None |
| Create `ppxai/workspace/` module | Basic app structure | Textual |
| Implement `--workspace` flag | Launch Textual app | Module |
| Port streaming chat | `StreamingChat` widget | Textual |
| Add statusline | Mode, provider, model, tokens | Textual |

**Entry Point:**

```python
# ppxai/main.py
import click

@click.option('--workspace', is_flag=True, help='Launch NvChad-like workspace UI')
def main(workspace: bool = False):
    if workspace:
        from ppxai.workspace import PPXAIWorkspace
        app = PPXAIWorkspace()
        app.run()
    else:
        # Existing Rich-based TUI
        run_classic_tui()
```

**Integration with Agentic Features:**

The workspace UI will display `/agent` loop progress:

```
+------------------------------------------------------------------+
| Agent Loop: 2/5                                                  |
+------------------------------------------------------------------+
| [1] pytest tests/ -v                     FAILED (3 errors)    |
| [2] edit_file ppxai/client.py:142        APPLIED              |
| [3] pytest tests/ -v                     RUNNING...           |
+------------------------------------------------------------------+
```

### 5.3 Phase 3: Split Pane Layout (v1.12.0)

**Priority:** Medium
**Sync with:** v1.12.0 "The Context Release" (`@tree`, `@codebase`, `@problems`)

| Task | Description | Dependency |
|:-----|:------------|:-----------|
| Implement split layout | Horizontal container with sidebar + main | Textual |
| Add DirectoryTree | File explorer with git status | Split layout |
| Add TabbedContent | Multi-session tabs | Textual |
| Add file preview pane | TextArea with syntax highlighting | Split layout |
| Implement `@tree` display | Show tree in sidebar or inject into context | DirectoryTree |

**`@tree` Integration:**

```python
# When user types "@tree", inject directory structure
@tree_context = """
ppxai/
  __init__.py
  client.py
  config.py
  main.py
  ui.py
  engine/
    client.py
    session.py
    providers/
    tools/
  workspace/  # NEW
    app.py
    widgets/
    themes/
"""
```

### 5.4 Phase 4: Interactive Code Editing (v1.13.0)

**Priority:** Medium
**Sync with:** v1.13.0 "The Integration Release" (inline completion, code lenses)

| Task | Description | Dependency |
|:-----|:------------|:-----------|
| Diff view widget | Show proposed changes as unified diff | Textual |
| Accept/reject UI | Keyboard shortcuts for hunks | Diff widget |
| Undo stack | Track applied changes | Accept/reject |
| `@problems` display | Show linter errors in sidebar | VS Code integration |

**Diff View:**

```
+------------------- Proposed Changes --------------------+
| ppxai/client.py                                         |
+---------------------------------------------------------+
|  140   def _stream_response(self, model, messages):     |
|  141       import time                                  |
|- 142       start_time = time.time()                     |
|+ 142       start_time = time.perf_counter()             |
|  143                                                    |
+---------------------------------------------------------+
| [A] Accept All  [R] Reject All  [j/k] Navigate Hunks    |
| [a] Accept Hunk [r] Reject Hunk [e] Edit Manually       |
+---------------------------------------------------------+
```

### 5.5 Phase 5: Full Workspace (v1.14.0)

**Priority:** Low-Medium
**Sync with:** Post-agentic stabilization

| Task | Description | Dependency |
|:-----|:------------|:-----------|
| Dashboard screen | alpha.nvim-like welcome | Textual |
| Which-key hints | Modal keybinding display | Textual |
| Theme switching | Multiple TCSS themes | Theme system |
| Fuzzy file search | fzf-like finder | DirectoryTree |
| Bookmarks | Quick access to important files | File tree |

**Dashboard (alpha.nvim style):**

```
                +-------------------------------+
                |        ppxai v1.14.0          |
                +-------------------------------+

                Quick Actions

                [n] New conversation
                [r] Resume last session
                [f] Find in files
                [s] Sessions
                [a] Agent mode
                [c] Config
                [q] Quit

                Recent Sessions:
                * debugging-api-issue (2h ago)
                * feature-planning (yesterday)
                * code-review @git (3 days ago)
```

### 5.6 Phase 6: Terminal Multiplexing (v1.15.0+)

**Priority:** Low

| Task | Description | Dependency |
|:-----|:------------|:-----------|
| Embedded terminal | Run shell commands in TUI | Textual |
| Terminal capture | Pipe output to AI context | Embedded terminal |
| Auto-scroll/search | Navigate terminal output | Terminal widget |

---

## Part 6: File Structure

```
ppxai/
+-- workspace/                    # NEW: Textual-based workspace
|   +-- __init__.py               # Exports PPXAIWorkspace
|   +-- app.py                    # Main Textual App class
|   +-- themes/                   # TCSS theme files
|   |   +-- nvchad_dark.tcss      # Default dark theme
|   |   +-- catppuccin.tcss       # Catppuccin theme
|   |   +-- dracula.tcss          # Dracula theme
|   +-- widgets/                  # Custom widgets
|   |   +-- __init__.py
|   |   +-- chat.py               # StreamingChat widget
|   |   +-- statusline.py         # Statusline widget
|   |   +-- whichkey.py           # Which-key modal
|   |   +-- diffview.py           # Diff viewer widget
|   |   +-- agentloop.py          # Agent loop progress
|   |   +-- commandpalette.py     # Command palette
|   +-- screens/                  # Textual screens
|       +-- dashboard.py          # Welcome dashboard
|       +-- settings.py           # Settings screen
+-- rendering.py                  # NEW: Table parser for v1.10.3 fix
+-- main.py                       # Add --workspace flag
+-- ...existing files...
```

---

## Part 7: Integration with Agentic Roadmap

### 7.1 Feature Alignment Matrix

| Agentic Feature (gemini3-roadmap) | Workspace UI Support |
|:----------------------------------|:---------------------|
| `/agent` loop (v1.11.0) | Agent progress widget showing loop iteration |
| `edit_file` tool (v1.11.0) | Diff view for proposed changes |
| `@git` context (v1.10.3) | Git status in DirectoryTree sidebar |
| `@tree` context (v1.12.0) | DirectoryTree widget + context injection |
| `@codebase` RAG (v1.12.0) | Semantic search results in preview pane |
| `@problems` (v1.12.0) | Linter errors in sidebar panel |
| Inline completion (v1.13.0) | Ghost text in TextArea (future) |
| Code lenses (v1.13.0) | Buttons in file preview (future) |

### 7.2 Combined Release Timeline

| Version | TUI/Workspace | Agentic Features |
|:--------|:--------------|:-----------------|
| **v1.10.3** | *(Released 2025-12-18)* Pre-built server binaries | N/A |
| **v1.10.4** | Fix markdown tables | `@git` context, `@tree` context |
| **v1.11.0** | Textual foundation, `--workspace` flag, statusline | `/agent` loop, `edit_file` tool |
| **v1.12.0** | Split panes, DirectoryTree, tabs | `@codebase` RAG, `@problems` |
| **v1.13.0** | Diff view, accept/reject UI | Inline completion, code lenses |
| **v1.14.0** | Dashboard, which-key, themes | Stabilization |
| **v1.15.0** | Embedded terminal | Plugin system |

---

## Part 8: Backward Compatibility

### 8.1 Commitment

- **Classic TUI mode** (`ppxai` or `ppxai --classic`) always available
- **Workspace mode** (`ppxai --workspace`) optional until stable
- **Same slash commands** work in both modes
- **Session files** compatible across modes
- **Configuration** shared between modes

### 8.2 Migration Path

1. v1.10.3: Pre-built server binaries (released 2025-12-18)
2. v1.10.4: Fix tables in classic Rich TUI
3. v1.11.0: Add `--workspace` flag (experimental)
4. v1.12.0: Workspace becomes default for new users
5. v1.14.0: Workspace becomes default for all users
6. v1.15.0+: Classic mode deprecated but maintained

---

## Part 9: Performance Considerations

| Concern | Mitigation |
|:--------|:-----------|
| Textual startup time | Lazy loading; classic mode stays fast |
| Memory usage | Virtual scrolling for long conversations |
| CPU during streaming | Batch re-renders, 60fps cap |
| Large file preview | Lazy loading, truncation at 10K lines |
| Many open tabs | Tab limit (10) with LRU eviction |

---

## Part 10: Success Metrics

### 10.1 Bug Fix Success (v1.10.4)

- [ ] Markdown tables render correctly
- [ ] Table alignment (left, center, right) works
- [ ] No raw `|:---|:---|` visible in output
- [ ] Tables with emojis render correctly

### 10.2 Workspace Foundation (v1.11.0)

- [ ] `--workspace` flag launches Textual app
- [ ] Streaming chat works in workspace
- [ ] Statusline shows provider/model/tokens
- [ ] Ctrl+C gracefully exits

### 10.3 Full Workspace (v1.14.0)

- [ ] Split-pane layout functional
- [ ] File preview with syntax highlighting
- [ ] Diff view for code changes
- [ ] Accept/reject changes without leaving TUI
- [ ] < 100ms response to keyboard input
- [ ] Works on 80x24 minimum terminal size
- [ ] At least 3 themes available

### 10.4 Developer Adoption

- [ ] Positive feedback on GitHub discussions
- [ ] Users prefer TUI workspace for quick tasks
- [ ] Documentation and tutorials complete
- [ ] Keyboard-only workflow fully supported

---

## Appendix A: Keyboard Shortcuts (Proposed)

### Global Shortcuts

| Shortcut | Action |
|:---------|:-------|
| `Ctrl+L` | Clear screen |
| `Ctrl+C` | Cancel current generation / Exit |
| `Ctrl+D` | Exit application |
| `Ctrl+S` | Save session |
| `Ctrl+O` | Open file picker |
| `Ctrl+P` | Command palette |
| `Ctrl+\` | Toggle side panel |
| `Ctrl+B` | Toggle sidebar |

### Function Keys

| Shortcut | Action |
|:---------|:-------|
| `F1` | Help |
| `F2` | File tree focus |
| `F3` | History |
| `F5` | Regenerate response |

### Tab Navigation

| Shortcut | Action |
|:---------|:-------|
| `Ctrl+Tab` | Next tab |
| `Ctrl+Shift+Tab` | Previous tab |
| `Ctrl+W` | Close tab |
| `Ctrl+T` | New tab |

### Leader Key (Space)

| Shortcut | Action |
|:---------|:-------|
| `Space+f` | Find file |
| `Space+g` | Git status / `@git` context |
| `Space+t` | Toggle tools |
| `Space+s` | Save session |
| `Space+a` | Agent mode (`/agent`) |
| `Space+p` | Switch provider |
| `Space+m` | Switch model |
| `Space+q` | Quit |

### Diff View

| Shortcut | Action |
|:---------|:-------|
| `A` | Accept all changes |
| `R` | Reject all changes |
| `a` | Accept current hunk |
| `r` | Reject current hunk |
| `j` / `k` | Navigate hunks |
| `e` | Edit manually |

---

## Appendix B: Theme Gallery

### NvChad Dark (Default)

```
Background:  #1e1e2e (Catppuccin base)
Foreground:  #cdd6f4 (Catppuccin text)
Accent:      #89b4fa (Catppuccin blue)
Success:     #a6e3a1 (Catppuccin green)
Error:       #f38ba8 (Catppuccin red)
Warning:     #fab387 (Catppuccin peach)
```

### Dracula

```
Background:  #282a36
Foreground:  #f8f8f2
Accent:      #bd93f9 (purple)
Success:     #50fa7b (green)
Error:       #ff5555 (red)
Warning:     #ffb86c (orange)
```

### Tokyo Night

```
Background:  #1a1b26
Foreground:  #c0caf5
Accent:      #7aa2f7 (blue)
Success:     #9ece6a (green)
Error:       #f7768e (red)
Warning:     #e0af68 (yellow)
```

---

## References

- [Rich Documentation](https://rich.readthedocs.io/)
- [Textual Documentation](https://textual.textualize.io/)
- [Textual Widget Gallery](https://textual.textualize.io/widget_gallery/)
- [Textual Performance Blog](https://textual.textualize.io/blog/2024/12/12/algorithms-for-high-performance-terminal-apps/)
- [prompt_toolkit Documentation](https://python-prompt-toolkit.readthedocs.io/)
- [markdown-it-py](https://github.com/executablebooks/markdown-it-py)
- [NvChad](https://nvchad.com/) - Neovim configuration inspiration
- [GitHub: ppxai Issues](https://github.com/rcconsult/ppxai/issues)
