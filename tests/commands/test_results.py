"""
Test suite for command result types.

Tests all 17 result types defined in ppxai/commands/results.py:
- Instantiation with default values
- Status properties (success, failed)
- Structure validation
- Composite result nesting
- ToolExecutionResult with artifacts

v1.15.0: Type-based renderer dispatch refactoring
"""

import pytest

from ppxai.commands.results import (
    AIResponseResult,
    CompositeResult,
    ConfirmationResult,
    ConsentResult,
    DiffResult,
    ErrorResult,
    FileViewResult,
    ImageResult,
    KeyValueResult,
    ListResult,
    NotificationResult,
    ProgressResult,
    PromptResult,
    ResultStatus,
    TableResult,
    TextResult,
    ToolExecutionResult,
    TreeResult,
)

# ============================================================================
# Display Result Tests
# ============================================================================

class TestNotificationResult:
    """Test NotificationResult (success/info notifications)."""

    def test_success_notification(self):
        """Test success notification."""
        result = NotificationResult(
            status=ResultStatus.SUCCESS,
            message="Operation completed"
        )
        assert result.status == ResultStatus.SUCCESS
        assert result.message == "Operation completed"
        assert result.success is True
        assert result.failed is False

    def test_warning_notification(self):
        """Test warning notification."""
        result = NotificationResult(
            status=ResultStatus.WARNING,
            message="Potential issue detected"
        )
        assert result.status == ResultStatus.WARNING
        assert result.success is False
        assert result.failed is False

    def test_info_notification(self):
        """Test info notification."""
        result = NotificationResult(
            status=ResultStatus.INFO,
            message="Information message"
        )
        assert result.status == ResultStatus.INFO
        assert result.success is False
        assert result.failed is False


class TestErrorResult:
    """Test ErrorResult (structured errors)."""

    def test_basic_error(self):
        """Test basic error without details."""
        result = ErrorResult(
            status=ResultStatus.ERROR,
            message="Something went wrong"
        )
        assert result.status == ResultStatus.ERROR
        assert result.message == "Something went wrong"
        assert result.failed is True
        assert result.success is False
        assert result.error_details is None
        assert result.suggestions == []

    def test_error_with_details(self):
        """Test error with details and suggestions."""
        result = ErrorResult(
            status=ResultStatus.ERROR,
            message="File not found",
            error_details="Path: /nonexistent/file.txt",
            suggestions=[
                "Check the file path",
                "Verify file permissions"
            ]
        )
        assert result.error_details == "Path: /nonexistent/file.txt"
        assert len(result.suggestions) == 2
        assert "Check the file path" in result.suggestions


class TestConfirmationResult:
    """Test ConfirmationResult (action confirmations)."""

    def test_basic_confirmation(self):
        """Test basic confirmation."""
        result = ConfirmationResult(
            status=ResultStatus.SUCCESS,
            message="Session saved successfully"
        )
        assert result.status == ResultStatus.SUCCESS
        assert result.message == "Session saved successfully"
        assert result.details == {}

    def test_confirmation_with_details(self):
        """Test confirmation with details."""
        result = ConfirmationResult(
            status=ResultStatus.SUCCESS,
            message="Model switched",
            details={
                "from": "gpt-4",
                "to": "claude-3.5-sonnet",
                "timestamp": "2024-01-01T00:00:00Z"
            }
        )
        assert result.details["from"] == "gpt-4"
        assert result.details["to"] == "claude-3.5-sonnet"


class TestAIResponseResult:
    """Test AIResponseResult (AI-generated content)."""

    def test_ai_response_with_content(self):
        """Test AI response with markdown content."""
        result = AIResponseResult(
            status=ResultStatus.SUCCESS,
            message="Analysis complete",
            content="# Code Review\n\n- Good structure\n- Needs tests"
        )
        assert result.status == ResultStatus.SUCCESS
        assert result.message == "Analysis complete"
        assert "# Code Review" in result.content

    def test_ai_response_without_message(self):
        """Test AI response with content only."""
        result = AIResponseResult(
            status=ResultStatus.SUCCESS,
            message="",
            content="Here is the answer to your question."
        )
        assert result.content == "Here is the answer to your question."
        assert result.message == ""


