# Textual Widgets Research for ppxaide v1.16.0+

**Date:** 2026-01-27
**Purpose:** Research findings for UI/UX improvements in ppxaide (Textual TUI)
**Target Releases:** v1.16.0 (Q2 2026), v1.17.0 (Q3 2026)

---

## Executive Summary

This document compiles research on third-party Textual widgets and built-in features that can significantly improve ppxaide's UI/UX. All solutions are production-ready and actively maintained.

**Key Findings:**
1. **Autocomplete** - `textual-autocomplete` library solves all our current issues
2. **Tabbed Outputs** - Built-in `TabbedContent` widget perfect for dynamic tool outputs
3. **File Browser** - Built-in `DirectoryTree` widget ready for VSCode-style sidebar
4. **Split Panes** - Built-in layout containers support complex layouts
5. **Streaming** - Built-in `RichLog` widget handles async streaming perfectly

---

## 1. Autocomplete Widget

### Problem Statement

Current ppxaide autocomplete implementation (v1.15.0):
- ❌ Fixed offset positioning (`offset-y: 90%`) instead of cursor-based
- ❌ Single column layout (poor UX for 100+ files)
- ❌ No alphabetical sorting
- ❌ Fixed 100 file limit
- ❌ No lazy loading/virtual scrolling

**Status:** Disabled in production (see [CLAUDE.md:81-96](../CLAUDE.md#L81-L96))

### Solution: textual-autocomplete

**Library:** [darrenburns/textual-autocomplete](https://github.com/darrenburns/textual-autocomplete)
**Version:** 4.0.6 (Jan 2026)
**License:** MIT
**Stars:** 256 ⭐
**Status:** May become officially recommended by Textualize

#### Features

- ✅ **Dropdown popup** - Proper cursor-based positioning
- ✅ **Fuzzy matching** - Find matches even with typos
- ✅ **Keyboard navigation** - Arrow keys, Tab, Enter, Escape
- ✅ **Rich styling** - Customizable highlighting and appearance
- ✅ **Dynamic content** - Supply items as list or from callback function
- ✅ **Path completions** - Built-in `PathAutoComplete` widget
- ✅ **Compatible with Textual 2.0+**
- ✅ **Async-friendly** - Works with workers and background tasks

#### Installation

```toml
# pyproject.toml
[project.dependencies]
textual-autocomplete = "^4.0.6"
```

```bash
pip install textual-autocomplete
uv add textual-autocomplete
```

#### Basic Usage

```python
from textual.app import App
from textual.widgets import Input
from textual_autocomplete import AutoComplete, Dropdown, DropdownItem

class ChatApp(App):
    def compose(self):
        yield AutoComplete(
            Input(placeholder="Type / for commands or @ for files..."),
            Dropdown(items=self.get_completions)
        )

    def get_completions(self, current_text: str) -> list[DropdownItem]:
        """Dynamic completion callback."""
        if current_text.startswith('/'):
            return self.get_command_completions(current_text)
        elif '@' in current_text:
            return self.get_file_completions(current_text)
        return []
```

#### Path Autocomplete

```python
from textual_autocomplete import AutoComplete, PathAutoComplete

class FileInput(App):
    def compose(self):
        yield AutoComplete(
            Input(placeholder="Enter file path..."),
            PathAutoComplete(
                root="/path/to/project",
                ignore_patterns=[".git", "node_modules", "__pycache__"]
            )
        )
```

#### Advanced: Custom Dropdown with Metadata

```python
class CommandDropdown(Dropdown):
    def get_items(self, text: str) -> list[DropdownItem]:
        """Get slash command completions with descriptions."""
        commands = CommandFactory.get_all_commands()

        if not text.startswith('/'):
            return []

        query = text[1:].lower()  # Remove '/'
        matches = []

        for cmd in commands:
            if query in cmd.name.lower():
                matches.append(
                    DropdownItem(
                        main=f"/{cmd.name}",
                        metadata=cmd.description,
                        highlight_query=query
                    )
                )

        return sorted(matches, key=lambda x: x.main)
```

#### Integration Plan

**Phase 1: Replace CompletionPopup (v1.16.0)**

1. Add dependency to `pyproject.toml`
2. Remove `ppxai/tui/widgets/completion_popup.py` (145 lines)
3. Refactor `ppxai/tui/completer.py` to return `DropdownItem` objects
4. Update `ppxai/tui/widgets/input_box.py` to use `AutoComplete` wrapper
5. Enable autocomplete (remove TODO comment)

**Phase 2: Enhance with fuzzy matching (v1.16.0)**

6. Add fuzzy matching for file paths (built-in to library)
7. Add keyboard shortcuts for common completions
8. Add icons/badges for different completion types

**Phase 3: Remove file limit (v1.17.0)**

9. Remove `MAX_FILES = 100` limit
10. Implement virtual scrolling via library features
11. Add file count indicator in dropdown

**Estimated effort:** 1-2 days (mostly refactoring existing code)

**Sources:**
- [GitHub: textual-autocomplete](https://github.com/darrenburns/textual-autocomplete)
- [PyPI: textual-autocomplete](https://pypi.org/project/textual-autocomplete/)
- [Textual issue: AutoComplete widget](https://github.com/Textualize/textual/issues/3362)
- [GitHub discussions: Input autocomplete](https://github.com/Textualize/textual/issues/2330)

---

## 2. Tabbed Content for Multiple Outputs

### Problem Statement

Current ppxaide handles multiple outputs by:
- Single `RichLog` for chat responses
- No separation between tool outputs and chat
- No way to view multiple tool executions simultaneously
- Grid layout proposed but limited to 2-4 panels

### Solution: Built-in TabbedContent

**Widget:** `textual.widgets.TabbedContent` (built-in)
**Added:** Textual 0.16.0 (March 2023)
**Status:** Stable, actively maintained

#### Features

- ✅ **Dynamic tabs** - Add/remove tabs programmatically
- ✅ **Keyboard navigation** - Ctrl+Tab, arrow keys
- ✅ **Closeable tabs** - Optional X button on tabs
- ✅ **Programmatic switching** - `active` reactive property
- ✅ **Events** - `TabActivated`, `TabDisabled` messages
- ✅ **Nested tabs** - Tabs within tabs for complex layouts
- ✅ **Async-friendly** - Methods are optionally awaitable

#### Basic Usage

```python
from textual.widgets import TabbedContent, TabPane, RichLog

class OutputArea(Widget):
    def compose(self):
        with TabbedContent(id="outputs"):
            with TabPane("Chat", id="chat"):
                yield RichLog(auto_scroll=True)
            with TabPane("Tools", id="tools"):
                yield RichLog(auto_scroll=True)
```

#### Dynamic Tab Management

```python
class ChatApp(App):
    def __init__(self):
        super().__init__()
        self.tab_counter = 0

    async def create_tool_output_tab(self, tool_name: str, tool_id: str):
        """Create a new tab for tool execution."""
        outputs = self.query_one("#outputs", TabbedContent)

        # Create unique tab ID
        tab_id = f"tool-{self.tab_counter}"
        self.tab_counter += 1

        # Create RichLog for streaming
        log = RichLog(auto_scroll=True, markup=True, id=f"log-{tab_id}")

        # Add tab with closeable option
        await outputs.add_pane(
            TabPane(
                f"🔧 {tool_name}",
                log,
                id=tab_id,
                closable=True  # Add X button
            )
        )

        # Switch to new tab
        outputs.active = tab_id

        return log

    async def handle_tool_execution(self, tool_name: str, tool_id: str):
        """Stream tool output to dedicated tab."""
        log = await self.create_tool_output_tab(tool_name, tool_id)

        async for chunk in execute_tool(tool_name):
            log.write(chunk)

        # Mark completion in tab title
        outputs = self.query_one("#outputs", TabbedContent)
        pane = outputs.query_one(f"#{outputs.active}", TabPane)
        pane.label = f"✅ {tool_name}"
```

#### Available Methods

```python
# Add a new tab
await tabbed_content.add_pane(TabPane("Title", widget, id="tab-id"))

# Remove a tab
await tabbed_content.remove_pane("tab-id")

# Clear all tabs
await tabbed_content.clear_panes()

# Get tab count
count = tabbed_content.tab_count

# Switch to a tab
tabbed_content.active = "tab-id"

# Get current tab ID
current = tabbed_content.active
```

#### Events

```python
def on_tabbed_content_tab_activated(self, event: TabbedContent.TabActivated):
    """Handle tab activation."""
    tab_id = event.tab.id
    self.log(f"Switched to: {tab_id}")

def on_tabbed_content_tab_disabled(self, event: TabbedContent.TabDisabled):
    """Handle tab disabled."""
    pass
```

#### Hybrid Layout: Chat + Tabbed Outputs

**Best UX for ppxaide:**

```python
class PPXAIDEApp(App):
    def compose(self):
        with Horizontal():
            # Left: File browser (toggle-able, 30%)
            with Vertical(id="sidebar"):
                yield DirectoryTree("/path/to/project")

            # Right: Main area (70%)
            with Vertical(id="main-area"):
                # Top: Chat history (60%, fixed)
                with VerticalScroll(id="chat-area"):
                    yield RichLog(id="chat-log", auto_scroll=True)

                # Middle: Input box (fixed height)
                yield InputBox(id="input")

                # Bottom: Tabbed tool outputs (40%, dynamic)
                with TabbedContent(id="tool-outputs"):
                    # Default tab
                    with TabPane("Status", id="status"):
                        yield Static("Ready")
                    # Tool execution tabs added dynamically
```

**CSS:**
```css
#sidebar {
    width: 30%;
    border-right: solid $accent;
}

#main-area {
    width: 70%;
}

#chat-area {
    height: 50%;
    border-bottom: solid $accent;
}

#input {
    height: 3;
}

#tool-outputs {
    height: 1fr;  /* Fill remaining space */
}
```

#### Known Issues

**DuplicateIds Exception (Issue #5215):**
When rapidly removing and adding tabs, may crash with DuplicateIds.

**Workaround:**
```python
# Always use unique IDs with incrementing counter
self.tab_counter = 0

def create_tab(self):
    tab_id = f"tab-{self.tab_counter}"
    self.tab_counter += 1
    return TabPane("Title", widget, id=tab_id)
```

**Sources:**
- [Textual: TabbedContent widget](https://textual.textualize.io/widgets/tabbed_content/)
- [Textual: Tabs widget](https://textual.textualize.io/widgets/tabs/)
- [GitHub PR #2751: Dynamic tab management](https://github.com/Textualize/textual/pull/2751)
- [Blog: Textual 0.16.0 adds TabbedContent](https://textual.textualize.io/blog/2023/03/22/textual-0160-adds-tabbedcontent-and-border-titles/)
- [Tutorial: Using TabbedContent](https://www.blog.pythonlibrary.org/2023/04/25/textual-101-using-the-tabbedcontent-widget/)

---

## 3. File Browser Sidebar (VSCode-style)

### Problem Statement

ppxaide currently has:
- No project file browser
- Users must type file paths manually for `/show` and `/edit`
- No visual navigation of project structure

### Solution: Built-in DirectoryTree

**Widget:** `textual.widgets.DirectoryTree` (built-in)
**Status:** Stable, extends `Tree` widget

#### Features

- ✅ **Async loading** - Non-blocking directory scanning
- ✅ **Expandable folders** - Click to expand/collapse
- ✅ **Keyboard navigation** - Arrow keys, Enter to select
- ✅ **File filtering** - Override `filter_paths()` method
- ✅ **Events** - `FileSelected`, `DirectorySelected` messages
- ✅ **Custom styling** - CSS for colors, borders, icons
- ✅ **Hide/show** - Toggle visibility with keybinding

#### Basic Usage

```python
from textual.widgets import DirectoryTree

class FileExplorer(App):
    def compose(self):
        yield DirectoryTree("/path/to/project", id="file-tree")

    def on_directory_tree_file_selected(self, event):
        """Handle file selection."""
        file_path = event.path
        self.show_file(file_path)

    def on_directory_tree_directory_selected(self, event):
        """Handle directory selection."""
        dir_path = event.path
        self.log(f"Selected directory: {dir_path}")
```

#### Custom Filtering

```python
class FilteredDirectoryTree(DirectoryTree):
    """DirectoryTree with .git, node_modules, __pycache__ filtering."""

    IGNORE_PATTERNS = {'.git', 'node_modules', '__pycache__', '.venv', 'dist', 'build'}

    def filter_paths(self, paths: Iterable[Path]) -> Iterable[Path]:
        """Filter out ignored directories and files."""
        return [
            p for p in paths
            if not any(ignore in p.parts for ignore in self.IGNORE_PATTERNS)
        ]
```

#### Hide/Show Sidebar

```python
class PPXAIDEApp(App):
    BINDINGS = [
        ("ctrl+b", "toggle_sidebar", "Toggle Sidebar"),
    ]

    def action_toggle_sidebar(self):
        """Toggle file browser sidebar (Ctrl+B)."""
        sidebar = self.query_one("#sidebar")
        sidebar.display = not sidebar.display
```

#### Integration with Commands

```python
def on_directory_tree_file_selected(self, event):
    """Handle file selection - auto-run /show."""
    file_path = event.path

    # Auto-execute /show command
    input_box = self.query_one("#input", InputBox)
    input_box.value = f"/show {file_path}"
    self.execute_command(f"/show {file_path}")
```

#### Enhanced Alternative: textual-universal-directorytree

**Library:** [juftin/textual-universal-directorytree](https://github.com/juftin/textual-universal-directorytree)
**Features:** Support for remote filesystems (S3, SSH, etc.) via `fsspec`

```bash
pip install textual-universal-directorytree
```

```python
from textual_universal_directorytree import UniversalDirectoryTree

# Local filesystem
yield UniversalDirectoryTree("/path/to/project")

# S3 bucket
yield UniversalDirectoryTree("s3://my-bucket/path")

# SSH
yield UniversalDirectoryTree("ssh://user@host/path")
```

**Use case for ppxaide:** Browsing remote project files when using ppxai-server

**Sources:**
- [Textual: DirectoryTree widget](https://textual.textualize.io/widgets/directory_tree/)
- [Textual: Tree widget](https://textual.textualize.io/widgets/tree/)
- [GitHub: textual-universal-directorytree](https://github.com/juftin/textual-universal-directorytree)
- [DeepWiki: DirectoryTree examples](https://deepwiki.com/Textualize/textual/6.4-tree-and-directorytree-widgets)

---

## 4. Streaming Chat Interface

### Problem Statement

ppxaide needs to:
- Stream chat responses chunk-by-chunk (already working)
- Auto-scroll to latest message
- Allow scrolling up to view history
- Handle multiple concurrent streams (tool outputs)

### Solution: Built-in RichLog

**Widget:** `textual.widgets.RichLog` (built-in)
**Status:** Stable, purpose-built for streaming logs

#### Features

- ✅ **Auto-scroll** - Scrolls to bottom when new content added
- ✅ **Rich formatting** - Markdown, syntax highlighting, tables
- ✅ **Thread-safe** - Works with async workers
- ✅ **Max lines** - Auto-truncate old content
- ✅ **Anchoring** - Keep at bottom while allowing scroll-up
- ✅ **High performance** - Handles rapid updates

#### Basic Usage

```python
from textual.widgets import RichLog

class ChatArea(Widget):
    def compose(self):
        yield RichLog(
            id="chat-log",
            auto_scroll=True,    # Auto-scroll to bottom
            max_lines=1000,      # Keep last 1000 lines
            markup=True,         # Enable Rich markup
            highlight=True,      # Syntax highlighting
        )
```

#### Streaming Chat Response

```python
async def stream_chat_response(self, prompt: str):
    """Stream chat response to RichLog."""
    chat_log = self.query_one("#chat-log", RichLog)

    # User message
    chat_log.write(f"[bold cyan]You:[/bold cyan] {prompt}")
    chat_log.write("")  # Blank line

    # Start AI response
    chat_log.write("[bold green]AI:[/bold green] ", end="")

    # Stream response chunks
    response_text = ""
    async for chunk in engine_client.send_message(prompt):
        response_text += chunk
        # Update last line with accumulated response
        chat_log.write(chunk, end="")

    chat_log.write("")  # End line
    chat_log.write("─" * 80)  # Separator
```

#### Methods

```python
# Write text (appends new line)
log.write("Hello world")

# Write without newline
log.write("Streaming...", end="")

# Clear all content
log.clear()

# Scroll to end
log.scroll_end()
```

#### Combining with TabbedContent

```python
# Separate logs for different outputs
with TabbedContent(id="outputs"):
    with TabPane("Chat", id="chat"):
        yield RichLog(id="chat-log", auto_scroll=True)

    with TabPane("Debug", id="debug"):
        yield RichLog(id="debug-log", auto_scroll=True)

    with TabPane("Errors", id="errors"):
        yield RichLog(id="error-log", auto_scroll=True)
```

**Sources:**
- [Textual: RichLog widget](https://textual.textualize.io/widgets/rich_log/)
- [GitHub: RichLog source](https://github.com/Textualize/textual/blob/main/src/textual/widgets/_rich_log.py)
- [Medium: Building a Responsive Textual Chat UI](https://oneryalcin.medium.com/building-a-responsive-textual-chat-ui-with-long-running-processes-c0c53cd36224)
- [Blog: Using Textual to Build a ChatGPT TUI](https://chaoticengineer.hashnode.dev/textual-and-chatgpt)

---

## 5. Split Panes and Layout

### Problem Statement

Need flexible layout system for:
- Resizable sidebar (30% / 70% split)
- Multiple output areas (top/bottom split)
- Dynamic hide/show of panels

### Solution: Built-in Layout Containers

**Containers:** `textual.containers.*` (built-in)
**Status:** Stable, core framework feature

#### Available Containers

| Container | Purpose | Scroll |
|-----------|---------|--------|
| `Horizontal` | Side-by-side layout | No |
| `Vertical` | Stacked layout | No |
| `HorizontalScroll` | Side-by-side with scrollbar | X-axis |
| `VerticalScroll` | Stacked with scrollbar | Y-axis |
| `Grid` | CSS Grid-style (2x2, 3x3, etc.) | No |
| `Center` | Center child widget | No |
| `Container` | Generic container | No |
| `ScrollableContainer` | Generic with scroll | Both |

#### Basic Layout

```python
from textual.containers import Horizontal, Vertical, VerticalScroll

class Layout(App):
    def compose(self):
        with Horizontal():
            # Left pane (30%)
            with Vertical(id="left"):
                yield DirectoryTree("/project")

            # Right pane (70%)
            with Vertical(id="right"):
                yield VerticalScroll(RichLog())
```

**CSS:**
```css
#left {
    width: 30%;
    border-right: solid $accent;
}

#right {
    width: 70%;
}
```

#### Docking (Sticky Panels)

```python
# Dock to edges
yield Header().dock(edge="top")
yield Footer().dock(edge="bottom")
yield DirectoryTree("/project").dock(edge="left", size=30)
```

**Sources:**
- [Textual: Layout Guide](https://textual.textualize.io/guide/layout/)
- [Textual: Design a Layout](https://textual.textualize.io/how-to/design-a-layout/)
- [Textual: Containers API](https://textual.textualize.io/api/containers/)
- [Real Python: Textual Tutorial](https://realpython.com/python-textual/)

---

## 6. Additional Third-Party Widgets

### Useful Community Libraries

| Library | Purpose | GitHub | Status |
|---------|---------|--------|--------|
| **textual-filedrop** | Drag & drop files into terminal | [agmmnn/textual-filedrop](https://github.com/agmmnn/textual-filedrop) | ✅ Active |
| **textual-slider** | Integer slider widget | [TomJGooding/textual-slider](https://github.com/TomJGooding/textual-slider) | ✅ Active |
| **textual-plotext** | Terminal plots/charts | [Textualize/textual-plotext](https://github.com/Textualize/textual-plotext) | ✅ Official |
| **zandev_textual_widgets** | File picker, dropdowns, dialogs | [ZandevOxford/zandev_textual_widgets](https://github.com/ZandevOxford/zandev_textual_widgets) | ✅ Active |
| **textual_extras** | Experimental widgets collection | [kraanzu/textual_extras](https://github.com/kraanzu/textual_extras) | ⚠️ WIP |
| **textual-textarea** | VSCode-like text editor | [tconbeer/textual-textarea](https://github.com/tconbeer/textual-textarea) | ✅ Active |
| **textual-image** | Terminal image display | [Textualize/textual-image](https://github.com/Textualize/textual-image) | ✅ Official |

### Comprehensive Resource Lists

- [awesome-textualize-projects](https://oleksis.github.io/awesome-textualize-projects/) - Curated list
- [transcendent-textual](https://github.com/davep/transcendent-textual) - Dave Pearson's collection
- [Textual Widget Gallery](https://textual.textualize.io/widget_gallery/) - Official examples

**Sources:**
- [GitHub: textual-filedrop](https://github.com/agmmnn/textual-filedrop)
- [GitHub: textual-slider](https://github.com/TomJGooding/textual-slider)
- [GitHub: textual-plotext](https://github.com/Textualize/textual-plotext)
- [awesome-textualize-projects](https://oleksis.github.io/awesome-textualize-projects/)

---

## 7. Implementation Roadmap

### v1.16.0 (Q2 2026) - Core UX Improvements

**Priority 1: Autocomplete (1-2 days)**
- [ ] Add `textual-autocomplete = "^4.0.6"` to dependencies
- [ ] Remove `ppxai/tui/widgets/completion_popup.py`
- [ ] Refactor `ppxai/tui/completer.py` to return `DropdownItem` objects
- [ ] Update `InputBox` to use `AutoComplete` wrapper
- [ ] Enable autocomplete (remove disable comment)
- [ ] Test slash commands, @file, @clipboard, @url completions
- [ ] Add fuzzy matching for file paths

**Priority 2: Tabbed Outputs (1 day)**
- [ ] Replace single `RichLog` with `TabbedContent`
- [ ] Add default "Chat" tab
- [ ] Implement dynamic tab creation for tool executions
- [ ] Add tab close keybinding (Ctrl+W)
- [ ] Add status indicators (🔧 running, ✅ complete, ❌ error)

**Priority 3: File Browser Sidebar (1 day)**
- [ ] Add `FilteredDirectoryTree` widget
- [ ] Implement Ctrl+B toggle keybinding
- [ ] Connect to `/show` command on file selection
- [ ] Add context menu for file operations (future)

**Estimated total:** 3-4 days

### v1.17.0 (Q3 2026) - Advanced Features

**Priority 1: Enhanced Autocomplete**
- [ ] Remove 100 file limit
- [ ] Add virtual scrolling
- [ ] Add file count indicator
- [ ] Add icons/badges for completion types

**Priority 2: Split View Layouts**
- [ ] Implement resizable split panes
- [ ] Add vertical/horizontal split commands
- [ ] Add layout persistence

**Priority 3: Advanced File Browser**
- [ ] Consider `textual-universal-directorytree` for remote files
- [ ] Add file search/filter
- [ ] Add file operations (rename, delete, create)

**Estimated total:** 5-7 days

---

## 8. Comparison: Rich TUI vs Textual TUI (Updated)

| Feature | Rich TUI (ppxai) | Textual TUI (ppxaide v1.15.0) | Textual TUI (ppxaide v1.16.0) |
|---------|------------------|-------------------------------|-------------------------------|
| **Autocomplete** | ✅ prompt_toolkit (cursor-based) | ❌ Disabled (UI issues) | ✅ textual-autocomplete |
| **File browser** | ❌ No | ❌ No | ✅ DirectoryTree |
| **Tabbed outputs** | ❌ No | ❌ No | ✅ TabbedContent |
| **Split panes** | ❌ No | ⚠️ Basic grid | ✅ Advanced layouts |
| **Themes** | ⚠️ 6 themes | ✅ 17+ themes | ✅ 17+ themes |
| **Async streaming** | ⚠️ Threading | ✅ Native async | ✅ Native async |
| **Code editing** | ❌ Read-only | ✅ TextArea (syntax) | ✅ TextArea (syntax) |

**Conclusion:** v1.16.0 will achieve feature parity with Rich TUI and add significant new capabilities.

---

## 9. References

### Official Textual Documentation

- [Textual Homepage](https://textual.textualize.io/)
- [Widget Gallery](https://textual.textualize.io/widget_gallery/)
- [Layout Guide](https://textual.textualize.io/guide/layout/)
- [Widgets API](https://textual.textualize.io/guide/widgets/)
- [Tutorial](https://textual.textualize.io/tutorial/)

### Third-Party Libraries

- [textual-autocomplete](https://github.com/darrenburns/textual-autocomplete)
- [textual-universal-directorytree](https://github.com/juftin/textual-universal-directorytree)
- [textual-textarea](https://github.com/tconbeer/textual-textarea)
- [awesome-textualize-projects](https://oleksis.github.io/awesome-textualize-projects/)

### Tutorials & Examples

- [Real Python: Python Textual Tutorial](https://realpython.com/python-textual/)
- [Building a Responsive Textual Chat UI](https://oneryalcin.medium.com/building-a-responsive-textual-chat-ui-with-long-running-processes-c0c53cd36224)
- [Using Textual to Build a ChatGPT TUI](https://chaoticengineer.hashnode.dev/textual-and-chatgpt)
- [Textual 101 Series](https://www.blog.pythonlibrary.org/tag/textual/)

---

**Document Status:** Final
**Next Steps:** Implement textual-autocomplete in v1.16.0 development branch
