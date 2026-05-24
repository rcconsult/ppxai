# TUI Command Architecture Refactoring - Type-Based Rendering

**Version:** v1.15.0
**Status:** PROPOSAL - Awaiting approval
**Approach:** Full clean refactoring - UI-agnostic commands with type-based renderer dispatch

---

## Executive Summary

**Goal:** Refactor command architecture with formal protocol and mechanical UI bindings.

**Design Principles:**
1. **Commands return typed result objects** - TextResult, TableResult, TreeResult, etc.
2. **Type-based renderer dispatch** - Each TUI registers renderers for result types
3. **Mechanical UI bindings** - `renderer.render(result)` with zero conditional logic
4. **Data-driven rendering** - Result types drive rendering, not command names
5. **Framework-agnostic commands** - Commands have zero UI dependencies

**Scope:**
- ✅ Define result type hierarchy (17 result types including CompositeResult, ImageResult, ToolExecutionResult)
- ✅ Create renderer base class with type-based dispatch registry
- ✅ Implement RichRenderer and TextualRenderer with registered handlers
- ✅ Refactor all 54 existing commands to return typed results
- ✅ Update Rich TUI to use mechanical renderer dispatch
- ✅ Update Textual TUI to use mechanical renderer dispatch
- ✅ Redesign Textual side panel for multi-artifact display (tiling or tabbed view)
- ✅ Add framework-specific commands (show, edit, theme)
- ❌ No web/VSCode/server changes

**Benefits:**
- **Formal protocol** - Result types define the contract between commands and UIs
- **Mechanical bindings** - Renderer registry eliminates conditional rendering logic
- **Type-safe** - Each result type has defined structure, validated at compile time
- **Testable** - Commands return data structures, test without any UI framework
- **Extensible** - Add new result type + renderers, all commands work everywhere
- **Data-driven** - UI rendering is automatic based on result type

---

## Core Architecture

### Result Type Hierarchy

```python
# ppxai/commands/results.py (NEW)

from dataclasses import dataclass, field
from typing import Any, Optional, Dict, List
from enum import Enum
from abc import ABC


class ResultStatus(Enum):
    """Command execution status."""
    SUCCESS = "success"
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass
class CommandResult(ABC):
    """Base result type - all results inherit from this.

    Commands return specific result types (TextResult, TableResult, etc.).
    Renderer dispatch is type-based - no conditional logic needed.
    """
    status: ResultStatus
    message: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def success(self) -> bool:
        return self.status == ResultStatus.SUCCESS

    @property
    def failed(self) -> bool:
        return self.status == ResultStatus.ERROR


# ============================================================================
# Concrete Result Types
# ============================================================================

@dataclass
class TextResult(CommandResult):
    """Simple text message result.

    Used for: success/error messages, simple confirmations

    Example:
        TextResult(
            status=ResultStatus.SUCCESS,
            message="Session saved: my-session"
        )
    """
    error_details: Optional[str] = None


@dataclass
class TableResult(CommandResult):
    """Tabular data result.

    Used for: session lists, tool lists, usage stats, provider lists

    Example:
        TableResult(
            status=ResultStatus.SUCCESS,
            message="3 sessions found",
            columns=["Name", "Created", "Provider", "Model"],
            rows=[
                ["session1", "2024-01-20", "perplexity", "sonar"],
                ["session2", "2024-01-21", "openai", "gpt-4"]
            ]
        )
    """
    columns: List[str] = field(default_factory=list)
    rows: List[List[str]] = field(default_factory=list)


@dataclass
class ListResult(CommandResult):
    """List of items with optional styling.

    Used for: provider lists, model lists, file lists

    Example:
        ListResult(
            status=ResultStatus.SUCCESS,
            message="5 providers available",
            items=[
                {"text": "perplexity", "icon": "🌐", "badge": "default"},
                {"text": "openai", "icon": "🤖", "badge": "premium"}
            ]
        )
    """
    items: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class TreeResult(CommandResult):
    """Hierarchical tree structure result.

    Used for: context sources, file trees, nested config

    Example:
        TreeResult(
            status=ResultStatus.SUCCESS,
            message="Context sources loaded",
            root={
                "label": "Bootstrap Context",
                "children": [
                    {"label": "~/.ppxai/AGENTS.md [global] 1.2KB", "children": []},
                    {"label": "project/AGENTS.md [project] 3.5KB", "children": []}
                ]
            }
        )
    """
    root: Dict[str, Any] = field(default_factory=dict)


@dataclass
class FileViewResult(CommandResult):
    """File content with syntax highlighting.

    Used for: code display, log viewing, config file inspection

    Example:
        FileViewResult(
            status=ResultStatus.SUCCESS,
            message="Opened config.json",
            filepath="/path/to/config.json",
            content='{"key": "value"}',
            language="json",
            line_highlight=5
        )
    """
    filepath: str = ""
    content: str = ""
    language: Optional[str] = None
    line_highlight: Optional[int] = None
    read_only: bool = True


@dataclass
class ProgressResult(CommandResult):
    """Progress indicator for long operations.

    Used for: agent task progress, file downloads, batch operations

    Example:
        ProgressResult(
            status=ResultStatus.INFO,
            message="Processing files",
            current=7,
            total=10,
            description="Analyzing file.py"
        )
    """
    current: int = 0
    total: int = 100
    description: str = ""


@dataclass
class KeyValueResult(CommandResult):
    """Key-value pairs result.

    Used for: config display, version info, status information

    Example:
        KeyValueResult(
            status=ResultStatus.SUCCESS,
            message="System information",
            pairs={
                "Version": "1.15.0",
                "Python": "3.11.5",
                "Platform": "macOS-arm64"
            }
        )
    """
    pairs: Dict[str, str] = field(default_factory=dict)
```

### Renderer Base Class with Type-Based Dispatch

