"""
Command Result Types - Type-Based Rendering Protocol

This module defines the result type hierarchy for UI-agnostic commands.
Commands return typed result objects; renderers dispatch mechanically by type.

Architecture:
- Commands return CommandResult subclasses (TextResult, TableResult, etc.)
- Each TUI framework registers renderers for each result type
- Dispatch is mechanical: renderer.render(result) → type lookup → call handler
- Zero conditional logic in rendering

v1.15.0: Type-based renderer dispatch refactoring
"""

from dataclasses import dataclass, field
from typing import Any, Optional, Dict, List
from enum import Enum
from abc import ABC


class ResultStatus(Enum):
    """Command execution status.

    Used to color/style result rendering:
    - SUCCESS: Green, positive confirmation
    - ERROR: Red, with error details
    - WARNING: Yellow, cautionary message
    - INFO: Default, informational
    """
    SUCCESS = "success"
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


# ============================================================================
# Side-effect envelope (v1.18.1) — UI directives separate from rendered payload
# ============================================================================


class SideEffectKind:
    """Canonical names for SideEffect kinds (v1.18.1).

    Use these constants instead of bare strings when emitting:

        result.add_side_effect(SideEffectKind.OPEN_EDITOR,
                               filepath=str(path), line=42)

    Bare strings still work — kinds are an open enum on the wire —
    but the constants give you a typo-proof handle and let mypy /
    IDE rename refactors catch references. Adding a new kind: add
    the constant here AND document it in the SideEffect docstring
    below; the test_command_envelope.py sentinel asserts the two
    stay in sync.

    Removed in v1.18.1 (do not use):
      - SPAWN_TERMINAL  → use OPEN_TERMINAL
      - OPEN_PREVIEW    → use OPEN_HTML_PREVIEW
    """
    # File handling
    OPEN_EDITOR = "open_editor"        # editable; client picks editor
    OPEN_VIEWER = "open_viewer"        # read-only; client picks viewer
    SHOW_IMAGE = "show_image"          # client decodes / delegates
    SHOW_PDF = "show_pdf"              # client decodes / delegates
    REVEAL_IN_EXPLORER = "reveal_in_explorer"

    # Terminals + shells
    OPEN_TERMINAL = "open_terminal"    # cwd only
    RUN_SHELL = "run_shell"            # cwd + command pre-typed

    # Live previews
    OPEN_HTML_PREVIEW = "open_html_preview"

    # File tree / workspace
    REFRESH_FILE_TREE = "refresh_file_tree"

    # User preferences
    SET_THEME = "set_theme"

    # Clipboard
    COPY_TO_CLIPBOARD = "copy_to_clipboard"

    # Session / engine state
    ATTACH_FILE = "attach_file"

    # Interactive prompts (engine asks the user a follow-up)
    PROMPT_QUICK_PICK = "prompt_quick_pick"

    # User-facing messages
    NOTIFY = "notify"

    # VSCode-only escape hatch (web ignores)
    VSCODE_DELEGATE = "vscode_delegate"

    @classmethod
    def all_kinds(cls) -> tuple[str, ...]:
        """Return every public kind constant (uppercase fields).

        Used by the v1.18.1 sentinel test to verify the docstring
        on `SideEffect` lists exactly the same names — no typos,
        no drift.
        """
        return tuple(
            sorted(
                getattr(cls, name)
                for name in vars(cls)
                if name.isupper() and isinstance(getattr(cls, name), str)
            )
        )


