"""
CSV tools for large-file lazy loading.

v1.17.4. Two tools that let the model read large CSV files the user has
attached via `/attach data.csv` or the web/VSCode file picker. Small
CSVs (< 50 KB) are inlined as text; large CSVs are stored in
SessionFileStore and referenced via `<uploaded_file>` markers, just
like PDFs.

    read_csv(file_id, rows="1-100", columns=None, format="markdown")
        -> read a row range from a stored CSV, return as markdown table
           or raw CSV

    list_csv_columns(file_id)
        -> return column names, inferred types, and row count

Both tools resolve `file_id` through the engine's SessionFileStore.
No external dependencies required -- csv is part of the Python stdlib.
"""

from __future__ import annotations

import csv
import io
from typing import Any

from ...types import ToolEngineProtocol, ToolManagerProtocol
from ..base import BaseTool

# Maximum characters to return per tool call. Matches the default
# `_MAX_TEXT_CHARS` used by PDF tools and elsewhere in the engine.
_MAX_TEXT_CHARS = 100_000

# Maximum rows per request to prevent runaway output.
_MAX_ROWS_PER_REQUEST = 5000


def _resolve_file(engine: Any, file_id: str) -> tuple[Any | None, str | None]:
    """Look up a file_id in the engine's SessionFileStore.

    Returns (FileMetadata, None) on success or (None, error_message) on
    failure.
    """
    file_store = getattr(engine, "file_store", None)
    if file_store is None:
        return None, (
            "No SessionFileStore available on the engine. CSV tools require "
            "the file store to resolve file_id references."
        )

    meta = file_store.get_metadata(file_id)
    if meta is None:
        return None, (
            f"Unknown file_id: {file_id!r}. The attachment may have been "
            "removed or the session cleared. Ask the user to re-attach."
        )

    if not meta.path.exists():
        return None, (
            f"File for {file_id!r} is missing on disk at {meta.path}. "
            "The session may be in an inconsistent state."
        )

    return meta, None


def _read_csv_rows(path: Any) -> tuple[list[str], list[list[str]]]:
    """Read all rows from a CSV file, returning (headers, rows).

    Uses csv.reader with sniffing for delimiter detection. Falls back
    to comma if sniffing fails.
    """
    text = path.read_text(encoding="utf-8", errors="replace")

    # Sniff delimiter from first 8 KB
    try:
        dialect = csv.Sniffer().sniff(text[:8192])
        delimiter = dialect.delimiter
    except csv.Error:
        delimiter = ","

    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    rows = list(reader)
    if not rows:
        return [], []

    headers = rows[0]
    data_rows = rows[1:]
    return headers, data_rows


def _parse_rows_spec(spec: str, total_rows: int) -> tuple[int, int]:
    """Parse a rows selector like '1-100' into (start_idx, end_idx) 0-based.

    Accepts:
        "1-100"   -> rows 1 through 100 (1-indexed input)
        "50-200"  -> rows 50 through 200
        "all"     -> all rows (capped at _MAX_ROWS_PER_REQUEST)

    Returns (start_idx, end_idx) as 0-based indices into the data rows
    (excluding header).
    """
    if not spec or spec.lower() == "all":
        return 0, min(total_rows, _MAX_ROWS_PER_REQUEST)

    spec = spec.strip()
    if "-" in spec:
        parts = spec.split("-", 1)
        start = int(parts[0].strip())
        end = int(parts[1].strip())
    else:
        start = int(spec)
        end = start

    if start < 1:
        raise ValueError(f"row numbers are 1-indexed, got {start}")
    if end < start:
        raise ValueError(f"invalid range: {spec!r}")

    # Clamp to actual row count
    start_idx = min(start - 1, total_rows)
    end_idx = min(end, total_rows)

    # Cap range size
    if end_idx - start_idx > _MAX_ROWS_PER_REQUEST:
        end_idx = start_idx + _MAX_ROWS_PER_REQUEST

    return start_idx, end_idx