```python
# ppxai/rendering/base.py (NEW)

from typing import Callable, Dict, Type
from ppxai.commands.results import CommandResult


class Renderer:
    """Base renderer with type-based dispatch registry.

    Each TUI framework subclasses this and registers rendering
    functions for each result type. Dispatch is mechanical -
    just type lookup, zero conditional logic.

    Example:
        @RichRenderer.register(TableResult)
        def render_table(result: TableResult):
            # Rich-specific table rendering
            table = Table()
            ...

        # Later, mechanical dispatch
        result = command_handler(context, args)
        RichRenderer.render(result)  # Automatically calls render_table()
    """

    _registry: Dict[Type[CommandResult], Callable] = {}

    @classmethod
    def register(cls, result_type: Type[CommandResult]):
        """Decorator to register renderer for result type.

        Args:
            result_type: Result class to handle (e.g., TableResult)

        Returns:
            Decorator function
        """
        def decorator(func: Callable):
            cls._registry[result_type] = func
            return func
        return decorator

    @classmethod
    def render(cls, result: CommandResult):
        """Dispatch result to appropriate renderer - MECHANICAL.

        No conditional logic - just type lookup and call.

        Args:
            result: Command result to render

        Raises:
            KeyError: If no renderer registered for result type
        """
        result_type = type(result)

        # Get renderer function for this type
        if result_type not in cls._registry:
            # Fallback to base TextResult renderer
            result_type = TextResult

        renderer_func = cls._registry.get(result_type)
        if not renderer_func:
            raise KeyError(f"No renderer registered for {result_type}")

        return renderer_func(result)


class AsyncRenderer(Renderer):
    """Async variant for Textual TUI.

    Same pattern, but renderers are async functions.
    """

    @classmethod
    async def render(cls, result: CommandResult):
        """Async dispatch - for Textual widgets."""
        result_type = type(result)

        if result_type not in cls._registry:
            result_type = TextResult

        renderer_func = cls._registry.get(result_type)
        if not renderer_func:
            raise KeyError(f"No renderer registered for {result_type}")

        return await renderer_func(result)
```

### Command Handler Protocol

```python
# ppxai/commands/protocol.py (NEW)

from typing import Protocol, runtime_checkable, Callable
from .results import CommandResult


@runtime_checkable
class CommandContext(Protocol):
    """Context provided to commands.

    Commands receive minimal context - just what they need.
    No UI framework dependencies.
    """
    engine_client: Any  # EngineClient
    current_model: str
    provider: str
    working_dir: str

    def set_model(self, model: str) -> None: ...
    def set_provider(self, provider: str) -> None: ...


# Command handler signature - returns typed result
CommandHandler = Callable[[CommandContext, str], CommandResult]
```

---

## Renderer Implementations

### Rich TUI Renderer

```python
# ppxai/rendering/rich_renderer.py (NEW)

from rich.console import Console
from rich.table import Table
from rich.tree import Tree
from rich.syntax import Syntax
from .base import Renderer
from ..commands.results import *

console = Console()


class RichRenderer(Renderer):
    """Rich console renderer with type-based dispatch."""
    pass


@RichRenderer.register(TextResult)
def render_text(result: TextResult):
    """Render simple text message."""
    if result.status == ResultStatus.SUCCESS:
        console.print(f"[green]{result.message}[/green]")
    elif result.status == ResultStatus.ERROR:
        console.print(f"[red]{result.message}[/red]")
        if result.error_details:
            console.print(f"[dim]{result.error_details}[/dim]")
    elif result.status == ResultStatus.WARNING:
        console.print(f"[yellow]{result.message}[/yellow]")
    else:  # INFO
        console.print(result.message)


@RichRenderer.register(TableResult)
def render_table(result: TableResult):
    """Render table with Rich Table widget."""
    table = Table(title=result.message if result.status != ResultStatus.SUCCESS else None)

    # Add columns
    for col in result.columns:
        table.add_column(col, style="cyan")

    # Add rows
    for row in result.rows:
        table.add_row(*[str(cell) for cell in row])

    console.print(table)


@RichRenderer.register(ListResult)
def render_list(result: ListResult):
    """Render list with bullets/icons."""
    console.print(f"[bold]{result.message}[/bold]\n")

    for item in result.items:
        icon = item.get("icon", "•")
        text = item.get("text", "")
        badge = item.get("badge", "")
        console.print(f"{icon} {text} [dim]{badge}[/dim]")


@RichRenderer.register(TreeResult)
def render_tree(result: TreeResult):
    """Render hierarchical tree."""
    console.print(f"[bold]{result.message}[/bold]\n")

    tree = Tree(result.root.get("label", "Root"))

    def add_children(node, data):
        for child in data.get("children", []):
            child_node = node.add(child.get("label", ""))
            add_children(child_node, child)

    add_children(tree, result.root)
    console.print(tree)


@RichRenderer.register(FileViewResult)
def render_file_view(result: FileViewResult):
    """Render file with syntax highlighting."""
    console.print(f"[bold]{result.message}[/bold]\n")

    syntax = Syntax(
        result.content,
        result.language or "text",
        theme="monokai",
        line_numbers=True,
        highlight_lines={result.line_highlight} if result.line_highlight else set()
    )
    console.print(syntax)


@RichRenderer.register(KeyValueResult)
def render_key_value(result: KeyValueResult):
    """Render key-value pairs."""
    console.print(f"[bold]{result.message}[/bold]\n")

    max_key_len = max(len(k) for k in result.pairs.keys()) if result.pairs else 0

    for key, value in result.pairs.items():
        console.print(f"  [cyan]{key.ljust(max_key_len)}[/cyan] : {value}")


@RichRenderer.register(ProgressResult)
def render_progress(result: ProgressResult):
    """Render progress indicator."""
    from rich.progress import Progress

    # For simple progress, just show percentage
    pct = int((result.current / result.total) * 100)
    console.print(f"{result.message} [{pct}%] {result.description}")
```

### Textual TUI Renderer