@dataclass
class SideEffect:
    """A UI directive emitted alongside a CommandResult.

    Side-effects are orthogonal to the rendered payload: a command
    can return a TableResult AND tell the client "also open a
    terminal at this cwd". Clients pattern-match on `kind` and
    ignore unknown kinds — adding a new kind is non-breaking.

    The contract is "name the user's intent, let the client choose
    the rendering". Web builds panels (xterm.js, CodeMirror,
    embedded iframe); VSCode delegates to native APIs
    (createTerminal, showTextDocument, executeCommand('vscode.open'))
    so users get their shell, IntelliSense, debugging integration,
    installed image/PDF extensions, etc.

    Known kinds (v1.18.1):
      - "open_editor"        payload: {filepath, line?, column?}
            User wants to edit this file. Web → CodeMirror panel.
            VSCode → showTextDocument(preview=False) in primary col.

      - "open_viewer"        payload: {filepath, line?, column?}
            User wants to view this file read-only. Web → preview
            panel. VSCode → executeCommand('vscode.open',
            preview=True, viewColumn=Beside).

      - "open_terminal"      payload: {cwd}
            User wants a terminal at this cwd. Web → xterm.js panel.
            VSCode → window.createTerminal({cwd}).show() — user's
            chosen shell, profile, history.

      - "run_shell"          payload: {command, cwd}
            User wants a terminal AND a command pre-typed/executed.
            Strict superset of open_terminal. Web → xterm.js with
            command. VSCode → createTerminal + sendText(command).

      - "open_html_preview"  payload: {filepath, url, served?, proxied?}
            User wants live HTML preview with reload. Web → iframe
            in side panel. VSCode → existing previewPanel.ts
            WebviewPanel.

      - "show_image"         payload: {filepath}
            User wants to view an image. Web → inline <img> viewer.
            VSCode → executeCommand('vscode.open', uri) (delegates
            to user's installed image-viewer extension).

      - "show_pdf"           payload: {filepath}
            User wants to view a PDF. Web → embedded PDF.js viewer.
            VSCode → executeCommand('vscode.open', uri) (delegates
            to user's PDF extension).

      - "reveal_in_explorer" payload: {filepath}
            User wants the file highlighted in the file tree. Web →
            scroll/expand FileTreeComponent. VSCode →
            executeCommand('revealInExplorer', uri).

      - "refresh_file_tree"  payload: {cwd}
            The working tree changed; clients refresh their views.
            Web → FileTreeComponent.refresh(). VSCode → usually no-op
            (auto-watches), or workbench.files.action.refreshFilesExplorer.

      - "set_theme"          payload: {name}
            User picked a theme. Web → swap CSS class on body.
            VSCode → no-op (the user's VSCode theme is independent
            of the webview's theme).

      - "copy_to_clipboard"  payload: {text}
            User wants text on the system clipboard. Web →
            navigator.clipboard.writeText(). VSCode →
            vscode.env.clipboard.writeText(). The capability is
            client-dependent — kind makes that explicit.

      - "attach_file"        payload: {filepath} | {file_id}
            User asked to attach a file to the current session.
            Web → existing drag-drop handler / SessionFileStore
            upload. VSCode → similar via the extension's own attach
            path. TUI → uses the path directly.

      - "prompt_quick_pick"  payload: {title, items: [{label, value}],
                                       request_id, command_to_resume,
                                       resolved_arg_template}
            Engine needs the user to pick one of N options before
            the command can complete. Web → clickable list in chat.
            VSCode → window.showQuickPick(items). Choice resumes by
            issuing a fresh POST /command/<command_to_resume> with
            args = resolved_arg_template.format(value=<choice>).
            See ADR 0001 for the resume protocol decision.

      - "notify"             payload: {level: "info"|"warn"|"error",
                                       message}
            User-visible message that doesn't fit the result payload.
            Web → toast in chat. VSCode → showInformationMessage /
            showWarningMessage / showErrorMessage by level.

      - "vscode_delegate"    payload: {command, args}
            Escape hatch: invoke an arbitrary VSCode command via
            executeCommand(command, *args). Web ignores. Use
            sparingly — most things should have a stable kind so
            web has parity.

    Removed in v1.18.1 (renamed for consistency):
      - "spawn_terminal"  → "open_terminal"
      - "open_preview"    → "open_html_preview"
      - "open_editor" with read_only flag → split into
        "open_editor" (editable) + "open_viewer" (read-only)
    """
    kind: str
    payload: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"kind": self.kind, **self.payload}


