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


@dataclass
class CommandResult(ABC):
    """Base result type - all results inherit from this.

    Commands return specific result types (NotificationResult, TableResult, etc.).
    Renderer dispatch is type-based - no conditional logic needed.

    Attributes:
        status: Execution status (SUCCESS, ERROR, WARNING, INFO)
        message: Human-readable message describing the result
        metadata: Optional metadata for extended information
    """
    status: ResultStatus
    message: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def success(self) -> bool:
        """Check if result indicates success."""
        return self.status == ResultStatus.SUCCESS

    @property
    def failed(self) -> bool:
        """Check if result indicates failure."""
        return self.status == ResultStatus.ERROR


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