```python
# ppxai/rendering/textual_renderer.py (NEW)

from textual.widgets import DataTable, Tree, Static
from .base import AsyncRenderer
from ..commands.results import *
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..tui.app import PPXAIDEApp


class TextualRenderer(AsyncRenderer):
    """Textual TUI renderer with type-based dispatch.

    Requires app instance for widget access.
    """

    def __init__(self, app: "PPXAIDEApp"):
        self.app = app
        self.chat_view = app.query_one("#chat-view", ChatView)


@TextualRenderer.register(TextResult)
async def render_text(renderer: TextualRenderer, result: TextResult):
    """Render simple text message."""
    if result.status == ResultStatus.SUCCESS:
        renderer.chat_view.add_system_message(f"[green]{result.message}[/green]")
    elif result.status == ResultStatus.ERROR:
        msg = f"[red]{result.message}[/red]"
        if result.error_details:
            msg += f"\n[dim]{result.error_details}[/dim]"
        renderer.chat_view.add_system_message(msg)
    elif result.status == ResultStatus.WARNING:
        renderer.chat_view.add_system_message(f"[yellow]{result.message}[/yellow]")
    else:  # INFO
        renderer.chat_view.add_system_message(result.message)


@TextualRenderer.register(TableResult)
async def render_table(renderer: TextualRenderer, result: TableResult):
    """Render table with DataTable widget in side panel."""
    table = DataTable()
    table.add_columns(*result.columns)

    for row in result.rows:
        table.add_row(*row)

    await renderer.app.show_widget_in_panel(table, title=result.message)
    renderer.chat_view.add_system_message(f"[dim]{result.message} (opened in side panel)[/dim]")


@TextualRenderer.register(ListResult)
async def render_list(renderer: TextualRenderer, result: ListResult):
    """Render list in chat view."""
    lines = [f"[bold]{result.message}[/bold]\n"]

    for item in result.items:
        icon = item.get("icon", "•")
        text = item.get("text", "")
        badge = item.get("badge", "")
        lines.append(f"{icon} {text} [dim]{badge}[/dim]")

    renderer.chat_view.add_system_message("\n".join(lines))


@TextualRenderer.register(TreeResult)
async def render_tree(renderer: TextualRenderer, result: TreeResult):
    """Render tree in side panel."""
    tree = Tree(result.root.get("label", "Root"))

    def add_children(node, data):
        for child in data.get("children", []):
            child_node = node.add(child.get("label", ""))
            add_children(child_node, child)

    add_children(tree, result.root)

    await renderer.app.show_widget_in_panel(tree, title=result.message)
    renderer.chat_view.add_system_message(f"[dim]{result.message} (opened in side panel)[/dim]")


@TextualRenderer.register(FileViewResult)
async def render_file_view(renderer: TextualRenderer, result: FileViewResult):
    """Render file in CodeEditor widget."""
    from pathlib import Path

    await renderer.app.show_file_in_panel(
        Path(result.filepath),
        result.content,
        mode="code",
        line=result.line_highlight,
        read_only=result.read_only
    )

    renderer.chat_view.add_system_message(f"[dim]{result.message}[/dim]")


@TextualRenderer.register(KeyValueResult)
async def render_key_value(renderer: TextualRenderer, result: KeyValueResult):
    """Render key-value pairs."""
    lines = [f"[bold]{result.message}[/bold]\n"]

    max_key_len = max(len(k) for k in result.pairs.keys()) if result.pairs else 0

    for key, value in result.pairs.items():
        lines.append(f"  [cyan]{key.ljust(max_key_len)}[/cyan] : {value}")

    renderer.chat_view.add_system_message("\n".join(lines))


@TextualRenderer.register(ProgressResult)
async def render_progress(renderer: TextualRenderer, result: ProgressResult):
    """Render progress in status bar or chat."""
    pct = int((result.current / result.total) * 100)
    renderer.chat_view.add_system_message(
        f"{result.message} [{pct}%] {result.description}"
    )
```

---

## Multi-Artifact Display Architecture (Textual TUI Side Panel)

### Problem Statement

Tool execution (e.g., pandas scripts) can produce multiple outputs:
- Generated images/plots (matplotlib charts)
- Data tables (summary statistics)
- Text output (logs, stdout)

**Current limitation:** Side panel shows one widget at a time. Need to display multiple artifacts simultaneously or allow easy navigation between them.

### Proposed Solutions

#### Option A: Tiling Layout (Split Panes)

```
┌─────────────────────┬─────────────────────┐
│                     │ Image: sales.png    │
│  Chat View          │ [matplotlib chart]  │
│  (messages)         ├─────────────────────┤
│                     │ Table: Summary      │
│                     │  Mean   | 42.5      │
│                     │  Median | 38.0      │
└─────────────────────┴─────────────────────┘
```

**Benefits:**
- See multiple outputs at once
- Compare data side-by-side
- Natural for small number of artifacts (2-3)

**Challenges:**
- Screen space limited (especially on vertical split)
- Complex layout management
- May not scale well for 4+ artifacts

#### Option B: Tabbed View (Navigation)

```
┌─────────────────────┬─────────────────────┐
│                     │ ┌─[Chart]─[Table]─┐ │
│  Chat View          │ │ Image: sales.png│ │
│  (messages)         │ │ [matplotlib]    │ │
│                     │ │                 │ │
│                     │ └─────────────────┘ │
└─────────────────────┴─────────────────────┘
     Press Tab to cycle, Ctrl+1/2/3 for direct
```

**Benefits:**
- Each artifact gets full panel space
- Scales to any number of artifacts
- Simple keyboard navigation (Tab, Ctrl+N)
- Existing Textual TabbedContent widget

**Challenges:**
- Only one artifact visible at a time
- Need to switch tabs to compare

#### Recommended: Hybrid Approach

**Phase 1:** Implement tabbed view (simpler, scales better)
**Phase 2:** Add optional tiling for 2-artifact cases (if needed)

### Implementation Plan