# ============================================================================
# Structured Data Result Tests
# ============================================================================

class TestTableResult:
    """Test TableResult (tabular data)."""

    def test_basic_table(self):
        """Test table with columns and rows."""
        result = TableResult(
            status=ResultStatus.INFO,
            message="Session List",
            columns=["ID", "Name", "Created"],
            rows=[
                ["1", "main", "2024-01-01"],
                ["2", "test", "2024-01-02"]
            ]
        )
        assert len(result.columns) == 3
        assert len(result.rows) == 2
        assert result.rows[0][1] == "main"

    def test_empty_table(self):
        """Test empty table."""
        result = TableResult(
            status=ResultStatus.INFO,
            message="No data",
            columns=[],
            rows=[]
        )
        assert result.columns == []
        assert result.rows == []


class TestTreeResult:
    """Test TreeResult (hierarchical structures)."""

    def test_tree_structure(self):
        """Test tree with nested children."""
        result = TreeResult(
            status=ResultStatus.INFO,
            message="File Tree",
            root={
                "label": "project",
                "children": [
                    {"label": "src", "children": [
                        {"label": "main.py"},
                        {"label": "utils.py"}
                    ]},
                    {"label": "tests", "children": []}
                ]
            }
        )
        assert result.root["label"] == "project"
        assert len(result.root["children"]) == 2
        assert result.root["children"][0]["label"] == "src"


class TestListResult:
    """Test ListResult (lists with icons/badges)."""

    def test_list_with_items(self):
        """Test list with icons and badges."""
        result = ListResult(
            status=ResultStatus.INFO,
            message="Available Models",
            items=[
                {"icon": "🤖", "text": "GPT-4", "badge": "default"},
                {"icon": "🤖", "text": "Claude", "badge": ""},
                {"text": "Gemini"}  # Missing icon should work
            ]
        )
        assert len(result.items) == 3
        assert result.items[0]["icon"] == "🤖"
        assert result.items[0]["badge"] == "default"

    def test_empty_list(self):
        """Test empty list."""
        result = ListResult(
            status=ResultStatus.INFO,
            message="No items",
            items=[]
        )
        assert result.items == []


class TestKeyValueResult:
    """Test KeyValueResult (key-value pairs)."""

    def test_key_value_pairs(self):
        """Test key-value pairs."""
        result = KeyValueResult(
            status=ResultStatus.INFO,
            message="Configuration",
            pairs={
                "provider": "perplexity",
                "model": "llama-3.1-sonar-huge-128k-online",
                "tools_enabled": "true"
            }
        )
        assert result.pairs["provider"] == "perplexity"
        assert result.pairs["tools_enabled"] == "true"
        assert len(result.pairs) == 3


# ============================================================================
# File & Media Result Tests
# ============================================================================

class TestFileViewResult:
    """Test FileViewResult (code files with syntax highlighting)."""

    def test_file_view_with_content(self):
        """Test file view with content."""
        result = FileViewResult(
            status=ResultStatus.INFO,
            message="main.py",
            filepath="/path/to/main.py",
            content="def hello():\n    print('Hello')",
            language="python"
        )
        assert result.filepath == "/path/to/main.py"
        assert "def hello()" in result.content
        assert result.language == "python"
        assert result.read_only is True

    def test_file_view_with_line_highlight(self):
        """Test file view with line highlighting."""
        result = FileViewResult(
            status=ResultStatus.INFO,
            message="file.py",
            filepath="/path/to/file.py",
            content="line1\nline2\nline3",
            line_highlight=2
        )
        assert result.line_highlight == 2


class TestImageResult:
    """Test ImageResult (plots/charts/images)."""

    def test_image_result(self):
        """Test image result with metadata."""
        result = ImageResult(
            status=ResultStatus.INFO,
            message="Matplotlib plot",
            filepath="/path/to/plot.png",
            format="png",
            metadata={"width": 800, "height": 600, "dpi": 100}
        )
        assert result.filepath == "/path/to/plot.png"
        assert result.format == "png"
        assert result.metadata["width"] == 800
        assert result.metadata["height"] == 600

    def test_image_without_metadata(self):
        """Test image without metadata."""
        result = ImageResult(
            status=ResultStatus.INFO,
            message="image.jpg",
            filepath="/path/to/image.jpg",
            format="jpg"
        )
        assert result.metadata == {}


