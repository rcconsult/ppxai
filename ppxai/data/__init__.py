"""
Data format handling module for ppxai.

Provides format detection, parsing, and rendering for:
- Tabular data: CSV, TSV
- Structured data: JSON, YAML, TOML, HCL

v1.13.8: Initial implementation
"""

from .format_detector import (
    detect_format,
    detect_delimiter,
    is_data_format,
    EXTENSION_MAP,
    TABULAR_FORMATS,
    STRUCTURED_FORMATS,
)
from .parsers import (
    TableData,
    TreeNode,
    parse_csv,
    parse_json,
    parse_yaml,
    parse_toml,
    parse_hcl,
    parse_structured,
)
from .renderers_tui import (
    render_table_tui,
    render_tree_tui,
    render_source_tui,
    InteractiveTableViewer,
    InteractiveTreeViewer,
)

__all__ = [
    # Format detection
    "detect_format",
    "detect_delimiter",
    "is_data_format",
    "EXTENSION_MAP",
    "TABULAR_FORMATS",
    "STRUCTURED_FORMATS",
    # Data structures
    "TableData",
    "TreeNode",
    # Parsers
    "parse_csv",
    "parse_json",
    "parse_yaml",
    "parse_toml",
    "parse_hcl",
    "parse_structured",
    # TUI Renderers
    "render_table_tui",
    "render_tree_tui",
    "render_source_tui",
    "InteractiveTableViewer",
    "InteractiveTreeViewer",
]
