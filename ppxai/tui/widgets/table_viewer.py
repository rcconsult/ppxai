"""
TableViewer widget - Tabular data display for CSV/TSV files.

Uses Textual's DataTable for grid display with table/source toggle.
Supports CSV, TSV, PSV with automatic delimiter detection.
"""

import csv
import io
from pathlib import Path
from typing import Any, List, Literal, Optional, Tuple

from textual.app import ComposeResult
from textual.binding import Binding
from textual.css.query import NoMatches
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import ContentSwitcher, DataTable, Static

from .code_editor import CodeEditor


# Type alias for view modes
ViewMode = Literal["table", "source"]

# Supported delimiters
DELIMITERS = {
    ",": "CSV",
    "\t": "TSV",
    "|": "PSV",
    ";": "CSV (semicolon)",
}

# File extensions and their expected delimiters
EXTENSION_DELIMITERS = {
    ".csv": ",",
    ".tsv": "\t",
    ".tab": "\t",
    ".psv": "|",
}

# Maximum rows to display initially (for large files)
MAX_INITIAL_ROWS = 1000

# Maximum column width
MAX_COLUMN_WIDTH = 50


def detect_delimiter(content: str) -> str:
    """Detect the delimiter used in tabular data.

    Args:
        content: The file content to analyze

    Returns:
        The detected delimiter character
    """
    # Take first few lines for analysis
    lines = content.split("\n")[:10]
    sample = "\n".join(lines)

    # Count occurrences of each delimiter
    counts = {}
    for delim in [",", "\t", "|", ";"]:
        counts[delim] = sample.count(delim)

    # Return delimiter with highest count (minimum 1)
    best = max(counts.items(), key=lambda x: x[1])
    return best[0] if best[1] > 0 else ","


def detect_has_header(rows: List[List[str]]) -> bool:
    """Heuristic to detect if first row is a header.

    Args:
        rows: Parsed rows of data

    Returns:
        True if first row appears to be a header
    """
    if len(rows) < 2:
        return False

    header = rows[0]
    data_row = rows[1]

    # Check if header has different characteristics than data
    # Headers often have no numbers, different lengths, etc.
    header_numeric = sum(1 for cell in header if cell.replace(".", "").replace("-", "").isdigit())
    data_numeric = sum(1 for cell in data_row if cell.replace(".", "").replace("-", "").isdigit())

    # If header has fewer numeric values, likely a header
    if header_numeric < data_numeric:
        return True

    # If all header cells are short strings with no spaces, likely a header
    if all(len(cell) < 30 and " " not in cell for cell in header):
        return True

    return False


def parse_tabular(content: str, delimiter: str = None) -> Tuple[List[str], List[List[str]], str]:
    """Parse tabular data content.

    Args:
        content: Raw file content
        delimiter: Delimiter to use (auto-detect if None)

    Returns:
        Tuple of (headers, rows, detected_delimiter)
    """
    if delimiter is None:
        delimiter = detect_delimiter(content)

    # Parse with csv module
    reader = csv.reader(io.StringIO(content), delimiter=delimiter)
    all_rows = list(reader)

    if not all_rows:
        return [], [], delimiter

    # Detect header
    has_header = detect_has_header(all_rows)

    if has_header:
        headers = all_rows[0]
        rows = all_rows[1:]
    else:
        # Generate column names
        max_cols = max(len(row) for row in all_rows) if all_rows else 0
        headers = [f"Col {i+1}" for i in range(max_cols)]
        rows = all_rows

    return headers, rows, delimiter