**New widget:** `ppxai/tui/widgets/artifact_panel.py`

```python
class ArtifactPanel(TabbedContent):
    """Tabbed panel for displaying multiple tool execution artifacts.

    Features:
    - Tab per artifact (image, table, code, etc.)
    - Keyboard shortcuts: Tab (cycle), Ctrl+1/2/3 (direct)
    - Auto-labels: "Chart", "Table 1", "Output"
    """

    def add_artifact(self, widget: Widget, title: str, icon: str = "") -> None:
        """Add artifact widget as new tab."""
        ...

    def show_artifacts(self, results: List[CommandResult]) -> None:
        """Display multiple result artifacts in tabs."""
        ...
```

**Renderer updates:** `TextualRenderer` for `CompositeResult`/`ToolExecutionResult`

```python
@TextualRenderer.register(CompositeResult)
async def render_composite(renderer: TextualRenderer, result: CompositeResult):
    """Render multiple artifacts in tabbed panel."""
    artifact_panel = ArtifactPanel()

    for i, sub_result in enumerate(result.results):
        # Render each sub-result into widget
        if isinstance(sub_result, ImageResult):
            widget = await create_image_widget(sub_result)
            artifact_panel.add_artifact(widget, f"Chart {i+1}", "📊")
        elif isinstance(sub_result, TableResult):
            widget = create_table_widget(sub_result)
            artifact_panel.add_artifact(widget, f"Table {i+1}", "📋")
        # ... other types

    await renderer.app.show_widget_in_panel(artifact_panel, title=result.message)
```

---

## Refactoring Strategy

### Phase 1: Create Infrastructure (No Breaking Changes)

**New files:**
- `ppxai/commands/results.py` - Result type hierarchy (17 types)
- `ppxai/commands/protocol.py` - CommandContext protocol
- `ppxai/commands/context.py` - Context implementations for each UI
- `ppxai/rendering/__init__.py` - Rendering package
- `ppxai/rendering/base.py` - Renderer base class with type dispatch
- `ppxai/rendering/rich_renderer.py` - Rich TUI renderers (17 handlers)
- `ppxai/rendering/textual_renderer.py` - Textual TUI renderers (17 handlers)
- `ppxai/tui/widgets/artifact_panel.py` - Tabbed multi-artifact panel

**No existing code changed yet.**

---

### Phase 2: Refactor Commands One Category at a Time

#### Example: Session Commands

**BEFORE** (`ppxai/commands/session.py`):
```python
def handle_save(handler: "CommandHandler", args: str) -> None:
    """Save session to JSON."""
    from ..rich.ui import console

    try:
        session_name = handler.engine_client.session.save()
        filepath = handler.engine_client.session.sessions_dir / f"{session_name}.json"
        console.print(f"\n[green]Session saved to:[/green] {filepath}\n")  # ❌ UI-coupled
    except Exception as e:
        console.print(f"[red]Error saving session: {e}[/red]\n")  # ❌ UI-coupled
```

**AFTER** (`ppxai/commands/session.py`):
```python
def handle_save(context: CommandContext, args: str) -> CommandResult:
    """Save session to JSON.

    Returns:
        CommandResult with session name and filepath
    """
    try:
        session_name = context.engine_client.session.save()
        filepath = context.engine_client.session.sessions_dir / f"{session_name}.json"

        return CommandResult(
            status=ResultStatus.SUCCESS,
            message=f"Session saved: {session_name}",
            data={
                "session_name": session_name,
                "filepath": str(filepath)
            }
        )
    except Exception as e:
        return CommandResult(
            status=ResultStatus.ERROR,
            message=f"Error saving session: {e}",
            error_details=str(e)
        )
```

**UI Rendering** - Each TUI decides how to display:

```python
# Rich TUI (ppxai/rich/main.py)
result = CommandFactory.dispatch("save", context, args)
if result.success:
    console.print(f"\n[green]{result.message}[/green]")
    console.print(f"[dim]{result.data['filepath']}[/dim]\n")
else:
    console.print(f"[red]{result.message}[/red]\n")

# Textual TUI (ppxai/tui/app.py)
result = await CommandFactory.dispatch_async("save", context, args)
if result.success:
    chat_view.add_system_message(f"[green]{result.message}[/green]")
else:
    chat_view.add_system_message(f"[red]{result.message}[/red]")
```

---

### Phase 3: Update CommandFactory

**BEFORE** (`ppxai/commands/factory.py`):
```python
@dataclass
class CommandSpec:
    name: str
    description: str
    handler: Callable  # fn(handler: CommandHandler, args: str) -> None
    category: str = "general"
```

**AFTER**:
```python
@dataclass
class CommandSpec:
    name: str
    description: str
    handler: Callable  # fn(context: CommandContext, args: str) -> CommandResult
    category: str = "general"
    aliases: List[str] = field(default_factory=list)
    usage: str = ""
    hidden: bool = False

    # NEW: Client filtering
    clients: List[str] = field(default_factory=lambda: ["all"])
    # Valid: ["all"], ["rich"], ["textual"], ["rich", "textual"]

    # NEW: Async support for UI-specific commands
    is_async: bool = False  # True for Textual show/edit commands


class CommandFactory:
    @classmethod
    def dispatch(cls, name: str, context: CommandContext, args: str = "") -> CommandResult:
        """Dispatch synchronous command.

        Args:
            name: Command name (without /)
            context: Command context (engine, model, etc.)
            args: Command arguments

        Returns:
            CommandResult with status and data

        Raises:
            ValueError: If command not found
        """
        spec = cls.get(name)
        if not spec:
            return CommandResult(
                status=ResultStatus.ERROR,
                message=f"Unknown command: /{name}"
            )

        if spec.is_async:
            return CommandResult(
                status=ResultStatus.ERROR,
                message=f"Command /{name} requires async dispatch"
            )

        try:
            return spec.handler(context, args)
        except Exception as e:
            return CommandResult(
                status=ResultStatus.ERROR,
                message=f"Error executing /{name}: {e}",
                error_details=str(e)
            )

    @classmethod
    async def dispatch_async(cls, name: str, context: Any, args: str = "") -> CommandResult:
        """Dispatch async command (for Textual TUI).

        For sync commands, wraps in executor.
        For async commands, calls directly.
        """
        spec = cls.get(name)
        if not spec:
            return CommandResult(
                status=ResultStatus.ERROR,
                message=f"Unknown command: /{name}"
            )

        try:
            if spec.is_async:
                # Async command - call directly
                return await spec.handler(context, args)
            else:
                # Sync command - run in executor
                import asyncio
                from concurrent.futures import ThreadPoolExecutor

                loop = asyncio.get_event_loop()
                with ThreadPoolExecutor() as executor:
                    return await loop.run_in_executor(
                        executor,
                        spec.handler,
                        context,
                        args
                    )
        except Exception as e:
            return CommandResult(
                status=ResultStatus.ERROR,
                message=f"Error executing /{name}: {e}",
                error_details=str(e)
            )
```