@dataclass
class CommandResult(ABC):
    """Base result type - all results inherit from this.

    Commands return specific result types (NotificationResult, TableResult, etc.).
    Renderer dispatch is type-based - no conditional logic needed.

    Attributes:
        status: Execution status (SUCCESS, ERROR, WARNING, INFO)
        message: Human-readable message describing the result
        metadata: Optional metadata for extended information
        side_effects: UI directives orthogonal to the rendered payload.
            Populated by handlers that need to open panels, spawn
            terminals, refresh widgets, etc. The HTTP route layer
            promotes this field into the v1 envelope's `side_effects`
            array; in-process callers (Rich/Textual) read it directly.
    """
    status: ResultStatus
    message: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    side_effects: List[SideEffect] = field(default_factory=list)

    @property
    def success(self) -> bool:
        """Check if result indicates success."""
        return self.status == ResultStatus.SUCCESS

    @property
    def failed(self) -> bool:
        """Check if result indicates failure."""
        return self.status == ResultStatus.ERROR

    def add_side_effect(self, kind: str, **payload: Any) -> None:
        """Append a UI directive to this result. Handler convenience helper."""
        self.side_effects.append(SideEffect(kind=kind, payload=payload))

    def to_dict(self) -> dict:
        """Serialize result for HTTP/JSON transport.

        Used by POST /command/{name} endpoint to return CommandResult as JSON.
        Subclasses override to add their specific fields.

        Note: `side_effects` is NOT included here — the route layer
        promotes them into the envelope so the wire shape stays clean.
        In-process TUI callers read `result.side_effects` directly.
        """
        return {
            "type": type(self).__name__,
            "status": self.status.value,
            "message": self.message,
            "metadata": self.metadata,
        }


# ============================================================================
# Display Result Types - User Communication
# ============================================================================

@dataclass
class NotificationResult(CommandResult):
    """Success/info notification result (toast-style).

    Used for: Quick success confirmations, info messages
    Replaces: 25% of generic TextResult usage

    Rendering:
    - Rich: Brief console message (green/yellow/default)
    - Textual: Chat message or brief toast notification

    Example:
        NotificationResult(
            status=ResultStatus.SUCCESS,
            message="Provider switched to openai"
        )
    """
    auto_dismiss: bool = True  # For future toast implementation


@dataclass
class ErrorResult(CommandResult):
    """Structured error result with suggestions.

    Used for: Command failures, validation errors, exceptions
    Replaces: 10% of generic TextResult usage

    Rendering:
    - Rich: Red error message + dim details/suggestions
    - Textual: Red chat message with expandable details

    Example:
        ErrorResult(
            status=ResultStatus.ERROR,
            message="File not found: config.json",
            error_details="FileNotFoundError: [Errno 2] No such file",
            suggestions=["Run /pwd to check current directory",
                        "Use /cd to navigate to correct location"]
        )
    """
    error_details: Optional[str] = None
    suggestions: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = super().to_dict()
        d["error_details"] = self.error_details
        d["suggestions"] = self.suggestions
        return d


@dataclass
class ConfirmationResult(CommandResult):
    """Action completed confirmation.

    Used for: Operation confirmations with brief details
    Replaces: 8% of generic TextResult usage

    Rendering:
    - Rich: Brief confirmation message
    - Textual: Brief chat message

    Example:
        ConfirmationResult(
            status=ResultStatus.SUCCESS,
            message="History cleared (42 messages)",
            details={"messages_cleared": 42, "session": "my-session"}
        )
    """
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = super().to_dict()
        d["details"] = self.details
        return d


@dataclass
class AIResponseResult(CommandResult):
    """AI-generated content result with code blocks.

    Used for: /generate, /test, /docs, /explain, /debug output
    Replaces: 6% of generic TextResult usage

    Rendering:
    - Rich: Markdown rendering with code blocks
    - Textual: Markdown in chat view

    Example:
        AIResponseResult(
            status=ResultStatus.SUCCESS,
            message="Generated test cases",
            content="Here are the test cases:\n\n```python\n...\n```",
            code_blocks=[{"language": "python", "code": "def test_foo(): ..."}]
        )
    """
    content: str = ""  # Full markdown content
    code_blocks: List[Dict[str, str]] = field(default_factory=list)


# ============================================================================
# Structured Data Result Types
# ============================================================================

@dataclass
class TableResult(CommandResult):
    """Tabular data result.

    Used for: session lists, tool lists, usage stats, model lists, checkpoints

    Rendering:
    - Rich: Rich Table widget
    - Textual: DataTable in side panel

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

    def to_dict(self) -> dict:
        d = super().to_dict()
        d["columns"] = self.columns
        d["rows"] = self.rows
        return d


@dataclass
class TreeResult(CommandResult):
    """Hierarchical tree structure result.

    Used for: context sources, file trees, nested config, help categories

    Rendering:
    - Rich: Rich Tree widget
    - Textual: Tree in side panel

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
class DirectoryListingResult(TableResult):
    """Directory listing result — subscribable via event bus.

    Subtype of TableResult for typed dispatch. Renderers that handle
    TableResult automatically handle this. Event bus can map this type
    to UI_DIRECTORY_LISTED for widget subscribers (e.g. file tree sidebar).

    v1.16.0: File navigation commands
    """
    pass