class TableViewer(Widget):
    """A widget for viewing tabular data (CSV, TSV, PSV).

    Features:
    - Table view using DataTable
    - Source view using CodeEditor
    - Ctrl+V toggles between views
    - Automatic delimiter detection
    - Header detection

    Keybindings:
        Ctrl+V : Toggle between table and source view
    """

    can_focus = True
    can_focus_children = True

    BINDINGS = [
        Binding("ctrl+v", "toggle_view", "Toggle View", show=True, priority=True),
    ]

    # Reactive view mode
    view_mode: reactive[ViewMode] = reactive("table")

    class ViewToggled(Message):
        """Posted when view mode changes."""

        def __init__(self, mode: ViewMode):
            super().__init__()
            self.mode = mode

    def __init__(
        self,
        id: str = None,
    ):
        """Initialize the table viewer.

        Args:
            id: Widget ID
        """
        super().__init__(id=id)
        self._headers: List[str] = []
        self._rows: List[List[str]] = []
        self._source: str = ""
        self._filename: str = "data.csv"
        self._delimiter: str = ","
        self._total_rows: int = 0
        self._displayed_rows: int = 0

    def compose(self) -> ComposeResult:
        """Compose the table viewer layout."""
        # Header showing filename, format, and current view
        delim_name = DELIMITERS.get(self._delimiter, "Unknown")
        view_label = "Table" if self.view_mode == "table" else "Source"
        header_text = f" [bold]{self._filename}[/bold] [dim]({delim_name})[/dim] [{view_label}] [dim]Ctrl+V toggle[/dim]"
        yield Static(header_text, classes="table-viewer-header", id="table-header")

        # Content switcher for table/source views
        with ContentSwitcher(initial="table-view", id="table-content-switcher"):
            # Table view
            yield DataTable(id="table-view")

            # Source view (read-only CodeEditor)
            yield CodeEditor(
                text=self._source,
                language=None,  # Plain text, no syntax highlighting
                read_only=True,
                show_header=False,
                id="source-view",
            )

    def on_mount(self) -> None:
        """Called when mounted - populate table if data exists."""
        if self._headers or self._rows:
            self._populate_table()

    def _populate_table(self) -> None:
        """Populate the DataTable with current data."""
        try:
            table = self.query_one("#table-view", DataTable)
        except Exception:
            return

        # Clear existing data
        table.clear(columns=True)

        if not self._headers:
            return

        # Add columns
        for header in self._headers:
            # Truncate long headers
            display_header = header[:MAX_COLUMN_WIDTH] if len(header) > MAX_COLUMN_WIDTH else header
            table.add_column(display_header, key=header)

        # Add rows (limit for performance)
        rows_to_add = self._rows[:MAX_INITIAL_ROWS]
        self._displayed_rows = len(rows_to_add)

        for row in rows_to_add:
            # Ensure row has correct number of columns
            padded_row = row + [""] * (len(self._headers) - len(row))
            # Truncate long cells
            display_row = [
                cell[:MAX_COLUMN_WIDTH] + "..." if len(cell) > MAX_COLUMN_WIDTH else cell
                for cell in padded_row[:len(self._headers)]
            ]
            table.add_row(*display_row)

    def watch_view_mode(self, mode: ViewMode) -> None:
        """React to view mode changes."""
        # Update header
        try:
            header = self.query_one("#table-header", Static)
            delim_name = DELIMITERS.get(self._delimiter, "Unknown")
            view_label = "Table" if mode == "table" else "Source"
            header.update(f" [bold]{self._filename}[/bold] [dim]({delim_name})[/dim] [{view_label}] [dim]Ctrl+V toggle[/dim]")
        except Exception:
            pass

        # Switch content
        try:
            switcher = self.query_one("#table-content-switcher", ContentSwitcher)
            switcher.current = "table-view" if mode == "table" else "source-view"
        except Exception:
            pass

        # Focus the appropriate view after switching
        self._focus_current_view()

        # Post message
        self.post_message(self.ViewToggled(mode))

    def _focus_current_view(self) -> None:
        """Focus the widget for the current view mode."""
        if self.view_mode == "table":
            def focus_table():
                try:
                    table = self.query_one("#table-view", DataTable)
                    table.focus()
                except NoMatches:
                    pass
            self.call_after_refresh(focus_table)
        else:  # source
            def focus_editor():
                try:
                    # Focus the TextArea inside CodeEditor, not the container
                    editor = self.query_one("#source-view", CodeEditor)
                    text_area = editor.query_one("#code-text-area")
                    text_area.focus()
                except NoMatches:
                    pass
            self.call_after_refresh(focus_editor)

    def action_toggle_view(self) -> None:
        """Toggle between table and source view (Ctrl+V)."""
        self.view_mode = "source" if self.view_mode == "table" else "table"

    def load_csv(self, content: str, filename: str = "data.csv") -> bool:
        """Load CSV data.

        Args:
            content: CSV content
            filename: Filename for display

        Returns:
            True if loaded successfully
        """
        return self._load_tabular(content, filename, ",")

    def load_tsv(self, content: str, filename: str = "data.tsv") -> bool:
        """Load TSV data.

        Args:
            content: TSV content
            filename: Filename for display

        Returns:
            True if loaded successfully
        """
        return self._load_tabular(content, filename, "\t")

    def load_auto(self, content: str, filename: str = "data.csv") -> bool:
        """Load tabular data with auto-detected delimiter.

        Args:
            content: File content
            filename: Filename for display

        Returns:
            True if loaded successfully
        """
        return self._load_tabular(content, filename, None)

    def _load_tabular(self, content: str, filename: str, delimiter: str = None) -> bool:
        """Load tabular data.

        Args:
            content: File content
            filename: Filename for display
            delimiter: Delimiter (None for auto-detect)

        Returns:
            True if loaded successfully
        """
        try:
            headers, rows, detected_delim = parse_tabular(content, delimiter)

            self._headers = headers
            self._rows = rows
            self._source = content
            self._filename = filename
            self._delimiter = detected_delim
            self._total_rows = len(rows)

            # Update source editor
            try:
                editor = self.query_one("#source-view", CodeEditor)
                editor.text = content
            except Exception:
                pass

            # Populate table
            self._populate_table()

            # Update header
            try:
                header = self.query_one("#table-header", Static)
                delim_name = DELIMITERS.get(self._delimiter, "Unknown")
                view_label = "Table" if self.view_mode == "table" else "Source"
                row_info = f"{self._displayed_rows}/{self._total_rows} rows" if self._total_rows > MAX_INITIAL_ROWS else f"{self._total_rows} rows"
                header.update(f" [bold]{self._filename}[/bold] [dim]({delim_name}, {row_info})[/dim] [{view_label}] [dim]Ctrl+V toggle[/dim]")
            except Exception:
                pass

            return True

        except Exception:
            return False

    def set_data(
        self,
        headers: List[str],
        rows: List[List[str]],
        filename: str = "data.csv",
        delimiter: str = ",",
    ) -> None:
        """Set table data directly.

        Args:
            headers: Column headers
            rows: Data rows
            filename: Filename for display
            delimiter: Delimiter used
        """
        self._headers = headers
        self._rows = rows
        self._filename = filename
        self._delimiter = delimiter
        self._total_rows = len(rows)

        # Generate source from data
        output = io.StringIO()
        writer = csv.writer(output, delimiter=delimiter)
        writer.writerow(headers)
        writer.writerows(rows)
        self._source = output.getvalue()

        # Update widgets
        try:
            editor = self.query_one("#source-view", CodeEditor)
            editor.text = self._source
        except Exception:
            pass

        self._populate_table()

    @property
    def headers(self) -> List[str]:
        """Get column headers."""
        return self._headers

    @property
    def rows(self) -> List[List[str]]:
        """Get data rows."""
        return self._rows

    @property
    def total_rows(self) -> int:
        """Get total row count."""
        return self._total_rows

    @property
    def displayed_rows(self) -> int:
        """Get displayed row count."""
        return self._displayed_rows

    @property
    def delimiter(self) -> str:
        """Get the delimiter."""
        return self._delimiter

    @property
    def filename(self) -> str:
        """Get the filename."""
        return self._filename

    @staticmethod
    def get_delimiter_for_extension(ext: str) -> Optional[str]:
        """Get expected delimiter for file extension.

        Args:
            ext: File extension (e.g., ".csv")

        Returns:
            Expected delimiter or None
        """
        return EXTENSION_DELIMITERS.get(ext.lower())

    @staticmethod
    def is_tabular_file(path: Path) -> bool:
        """Check if a file is a tabular data file.

        Args:
            path: Path to check

        Returns:
            True if file has a tabular extension
        """
        return path.suffix.lower() in EXTENSION_DELIMITERS