---

### Phase 4: Create Context Implementations

```python
# ppxai/commands/context.py (NEW)

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..engine import EngineClient
    from ..rich.main import CommandHandler as RichHandler
    from ..tui.app import PPXAIDEApp


@dataclass
class RichCommandContext:
    """Command context for Rich TUI.

    Adapts CommandHandler to CommandContext protocol.
    """
    _handler: "RichHandler"

    @property
    def engine_client(self):
        return self._handler.engine_client

    @property
    def current_model(self):
        return self._handler.current_model

    @current_model.setter
    def current_model(self, value):
        self._handler.current_model = value

    @property
    def provider(self):
        return self._handler.provider

    @provider.setter
    def provider(self, value):
        self._handler.provider = value

    @property
    def working_dir(self):
        return self._handler.engine_client.working_dir

    def set_model(self, model: str):
        self._handler.current_model = model
        self._handler.engine_client.set_model(model)

    def set_provider(self, provider: str):
        self._handler.provider = provider
        self._handler.engine_client.set_provider(provider)


@dataclass
class TextualCommandContext:
    """Command context for Textual TUI.

    Adapts PPXAIDEApp to CommandContext protocol.
    """
    _app: "PPXAIDEApp"

    @property
    def engine_client(self):
        return self._app._engine_client

    @property
    def current_model(self):
        return self._app._model

    @current_model.setter
    def current_model(self, value):
        self._app._model = value

    @property
    def provider(self):
        return self._app._provider

    @provider.setter
    def provider(self, value):
        self._app._provider = value

    @property
    def working_dir(self):
        return self._app._working_dir or "."

    def set_model(self, model: str):
        self._app._model = model
        if self._app._engine_client:
            self._app._engine_client.set_model(model)

    def set_provider(self, provider: str):
        self._app._provider = provider
        if self._app._engine_client:
            self._app._engine_client.set_provider(provider)
```

---

## Command Categories Refactoring

### UI-Agnostic Commands (clients=["all"])

These return data, no UI rendering:

| Command | Returns | Data Fields |
|---------|---------|-------------|
| `/save` | Session saved | session_name, filepath |
| `/load` | Session loaded | session_name, message_count |
| `/sessions` | Session list | sessions: [name, created_at, provider, model, messages] |
| `/clear` | History cleared | messages_cleared |
| `/export` | Markdown exported | filename, filepath |
| `/provider` | Provider switched | provider, available_providers |
| `/model` | Model switched | model, available_models |
| `/tools enable/disable` | Tools toggled | enabled, tools_count |
| `/tools list` | Tools list | tools: [name, description, category] |
| `/agent` | Agent status | enabled, task |
| `/context show` | Context info | sources: [path, scope, size], total_tokens |
| `/context reload` | Context reloaded | sources_reloaded |
| `/usage` | Usage stats | tokens, cost, requests |
| `/version` | Version info | version, python_version, platform |
| `/config` | Config shown | config_dict |

**Implementation pattern:**
```python
def handle_command(context: CommandContext, args: str) -> CommandResult:
    # 1. Parse args
    # 2. Call engine/business logic
    # 3. Return CommandResult with data
    return CommandResult(
        status=ResultStatus.SUCCESS,
        message="...",
        data={...}
    )
```

### Textual-Specific Commands (clients=["textual"])

These use Textual widgets, must be async:

```python
# ppxai/tui/commands_textual.py (NEW)

async def handle_show(context: TextualCommandContext, args: str) -> CommandResult:
    """Display file in side panel.

    Uses Textual SidePanel widget - Rich TUI has no equivalent.
    """
    app = context._app
    # Parse file path from args
    # ... (existing implementation from cmd_show)

    await app.show_file_in_panel(path, content, mode="code")

    return CommandResult(
        status=ResultStatus.SUCCESS,
        message=f"Opened {path.name} in side panel",
        data={"file": str(path), "mode": "code"}
    )


async def handle_edit(context: TextualCommandContext, args: str) -> CommandResult:
    """Edit file with CodeEditor."""
    # ... implementation

async def handle_theme(context: TextualCommandContext, args: str) -> CommandResult:
    """Cycle through Textual themes."""
    # ... implementation

async def handle_cd(context: TextualCommandContext, args: str) -> CommandResult:
    """Change working directory (TUI-specific state)."""
    # ... implementation


# Registration
CommandFactory.register(CommandSpec(
    name="show",
    description="Display file in side panel",
    handler=handle_show,
    category="display",
    clients=["textual"],
    is_async=True,
    usage="/show <filepath>[:line]"
))
```

### Rich-Specific Commands (clients=["rich"])

```python
# ppxai/commands/display.py

def handle_theme_rich(context: CommandContext, args: str) -> CommandResult:
    """Switch Rich console theme."""
    # ... implementation
    return CommandResult(
        status=ResultStatus.SUCCESS,
        message=f"Theme changed to: {theme_name}",
        data={"theme": theme_name}
    )

CommandFactory.register(CommandSpec(
    name="theme",
    description="Switch theme",
    handler=handle_theme_rich,
    category="display",
    clients=["rich"],
    usage="/theme [list|<name>]"
))
```

