"""
Data parsers for ppxai.

Parses CSV, TSV, JSON, YAML, TOML, HCL into structured data.

v1.13.8: Initial implementation
"""

import csv
import json
import io
from dataclasses import dataclass, field
from typing import Any, List, Optional, Union


@dataclass
class TableData:
    """Parsed tabular data (CSV/TSV)."""

    headers: List[str]
    rows: List[List[str]]
    row_count: int = 0
    column_count: int = 0
    truncated: bool = False  # True if max_rows limit was hit

    def __post_init__(self):
        self.row_count = len(self.rows)
        self.column_count = len(self.headers) if self.headers else 0


@dataclass
class TreeNode:
    """Node in a parsed tree structure (JSON/YAML/TOML/HCL)."""

    key: str
    value: Any = None
    node_type: str = "null"  # 'object', 'array', 'string', 'number', 'boolean', 'null'
    children: List["TreeNode"] = field(default_factory=list)
    depth: int = 0

    @property
    def is_leaf(self) -> bool:
        return len(self.children) == 0

    @property
    def child_count(self) -> int:
        return len(self.children)


def parse_csv(
    content: str,
    delimiter: str = ",",
    max_rows: int = 10000,
    max_columns: int = 50,
    has_header: bool = True,
) -> TableData:
    """
    Parse CSV/TSV content into TableData.

    Args:
        content: CSV/TSV content string
        delimiter: Column delimiter
        max_rows: Maximum rows to parse (for performance)
        max_columns: Maximum columns to include
        has_header: Whether first row is header

    Returns:
        TableData with headers and rows
    """
    reader = csv.reader(io.StringIO(content), delimiter=delimiter)
    rows_list = []
    headers = []
    truncated = False

    for i, row in enumerate(reader):
        if i == 0 and has_header:
            headers = row[:max_columns]
            # Ensure headers are strings and non-empty
            headers = [str(h).strip() or f"Column {j+1}" for j, h in enumerate(headers)]
            continue

        if i > max_rows:
            truncated = True
            break

        # Truncate columns if needed
        row_data = [str(cell) for cell in row[:max_columns]]
        # Pad row if shorter than headers
        while len(row_data) < len(headers):
            row_data.append("")
        rows_list.append(row_data)

    # If no header row, generate column names
    if not headers and rows_list:
        headers = [f"Column {i+1}" for i in range(len(rows_list[0]))]

    return TableData(
        headers=headers,
        rows=rows_list,
        truncated=truncated,
    )


def parse_json(
    content: str,
    max_depth: int = 10,
    root_key: str = "root",
) -> TreeNode:
    """
    Parse JSON content into TreeNode structure.

    Args:
        content: JSON string
        max_depth: Maximum nesting depth to parse
        root_key: Key name for root node

    Returns:
        TreeNode representing the JSON structure
    """
    data = json.loads(content)
    return _build_tree(root_key, data, depth=0, max_depth=max_depth)


def parse_yaml(
    content: str,
    max_depth: int = 10,
    root_key: str = "root",
) -> TreeNode:
    """
    Parse YAML content into TreeNode structure.

    Args:
        content: YAML string
        max_depth: Maximum nesting depth to parse
        root_key: Key name for root node

    Returns:
        TreeNode representing the YAML structure
    """
    try:
        import yaml
        data = yaml.safe_load(content)
        return _build_tree(root_key, data, depth=0, max_depth=max_depth)
    except ImportError:
        raise ImportError("PyYAML is required for YAML parsing: pip install pyyaml")