# ============================================================================
# Operations Result Tests
# ============================================================================

class TestProgressResult:
    """Test ProgressResult (long-running operations)."""

    def test_progress_with_percentage(self):
        """Test progress with total."""
        result = ProgressResult(
            status=ResultStatus.INFO,
            message="Processing files",
            current=50,
            total=100,
            description="50% complete"
        )
        assert result.current == 50
        assert result.total == 100
        assert result.description == "50% complete"

    def test_progress_without_total(self):
        """Test progress without total."""
        result = ProgressResult(
            status=ResultStatus.INFO,
            message="Processing",
            current=42,
            total=0
        )
        assert result.current == 42
        assert result.total == 0


class TestDiffResult:
    """Test DiffResult (before/after diffs)."""

    def test_diff_result(self):
        """Test diff with file changes."""
        result = DiffResult(
            status=ResultStatus.INFO,
            message="Changes to apply",
            summary="2 files changed",
            files=[
                {
                    "path": "main.py",
                    "old_content": "old code",
                    "new_content": "new code"
                },
                {
                    "path": "utils.py",
                    "old_content": "old utils",
                    "new_content": "new utils"
                }
            ]
        )
        assert result.summary == "2 files changed"
        assert len(result.files) == 2
        assert result.files[0]["path"] == "main.py"


# ============================================================================
# Interactive Result Tests
# ============================================================================

class TestConsentResult:
    """Test ConsentResult (user consent requests)."""

    def test_consent_request(self):
        """Test consent request."""
        result = ConsentResult(
            status=ResultStatus.INFO,
            message="Permission Required",
            question="Allow file write?",
            options=["allow", "deny", "allow-session"],
            context="Writing to /etc/config.json"
        )
        assert result.question == "Allow file write?"
        assert len(result.options) == 3
        assert "allow" in result.options
        assert result.context == "Writing to /etc/config.json"


class TestPromptResult:
    """Test PromptResult (text input prompts)."""

    def test_prompt_request(self):
        """Test text input prompt."""
        result = PromptResult(
            status=ResultStatus.INFO,
            message="Input Required",
            prompt="Enter session name:",
            placeholder="my-session",
            default=""
        )
        assert result.prompt == "Enter session name:"
        assert result.placeholder == "my-session"
        assert result.default == ""


# ============================================================================
# Composite Result Tests
# ============================================================================

class TestCompositeResult:
    """Test CompositeResult (multiple outputs)."""

    def test_composite_with_multiple_results(self):
        """Test composite result with nested results."""
        result = CompositeResult(
            status=ResultStatus.INFO,
            message="Analysis Complete",
            results=[
                NotificationResult(
                    status=ResultStatus.SUCCESS,
                    message="Step 1 complete"
                ),
                TableResult(
                    status=ResultStatus.INFO,
                    message="Results",
                    columns=["A", "B"],
                    rows=[["1", "2"]]
                ),
                ImageResult(
                    status=ResultStatus.INFO,
                    message="chart.png",
                    filepath="/path/to/chart.png",
                    format="png"
                )
            ]
        )
        assert len(result.results) == 3
        assert isinstance(result.results[0], NotificationResult)
        assert isinstance(result.results[1], TableResult)
        assert isinstance(result.results[2], ImageResult)

    def test_empty_composite(self):
        """Test empty composite."""
        result = CompositeResult(
            status=ResultStatus.INFO,
            message="No results",
            results=[]
        )
        assert result.results == []