**Note:** Rich and Textual both register `/theme` command, but factory filters by client.

---

## Updated Architecture Diagram

```
┌──────────────────────────────────────────────────────────┐
│                   CommandFactory                         │
│                                                          │
│  Registry: CommandSpec with clients filter               │
│  Dispatch: Returns CommandResult (not void)             │
│  Methods: dispatch() sync, dispatch_async() async       │
└──────────────────────────────────────────────────────────┘
                           │
                           │
        ┌──────────────────┼──────────────────┐
        │                  │                  │
        ▼                  ▼                  ▼
┌──────────────┐  ┌──────────────┐  ┌──────────────────┐
│UI-Agnostic   │  │Rich-Specific │  │Textual-Specific  │
│Commands      │  │Commands      │  │Commands          │
│(sync)        │  │(sync)        │  │(async)           │
├──────────────┤  ├──────────────┤  ├──────────────────┤
│save          │  │theme (rich)  │  │show              │
│load          │  │emoji         │  │edit              │
│sessions      │  │              │  │theme (textual)   │
│provider      │  │              │  │cd                │
│model         │  │              │  │pwd               │
│tools         │  │              │  │copy              │
│agent         │  │              │  │paste             │
│... (28 cmds) │  │              │  │badge             │
└──────────────┘  └──────────────┘  └──────────────────┘
       │                 │                    │
       │                 │                    │
       ▼                 ▼                    ▼
┌──────────────────────────────────────────────────────┐
│           Return CommandResult                       │
│                                                      │
│  {                                                   │
│    status: SUCCESS/ERROR/WARNING/INFO                │
│    message: "Session saved: my-session"              │
│    data: {session_name: "...", filepath: "..."}      │
│  }                                                   │
└──────────────────────────────────────────────────────┘
       │                                      │
       │                                      │
       ▼                                      ▼
┌──────────────────┐              ┌──────────────────┐
│   Rich TUI       │              │  Textual TUI     │
│                  │              │                  │
│  Consumes result │              │  Consumes result │
│  Renders with    │              │  Renders with    │
│  Rich console    │              │  ChatView widget │
│                  │              │                  │
│  Context:        │              │  Context:        │
│  RichCommandContext              │  TextualCommandContext
└──────────────────┘              └──────────────────┘
```

---

## Migration Plan

### Phase 1: Infrastructure (1 day)

**Files created:**
- `ppxai/commands/result.py` - CommandResult, ResultStatus
- `ppxai/commands/protocol.py` - CommandContext protocol
- `ppxai/commands/context.py` - RichCommandContext, TextualCommandContext

**Tests:**
```python
def test_command_result():
    result = CommandResult(
        status=ResultStatus.SUCCESS,
        message="Test",
        data={"key": "value"}
    )
    assert result.success
    assert not result.failed
```

**Status:** ✅ No breaking changes, foundation only

---

### Phase 2: Refactor Session Commands (1 day)

**Commands:** save, load, sessions, clear, export (5 commands)

**Process:**
1. Refactor `ppxai/commands/session.py`:
   - Change handlers to accept `CommandContext`
   - Return `CommandResult` instead of printing
   - Remove `console.print()` calls
2. Update Rich TUI (`ppxai/commands/handler.py`):
   - Wrap `self` in `RichCommandContext`
   - Consume `CommandResult` and render with console
3. Update Textual TUI (when integrated):
   - Wrap `self` in `TextualCommandContext`
   - Consume `CommandResult` and render with ChatView

**Example diff:**
```diff
-def handle_save(handler: "CommandHandler", args: str) -> None:
+def handle_save(context: CommandContext, args: str) -> CommandResult:
     try:
-        session_name = handler.engine_client.session.save()
+        session_name = context.engine_client.session.save()
-        console.print(f"[green]Session saved: {session_name}[/green]")
+        return CommandResult(
+            status=ResultStatus.SUCCESS,
+            message=f"Session saved: {session_name}",
+            data={"session_name": session_name}
+        )
     except Exception as e:
-        console.print(f"[red]Error: {e}[/red]")
+        return CommandResult(
+            status=ResultStatus.ERROR,
+            message=f"Error saving session: {e}"
+        )
```

**Testing:**
```bash
uv run ppxai /save
uv run ppxai /sessions
# Should work exactly as before
```

---

### Phase 3: Refactor Provider Commands (1 day)

**Commands:** provider, model, tools (3 commands + subcommands)

**Same process as Phase 2.**

---

### Phase 4: Refactor Remaining Commands (2 days)

**Commands:**
- Coding (7): spec, code, fix, refactor, review, test, diff
- Context (5): context, browse, image, search, usage
- Agent (3): agent, delegate, ask
- System (4): help, quit, version, config
- Utility (3): checkpoint, status, display

**Total:** ~24 commands

---

### Phase 5: Update CommandFactory (1 day)

**Changes:**
1. Add `clients` field to `CommandSpec`
2. Add `is_async` field
3. Update `dispatch()` to return `CommandResult`
4. Add `dispatch_async()` method
5. Add `list_for_client()` filtering
6. Add `get_help_for_client()` generator

**Backward compatibility:** None needed - we're refactoring everything.

---

### Phase 6: Update Rich TUI (1 day)

**File:** `ppxai/commands/handler.py`