def _filter_columns(
    headers: list[str],
    rows: list[list[str]],
    columns: str | None,
) -> tuple[list[str], list[list[str]], str | None]:
    """Filter columns by name. Returns (filtered_headers, filtered_rows, error)."""
    if not columns:
        return headers, rows, None

    requested = [c.strip() for c in columns.split(",") if c.strip()]
    if not requested:
        return headers, rows, None

    # Build index map
    header_lower = {h.lower(): i for i, h in enumerate(headers)}
    indices = []
    missing = []
    for col in requested:
        idx = header_lower.get(col.lower())
        if idx is not None:
            indices.append(idx)
        else:
            missing.append(col)

    if missing:
        return headers, rows, (
            f"Unknown columns: {', '.join(missing)}. "
            f"Available: {', '.join(headers)}"
        )

    filtered_headers = [headers[i] for i in indices]
    filtered_rows = []
    for row in rows:
        filtered_rows.append([row[i] if i < len(row) else "" for i in indices])

    return filtered_headers, filtered_rows, None


def _format_markdown_table(headers: list[str], rows: list[list[str]]) -> str:
    """Format rows as a markdown table."""
    if not headers:
        return "(empty CSV)"

    lines = []
    lines.append("| " + " | ".join(headers) + " |")
    lines.append("| " + " | ".join(["---"] * len(headers)) + " |")
    for row in rows:
        # Pad row to header length
        padded = row + [""] * (len(headers) - len(row))
        # Escape pipe characters in cell values
        cells = [cell.replace("|", "\\|") for cell in padded[:len(headers)]]
        lines.append("| " + " | ".join(cells) + " |")

    return "\n".join(lines)