class TestToolExecutionResult:
    """Test ToolExecutionResult (tool execution wrapper)."""

    def test_successful_tool_execution(self):
        """Test successful tool execution with artifacts."""
        result = ToolExecutionResult(
            status=ResultStatus.SUCCESS,
            message="Script executed successfully",
            tool_name="run_python",
            duration=1.23,
            stdout="Hello, world!",
            stderr="",
            exit_code=0,
            artifacts=[
                ImageResult(
                    status=ResultStatus.INFO,
                    message="plot.png",
                    filepath="/tmp/plot.png",
                    format="png"
                ),
                TableResult(
                    status=ResultStatus.INFO,
                    message="Data",
                    columns=["X", "Y"],
                    rows=[["1", "2"]]
                )
            ]
        )
        assert result.success is True
        assert result.tool_name == "run_python"
        assert result.duration == 1.23
        assert result.exit_code == 0
        assert len(result.artifacts) == 2

    def test_failed_tool_execution(self):
        """Test failed tool execution."""
        result = ToolExecutionResult(
            status=ResultStatus.ERROR,
            message="Script failed",
            tool_name="run_python",
            duration=0.5,
            stdout="",
            stderr="ImportError: No module named 'pandas'",
            exit_code=1,
            artifacts=[]
        )
        assert result.success is False
        assert result.failed is True
        assert result.exit_code == 1
        assert "ImportError" in result.stderr


class TestTextResult:
    """Test TextResult (generic fallback)."""

    def test_success_text(self):
        """Test success text result."""
        result = TextResult(
            status=ResultStatus.SUCCESS,
            message="Operation successful"
        )
        assert result.status == ResultStatus.SUCCESS
        assert result.success is True

    def test_error_text_with_details(self):
        """Test error text result with details."""
        result = TextResult(
            status=ResultStatus.ERROR,
            message="Error occurred",
            error_details="Stack trace here"
        )
        assert result.failed is True
        assert result.error_details == "Stack trace here"


# ============================================================================
# Integration Tests
# ============================================================================

class TestResultStatusProperties:
    """Test status properties across all result types."""

    def test_success_property(self):
        """Test success property."""
        success_result = NotificationResult(
            status=ResultStatus.SUCCESS,
            message="OK"
        )
        error_result = ErrorResult(status=ResultStatus.ERROR, message="Error")

        assert success_result.success is True
        assert error_result.success is False

    def test_failed_property(self):
        """Test failed property."""
        success_result = ConfirmationResult(
            status=ResultStatus.SUCCESS,
            message="OK"
        )
        error_result = ErrorResult(status=ResultStatus.ERROR, message="Error")

        assert success_result.failed is False
        assert error_result.failed is True

    def test_warning_status(self):
        """Test warning status (neither success nor failed)."""
        warning = NotificationResult(
            status=ResultStatus.WARNING,
            message="Warning"
        )
        assert warning.success is False
        assert warning.failed is False


class TestNestedCompositeResults:
    """Test nested composite results."""

    def test_deeply_nested_composite(self):
        """Test composite containing another composite."""
        nested = CompositeResult(
            status=ResultStatus.INFO,
            message="Nested analysis",
            results=[
                CompositeResult(
                    status=ResultStatus.INFO,
                    message="Inner composite",
                    results=[
                        NotificationResult(
                            status=ResultStatus.SUCCESS,
                            message="Deep notification"
                        )
                    ]
                ),
                TableResult(
                    status=ResultStatus.INFO,
                    message="Data",
                    columns=["A"],
                    rows=[["1"]]
                )
            ]
        )

        assert len(nested.results) == 2
        assert isinstance(nested.results[0], CompositeResult)
        inner_composite = nested.results[0]
        assert len(inner_composite.results) == 1
        assert isinstance(inner_composite.results[0], NotificationResult)


class TestMetadataField:
    """Test metadata field on all result types."""

    def test_metadata_defaults_to_empty_dict(self):
        """Test that metadata defaults to empty dict."""
        result = NotificationResult(
            status=ResultStatus.SUCCESS,
            message="Test"
        )
        assert result.metadata == {}

    def test_custom_metadata(self):
        """Test custom metadata."""
        result = TableResult(
            status=ResultStatus.INFO,
            message="Table",
            columns=["A"],
            rows=[["1"]],
            metadata={
                "query": "SELECT * FROM users",
                "execution_time": 0.123
            }
        )
        assert result.metadata["query"] == "SELECT * FROM users"
        assert result.metadata["execution_time"] == 0.123


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