**Changes:**
```python
def handle_command(self, user_input: str) -> Optional[bool]:
    """Handle slash commands."""
    from .context import RichCommandContext
    from .result import ResultStatus

    command_parts = user_input.split(maxsplit=1)
    command = command_parts[0].lower()
    args = command_parts[1] if len(command_parts) > 1 else ""
    cmd_name = command[1:] if command.startswith("/") else command

    # Special case: quit returns bool
    if command in ["/quit", "/exit"]:
        return self.handle_quit()

    # Create context
    context = RichCommandContext(_handler=self)

    # Dispatch command
    result = CommandFactory.dispatch(cmd_name, context, args)

    # Render result
    if result.success:
        console.print(f"[green]{result.message}[/green]")
        # TODO: Format data based on command type
    elif result.failed:
        console.print(f"[red]{result.message}[/red]")
        if result.error_details:
            console.print(f"[dim]{result.error_details}[/dim]")
    else:  # WARNING or INFO
        console.print(result.message)

    return False
```

---

### Phase 7: Integrate Textual TUI (2 days)

**Files:**
- `ppxai/tui/commands_textual.py` (NEW) - Textual-specific commands
- `ppxai/tui/app.py` (MODIFY) - Use CommandFactory

**Textual command dispatch:**
```python
async def _handle_command(self, command: str) -> None:
    """Handle slash commands via CommandFactory."""
    from ppxai.commands.factory import CommandFactory
    from ppxai.commands.context import TextualCommandContext
    from ppxai.commands.result import ResultStatus

    chat_view = self.query_one("#chat-view", ChatView)
    parts = command[1:].split(maxsplit=1)
    cmd = parts[0].lower()
    args = parts[1] if len(parts) > 1 else ""

    # Create context
    context = TextualCommandContext(_app=self)

    # Dispatch async
    result = await CommandFactory.dispatch_async(cmd, context, args)

    # Render result
    if result.success:
        chat_view.add_system_message(f"[green]{result.message}[/green]")
    elif result.failed:
        chat_view.add_system_message(f"[red]{result.message}[/red]")
    else:
        chat_view.add_system_message(result.message)
```

**Textual-specific commands:**
```python
# ppxai/tui/commands_textual.py

from ppxai.commands.factory import CommandFactory, CommandSpec
from ppxai.commands.result import CommandResult, ResultStatus
from ppxai.commands.context import TextualCommandContext

async def handle_show(context: TextualCommandContext, args: str) -> CommandResult:
    """Display file in side panel."""
    # ... implementation from ppxai/tui/commands.py:cmd_show()

CommandFactory.register(CommandSpec(
    name="show",
    handler=handle_show,
    clients=["textual"],
    is_async=True,
    # ... other fields
))

# ... register edit, theme, cd, pwd, copy, paste, badge, status, debug
```

---

### Phase 8: Help Command & Auto-Generation (1 day)

**Generate help from factory:**
```python
class CommandFactory:
    @classmethod
    def get_help_for_client(cls, client: str) -> str:
        """Generate help text for client."""
        commands = cls.list_for_client(client)

        # Group by category
        by_category = {}
        for cmd in commands:
            by_category.setdefault(cmd.category, []).append(cmd)

        # Format help
        lines = ["[bold]Available Commands:[/bold]\n"]
        for category, cmds in sorted(by_category.items()):
            lines.append(f"[bold dim]{category.title()}:[/bold dim]")
            for cmd in sorted(cmds, key=lambda c: c.name):
                aliases = f" ({', '.join(cmd.aliases)})" if cmd.aliases else ""
                lines.append(f"  [cyan]/{cmd.name}[/cyan]{aliases} - {cmd.description}")
            lines.append("")

        return "\n".join(lines)
```

**Dual help pattern:**
```python
# Both /help <cmd> and /<cmd> help
if cmd == "help" and args:
    # /help <command>
    spec = CommandFactory.get(args.strip())
    # ... show detailed help
elif args.strip() == "help":
    # /<command> help
    spec = CommandFactory.get(cmd)
    # ... show detailed help
```

---

## File Changes Summary

| Phase | Files | Action | Lines |
|-------|-------|--------|-------|
| 1 | result.py, protocol.py, context.py | Create | +200 |
| 2-4 | session.py, provider.py, coding.py, etc. | Refactor | ~2500 modified |
| 5 | factory.py | Update | +100 |
| 6 | handler.py (Rich) | Update | +50 |
| 7 | commands_textual.py, app.py | Create/Update | +400, -200 |
| 8 | help generation | Update | +50 |
| **Total** | **~40 files** | **3 new, 37 modified** | **Net: +600 lines** |

**Code quality improvement:**
- Testable commands (no UI dependencies)
- Clear separation of concerns
- Easy to add new UI clients

---

## Testing Strategy

### Unit Tests (No UI Framework)

```python
# tests/test_commands_ui_agnostic.py

from ppxai.commands.session import handle_save
from ppxai.commands.result import ResultStatus

class MockContext:
    def __init__(self):
        self.engine_client = MockEngineClient()
        # ... minimal mock

def test_save_command():
    """Test save command returns correct result."""
    context = MockContext()
    result = handle_save(context, "")

    assert result.status == ResultStatus.SUCCESS
    assert "Session saved" in result.message
    assert "session_name" in result.data
```

### Integration Tests (Each TUI)

```python
# tests/test_rich_tui_commands.py
def test_rich_save_command():
    """Test save command in Rich TUI."""
    # Create Rich handler
    # Dispatch command
    # Verify console output

# tests/test_textual_tui_commands.py
async def test_textual_save_command():
    """Test save command in Textual TUI."""
    # Create Textual app
    # Dispatch command
    # Verify chat view output
```

---

## Migration Checklist

### Pre-Migration
- [ ] Review plan with team
- [ ] Run all existing tests: `uv run pytest tests/ -v`
- [ ] Create feature branch: `feature/command-refactoring-v1.15`

### Phase 1: Infrastructure
- [ ] Create result.py, protocol.py, context.py
- [ ] Write unit tests for CommandResult
- [ ] Verify imports work
- [ ] Commit: "feat: add command result infrastructure"

### Phase 2: Session Commands
- [ ] Refactor session.py (5 commands)
- [ ] Update Rich TUI to consume results
- [ ] Test: `/save`, `/load`, `/sessions`, `/clear`, `/export`
- [ ] Commit: "refactor: session commands return CommandResult"