def parse_toml(
    content: str,
    max_depth: int = 10,
    root_key: str = "root",
) -> TreeNode:
    """
    Parse TOML content into TreeNode structure.

    Args:
        content: TOML string
        max_depth: Maximum nesting depth to parse
        root_key: Key name for root node

    Returns:
        TreeNode representing the TOML structure
    """
    try:
        # Python 3.11+ has tomllib built-in
        import tomllib
        data = tomllib.loads(content)
    except ImportError:
        try:
            # Fallback to tomli for older Python
            import tomli as tomllib
            data = tomllib.loads(content)
        except ImportError:
            raise ImportError("tomli is required for TOML parsing on Python < 3.11")

    return _build_tree(root_key, data, depth=0, max_depth=max_depth)


def parse_hcl(
    content: str,
    max_depth: int = 10,
    root_key: str = "root",
) -> TreeNode:
    """
    Parse HCL/Terraform content into TreeNode structure.

    Args:
        content: HCL string
        max_depth: Maximum nesting depth to parse
        root_key: Key name for root node

    Returns:
        TreeNode representing the HCL structure
    """
    try:
        import hcl2
        # hcl2 returns a dict
        data = hcl2.loads(content)
        return _build_tree(root_key, data, depth=0, max_depth=max_depth)
    except ImportError:
        raise ImportError("python-hcl2 is required for HCL parsing: pip install python-hcl2")


def parse_structured(
    content: str,
    format_type: str,
    max_depth: int = 10,
    root_key: str = "root",
) -> TreeNode:
    """
    Parse structured content based on format type.

    Args:
        content: Content string
        format_type: One of 'json', 'yaml', 'toml', 'hcl'
        max_depth: Maximum nesting depth
        root_key: Key name for root node

    Returns:
        TreeNode representing the structure

    Raises:
        ValueError: If format_type is not supported
    """
    parsers = {
        "json": parse_json,
        "jsonl": lambda c, **kw: parse_json(f"[{','.join(c.strip().split(chr(10)))}]", **kw),
        "yaml": parse_yaml,
        "toml": parse_toml,
        "hcl": parse_hcl,
    }

    if format_type not in parsers:
        raise ValueError(f"Unsupported format: {format_type}")

    return parsers[format_type](content, max_depth=max_depth, root_key=root_key)


def _build_tree(
    key: str,
    value: Any,
    depth: int = 0,
    max_depth: int = 10,
) -> TreeNode:
    """
    Recursively build TreeNode from Python object.

    Args:
        key: Key/name for this node
        value: Python value (dict, list, str, int, etc.)
        depth: Current depth
        max_depth: Maximum depth to traverse

    Returns:
        TreeNode representing the value
    """
    node_type = _get_type_name(value)

    if depth >= max_depth:
        # Truncate at max depth
        if isinstance(value, dict):
            return TreeNode(
                key=key,
                value=f"{{...{len(value)} keys}}",
                node_type="object",
                depth=depth,
            )
        elif isinstance(value, list):
            return TreeNode(
                key=key,
                value=f"[...{len(value)} items]",
                node_type="array",
                depth=depth,
            )

    if isinstance(value, dict):
        children = [
            _build_tree(str(k), v, depth + 1, max_depth)
            for k, v in value.items()
        ]
        return TreeNode(
            key=key,
            value=None,
            node_type="object",
            children=children,
            depth=depth,
        )

    elif isinstance(value, list):
        children = [
            _build_tree(f"[{i}]", v, depth + 1, max_depth)
            for i, v in enumerate(value)
        ]
        return TreeNode(
            key=key,
            value=None,
            node_type="array",
            children=children,
            depth=depth,
        )

    else:
        # Leaf node
        return TreeNode(
            key=key,
            value=value,
            node_type=node_type,
            depth=depth,
        )


def _get_type_name(value: Any) -> str:
    """Get type name for a value."""
    if value is None:
        return "null"
    elif isinstance(value, bool):
        return "boolean"
    elif isinstance(value, int):
        return "number"
    elif isinstance(value, float):
        return "number"
    elif isinstance(value, str):
        return "string"
    elif isinstance(value, dict):
        return "object"
    elif isinstance(value, list):
        return "array"
    else:
        return "unknown"