@dataclass
class DirectoryTreeResult(TreeResult):
    """Directory tree result — subscribable via event bus.

    Subtype of TreeResult for typed dispatch. Renderers that handle
    TreeResult automatically handle this. Event bus can map this type
    to UI_TREE_LOADED for widget subscribers (e.g. file tree sidebar).

    v1.16.0: File navigation commands
    """
    pass


@dataclass
class ListResult(CommandResult):
    """List of items with optional styling.

    Used for: provider lists, model lists, spec templates

    Rendering:
    - Rich: Bulleted list with icons
    - Textual: Formatted list in chat

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
class KeyValueResult(CommandResult):
    """Key-value pairs result.

    Used for: config display, version info, status information

    Rendering:
    - Rich: Formatted key-value pairs
    - Textual: Formatted key-value in chat

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

    def to_dict(self) -> dict:
        d = super().to_dict()
        d["pairs"] = self.pairs
        return d


# ============================================================================
# File & Media Result Types
# ============================================================================

@dataclass
class FileViewResult(CommandResult):
    """File content with syntax highlighting.

    Used for: code display (/show), log viewing, config inspection

    Rendering:
    - Rich: Syntax highlighted code with line numbers
    - Textual: CodeEditor in side panel

    Example:
        FileViewResult(
            status=ResultStatus.SUCCESS,
            message="Opened config.json",
            filepath="/path/to/config.json",
            content='{"key": "value"}',
            language="json",
            line_highlight=5,
            read_only=True
        )
    """
    filepath: str = ""
    content: str = ""
    language: Optional[str] = None
    line_highlight: Optional[int] = None
    col_highlight: Optional[int] = None
    read_only: bool = True


@dataclass
class MarkdownResult(CommandResult):
    """Markdown content for rich rendering.

    Used for: README files, documentation, release notes, AGENTS.md

    Rendering:
    - Rich: Rich Markdown widget
    - Textual: Markdown widget in side panel with proper formatting

    Example:
        MarkdownResult(
            status=ResultStatus.SUCCESS,
            message="Displaying README.md",
            filepath="/path/to/README.md",
            content="# Title\\n\\nSome **bold** text..."
        )
    """
    filepath: str = ""
    content: str = ""


@dataclass
class ImageResult(CommandResult):
    """Image display result for plots, charts, generated images.

    Used for: matplotlib plots, pandas visualizations, generated images from tools

    Rendering:
    - Rich: Image path + thumbnail (if terminal supports)
    - Textual: ImageViewer in side panel with zoom/pan

    Example:
        ImageResult(
            status=ResultStatus.SUCCESS,
            message="Sales Chart Generated",
            filepath="output/sales_2024.png",
            image_data=None,  # Optional: base64 for inline
            format="png",
            metadata={"width": 1920, "height": 1080, "dpi": 300}
        )
    """
    filepath: str = ""
    image_data: Optional[str] = None  # Base64 encoded image data (optional)
    format: str = "png"  # png, jpg, svg, etc.


@dataclass
class PreviewResult(CommandResult):
    """Live HTML preview result.

    Used for: /preview command - live-reloading HTML in browser/iframe

    Rendering:
    - Rich: Start PreviewServer, open browser, show URL
    - Textual: Start PreviewServer, open browser, show notification
    - Web App: iframe in split panel (via server /preview/ endpoint)
    - VSCode: WebviewPanel with FileSystemWatcher

    Example:
        PreviewResult(
            status=ResultStatus.SUCCESS,
            message="Preview: index.html",
            filepath="/path/to/index.html",
            url="http://localhost:54321/"
        )
    """
    filepath: str = ""
    url: str = ""


# ============================================================================
# Operations Result Types
# ============================================================================