def _format_csv(headers: list[str], rows: list[list[str]]) -> str:
    """Format rows as raw CSV text."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(headers)
    writer.writerows(rows)
    return buf.getvalue()


def _infer_type(values: list[str]) -> str:
    """Infer column type from a sample of values."""
    non_empty = [v.strip() for v in values if v.strip()]
    if not non_empty:
        return "empty"

    # Try integer
    int_count = 0
    float_count = 0
    for v in non_empty:
        try:
            int(v.replace(",", ""))
            int_count += 1
            continue
        except ValueError:
            pass
        try:
            float(v.replace(",", ""))
            float_count += 1
        except ValueError:
            pass

    total = len(non_empty)
    if int_count == total:
        return "integer"
    if int_count + float_count == total:
        return "number"

    # Check for boolean
    bool_vals = {"true", "false", "yes", "no", "0", "1"}
    if all(v.lower() in bool_vals for v in non_empty):
        return "boolean"

    return "string"


# =============================================================================
# ReadCsvTool
# =============================================================================


class ReadCsvTool(BaseTool):
    """Read rows from a stored CSV file by file_id.

    Resolves the `file_id` through SessionFileStore, parses with the
    csv stdlib module, and returns a markdown table or raw CSV for the
    requested row range.
    """

    def __init__(self, engine: ToolEngineProtocol):
        self.engine = engine
        self.name = "read_csv"
        self.description = (
            "Read rows from a CSV file the user has attached to the conversation. "
            "Use this to access the content of large CSV files referenced by "
            "<uploaded_file> markers. Pass the 'file_id' from the marker. "
            "Optionally specify a row range (e.g., '1-100'), specific columns, "
            "and output format."
        )
        self.parameters: dict[str, Any] = {
            "type": "object",
            "properties": {
                "file_id": {
                    "type": "string",
                    "description": (
                        "The file_id from the <uploaded_file file_id=\"...\"> "
                        "reference block in the conversation context."
                    ),
                },
                "rows": {
                    "type": "string",
                    "description": (
                        "Row range to read. Format: '1-100' (1-indexed, inclusive). "
                        "Default '1-100'. Use 'all' to read all rows (capped at "
                        f"{_MAX_ROWS_PER_REQUEST})."
                    ),
                    "default": "1-100",
                },
                "columns": {
                    "type": "string",
                    "description": (
                        "Comma-separated column names to include. "
                        "Default: all columns. Example: 'name,age,city'"
                    ),
                },
                "format": {
                    "type": "string",
                    "description": (
                        "Output format: 'markdown' (default) for a markdown table, "
                        "or 'csv' for raw CSV text."
                    ),
                    "enum": ["markdown", "csv"],
                    "default": "markdown",
                },
            },
            "required": ["file_id"],
        }

    async def execute(
        self,
        file_id: str,
        rows: str = "1-100",
        columns: str | None = None,
        format: str = "markdown",
        **kwargs,
    ) -> str:
        meta, err = _resolve_file(self.engine, file_id)
        if err:
            return f"Error: {err}"

        try:
            headers, data_rows = _read_csv_rows(meta.path)
        except Exception as exc:
            return f"Error reading CSV {meta.name!r}: {exc}"

        total_rows = len(data_rows)
        if not headers and total_rows == 0:
            return f"{meta.name}: empty CSV file."

        try:
            start_idx, end_idx = _parse_rows_spec(rows, total_rows)
        except ValueError as exc:
            return f"Error parsing rows={rows!r}: {exc}"

        selected_rows = data_rows[start_idx:end_idx]

        # Filter columns if requested
        display_headers, display_rows, col_err = _filter_columns(
            headers, selected_rows, columns,
        )
        if col_err:
            return f"Error: {col_err}"

        # Format output
        if format == "csv":
            result = _format_csv(display_headers, display_rows)
        else:
            result = _format_markdown_table(display_headers, display_rows)

        # Build header info
        showing = f"rows {start_idx + 1}-{start_idx + len(display_rows)}"
        header = (
            f"# {meta.name} ({total_rows} data rows, {len(headers)} columns)\n"
            f"Showing {showing} of {total_rows}\n\n"
        )
        result = header + result

        # Truncate if too large
        if len(result) > _MAX_TEXT_CHARS:
            result = result[:_MAX_TEXT_CHARS]
            result += (
                f"\n\n[Output truncated at {_MAX_TEXT_CHARS:,} chars. "
                f"Use a narrower row range or fewer columns.]"
            )

        return result


# =============================================================================
# ListCsvColumnsTool
# =============================================================================


class ListCsvColumnsTool(BaseTool):
    """List columns, inferred types, and row count of a stored CSV."""

    def __init__(self, engine: ToolEngineProtocol):
        self.engine = engine
        self.name = "list_csv_columns"
        self.description = (
            "List the column names, inferred data types, and row count of a CSV "
            "file the user has attached. Use this to understand the structure of "
            "a CSV before reading specific rows or columns with read_csv."
        )
        self.parameters: dict[str, Any] = {
            "type": "object",
            "properties": {
                "file_id": {
                    "type": "string",
                    "description": (
                        "The file_id from the <uploaded_file file_id=\"...\"> "
                        "reference block in the conversation context."
                    ),
                },
            },
            "required": ["file_id"],
        }

    async def execute(self, file_id: str, **kwargs) -> str:
        meta, err = _resolve_file(self.engine, file_id)
        if err:
            return f"Error: {err}"

        try:
            headers, data_rows = _read_csv_rows(meta.path)
        except Exception as exc:
            return f"Error reading CSV {meta.name!r}: {exc}"

        total_rows = len(data_rows)

        if not headers:
            return f"{meta.name}: empty CSV (no headers found)."

        # Infer types from first 10 rows
        sample_rows = data_rows[:10]
        lines = [
            f"# {meta.name}",
            f"- **Rows:** {total_rows}",
            f"- **Columns:** {len(headers)}",
            f"- **Size:** {meta.size / 1024:.1f} KB",
            "",
            "| # | Column | Type | Sample |",
            "| --- | --- | --- | --- |",
        ]

        for i, header in enumerate(headers):
            sample_values = [
                row[i] if i < len(row) else "" for row in sample_rows
            ]
            col_type = _infer_type(sample_values)
            # Show first non-empty sample value
            sample = next((v for v in sample_values if v.strip()), "")
            if len(sample) > 50:
                sample = sample[:47] + "..."
            sample = sample.replace("|", "\\|")
            lines.append(f"| {i + 1} | {header} | {col_type} | {sample} |")

        return "\n".join(lines)


# =============================================================================
# Registration
# =============================================================================


def register_tools(manager: ToolManagerProtocol, engine: ToolEngineProtocol) -> bool:
    """Register CSV tools with the manager.

    No optional dependencies required -- csv is part of Python stdlib.
    Always registers successfully when engine is provided.

    Args:
        manager: ToolManager instance.
        engine: EngineClient -- required because the tools resolve
                `file_id` through `engine.file_store`.

    Returns:
        True if tools were registered, False otherwise.
    """
    if engine is None:
        return False

    manager.register_tool(ReadCsvTool(engine))
    manager.register_tool(ListCsvColumnsTool(engine))
    return True


__all__ = [
    "ReadCsvTool",
    "ListCsvColumnsTool",
    "register_tools",
]