### Phase 3: Provider Commands
- [ ] Refactor provider.py (3 commands)
- [ ] Test: `/provider`, `/model`, `/tools`
- [ ] Commit: "refactor: provider commands return CommandResult"

### Phase 4: Remaining Commands
- [ ] Refactor coding.py (7 commands)
- [ ] Refactor utility.py (5 commands)
- [ ] Refactor agent.py (3 commands)
- [ ] Refactor system.py (4 commands)
- [ ] Refactor display.py (1 command)
- [ ] Test each category
- [ ] Commit per category

### Phase 5: Update CommandFactory
- [ ] Add clients field
- [ ] Add is_async field
- [ ] Implement dispatch() returning CommandResult
- [ ] Implement dispatch_async()
- [ ] Add list_for_client()
- [ ] Test factory filtering
- [ ] Commit: "feat: enhance CommandFactory with client filtering"

### Phase 6: Update Rich TUI
- [ ] Update handler.py dispatch logic
- [ ] Test all Rich commands work
- [ ] Verify help text
- [ ] Commit: "refactor: Rich TUI consumes CommandResult"

### Phase 7: Integrate Textual TUI
- [ ] Create commands_textual.py
- [ ] Register Textual-specific commands
- [ ] Update app.py dispatch
- [ ] Test all Textual commands
- [ ] Commit: "feat: integrate Textual TUI with CommandFactory"

### Phase 8: Help & Polish
- [ ] Implement get_help_for_client()
- [ ] Add dual help pattern
- [ ] Test help in both TUIs
- [ ] Update documentation
- [ ] Commit: "feat: auto-generate help from factory"

### Post-Migration
- [ ] Run full test suite
- [ ] Manual testing: both TUIs, all commands
- [ ] Update architecture.md
- [ ] Update CHANGELOG.md
- [ ] Create PR

---

## Risk Assessment

### Low Risk ✅
- Creating new infrastructure (result.py, protocol.py)
- Unit tests without UI
- Client filtering in factory

### Medium Risk ⚠️
- Refactoring 32 existing commands (systematic but large)
- Async/sync boundary in dispatch_async()
- Context protocol compatibility

**Mitigation:**
- Refactor one category at a time with tests
- Keep Rich TUI working at each step
- Comprehensive unit + integration tests

### High Risk 🚨
- Breaking Rich TUI during migration
- Missing edge cases in command refactoring

**Mitigation:**
- Test after each phase
- Feature branch with full CI/CD
- Rollback plan: revert commit range

---

## Success Criteria

1. ✅ All 32 commands return `CommandResult` instead of printing
2. ✅ Rich TUI consumes results and renders correctly
3. ✅ Textual TUI uses same commands via factory
4. ✅ Textual-specific commands (show, edit) registered with `clients=["textual"]`
5. ✅ Help text auto-generated from factory
6. ✅ Dual help pattern: `/help <cmd>` and `/<cmd> help`
7. ✅ All tests passing (existing + new unit tests)
8. ✅ Commands testable without UI framework

---

## Follow-Up (v1.16.0+)

**Enabled by this architecture:**

1. **HTTP command endpoint** - Server can dispatch commands and return JSON
2. **Web-based TUI** - Browser client consumes CommandResult as JSON
3. **SSH server** - Remote TUI over SSH uses same commands
4. **Command logging** - Audit trail of all command executions
5. **Command undo/redo** - Commands can be replayed or reversed

---

## Known Issues / Future Improvements

### 1. Word Wrap for Narrow Terminal Views
**Status:** TODO
**Priority:** Medium
**Context:** When running TUI in narrow terminal windows (e.g., VSCode sidebar terminal), table columns and long text get truncated instead of wrapping.

**Affected areas:**
- Tool list table in side panel (descriptions cut off)
- Help text tables
- Status bar badges
- Any DataTable-based rendering

**Potential solutions:**
- Detect terminal width and adjust column widths dynamically
- Enable word wrap in DataTable cells for narrow views
- Consider responsive breakpoints (full view vs compact view)
- Truncate with ellipsis + tooltip on hover (if supported)

### 2. N:1 Renderer Dispatch for File Types
**Status:** Design decision needed
**Priority:** High
**Context:** `/show` and `/edit` commands need different widgets based on file type (markdown→Markdown widget, json→TreeViewer, csv→TableViewer, code→CodeEditor), but the current architecture uses 1:1 type-based dispatch (`FileViewResult` → single renderer).

**Options under consideration:**
1. **Multiple typed results** - `MarkdownViewResult`, `TreeViewResult`, `TableViewResult`, `CodeViewResult`
2. **Render hint field** - Add `render_mode: str` to `FileViewResult`
3. **Keep as TUI-specific** - Don't route `/show`/`/edit` through command factory for TUI
4. **Composite results** - `FileViewResult` wraps content-specific inner types

**Current workaround:** TUI-specific handlers in `tui/commands.py` bypass command factory for proper widget selection.

---

## Questions for Approval

1. **CommandResult structure:** Is the proposed structure sufficient, or do you need additional fields?

2. **Async strategy:** Use `dispatch_async()` with executor for sync commands, or make ALL commands async?

3. **Context protocol:** Should we add more methods to CommandContext, or keep minimal?

4. **Testing priority:** Unit tests first, or integration tests first?

5. **Migration speed:** One category per day (slow, safe) or multiple categories per day (fast, risky)?

---

## Recommendation

**Proceed with phased migration:**
- Week 1: Phases 1-3 (infrastructure + session + provider)
- Week 2: Phases 4-5 (remaining commands + factory)
- Week 3: Phases 6-7 (integrate both TUIs)
- Week 4: Phase 8 + testing + documentation

**Estimated effort:** 4 weeks for clean, well-tested refactoring.

**Alternative:** 2-week aggressive timeline if we skip some unit tests (not recommended).

**Your decision?**