@dataclass
class ProgressResult(CommandResult):
    """Progress indicator for long operations.

    Used for: agent task progress, file downloads, batch operations

    Rendering:
    - Rich: Progress bar or percentage
    - Textual: Status bar + chat message

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
class DiffResult(CommandResult):
    """Structured diff data for before/after comparisons.

    Used for: /undo, /checkpoint diff, agent rollbacks

    Rendering:
    - Rich: Unified diff format with colors
    - Textual: Diff viewer in side panel (or inline)

    Example:
        DiffResult(
            status=ResultStatus.SUCCESS,
            message="Checkpoint diff",
            files=[
                {
                    "path": "config.json",
                    "old_content": "...",
                    "new_content": "...",
                    "hunks": [...]
                }
            ],
            summary="3 files changed, 42 insertions(+), 15 deletions(-)"
        )
    """
    files: List[Dict[str, Any]] = field(default_factory=list)
    summary: str = ""


# ============================================================================
# Interactive Result Types (Future: User Input)
# ============================================================================

@dataclass
class ConsentResult(CommandResult):
    """Request user consent/confirmation before action.

    Used for: destructive operations, file edits, agent tasks, tool execution

    Rendering:
    - Rich: Prompt in console (input)
    - Textual: Modal dialog with buttons

    Example:
        ConsentResult(
            status=ResultStatus.INFO,
            message="Execute 'rm -rf /' command?",
            question="This will delete all files. Continue?",
            options=["Allow", "Deny", "Always Allow"],
            default="Deny",
            context={"command": "rm -rf /", "risk": "high"}
        )
    """
    question: str = ""
    options: List[str] = field(default_factory=lambda: ["Allow", "Deny"])
    default: str = "Deny"
    context: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PromptResult(CommandResult):
    """Request text input from user.

    Used for: missing arguments, interactive configuration

    Rendering:
    - Rich: Input prompt in console
    - Textual: Input modal dialog

    Example:
        PromptResult(
            status=ResultStatus.INFO,
            message="Session name required",
            prompt="Enter session name:",
            placeholder="my-session",
            default="",
            validation=r"^[a-z0-9-]+$"
        )
    """
    prompt: str = ""
    placeholder: str = ""
    default: str = ""
    validation: Optional[str] = None  # Regex pattern


# ============================================================================
# Composite Result Types - Multiple Outputs
# ============================================================================

@dataclass
class CompositeResult(CommandResult):
    """Container for multiple result types from single operation.

    Used for: tool executions that produce multiple outputs (image + table + text)

    Rendering:
    - Rich: Iterate and render each sub-result sequentially
    - Textual: ArtifactPanel with tabs for each sub-result

    Example:
        CompositeResult(
            status=ResultStatus.SUCCESS,
            message="Analysis complete",
            results=[
                ImageResult(...),  # Plot
                TableResult(...),  # Summary stats
                NotificationResult(...)  # Completion message
            ]
        )
    """
    results: List[CommandResult] = field(default_factory=list)


@dataclass
class ToolExecutionResult(CommandResult):
    """Specialized result for tool execution with artifacts.

    Used for: agent tool execution, script running

    Rendering:
    - Rich: Execution summary + artifacts sequentially
    - Textual: Execution summary in chat + ArtifactPanel for artifacts

    Example:
        ToolExecutionResult(
            status=ResultStatus.SUCCESS,
            message="Script executed successfully",
            tool_name="python",
            duration=2.5,
            stdout="Processing data...\nGenerating chart...",
            stderr="",
            exit_code=0,
            artifacts=[
                ImageResult(...),
                TableResult(...)
            ]
        )
    """
    tool_name: str = ""
    duration: float = 0.0
    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0
    artifacts: List[CommandResult] = field(default_factory=list)


# ============================================================================
# Fallback Result Type
# ============================================================================

@dataclass
class TextResult(CommandResult):
    """Generic text message result (fallback).

    Used for: Edge cases not covered by specific types (<1% usage)

    Rendering:
    - Rich: Basic console.print with status coloring
    - Textual: Basic chat message

    Example:
        TextResult(
            status=ResultStatus.SUCCESS,
            message="Operation completed",
            error_details="Optional error trace"
        )
    """
    error_details: Optional[str] = None


# Export all result types for easy importing
__all__ = [
    # Enums
    "ResultStatus",
    # Base
    "CommandResult",
    "SideEffect",
    "SideEffectKind",
    # Display
    "NotificationResult",
    "ErrorResult",
    "ConfirmationResult",
    "AIResponseResult",
    # Structured Data
    "TableResult",
    "TreeResult",
    "ListResult",
    "KeyValueResult",
    # File & Media
    "FileViewResult",
    "MarkdownResult",
    "ImageResult",
    "PreviewResult",
    # Operations
    "ProgressResult",
    "DiffResult",
    # Interactive
    "ConsentResult",
    "PromptResult",
    # Composite
    "CompositeResult",
    "ToolExecutionResult",
    # Fallback
    "TextResult",
]
