"""
TreeViewer widget - Hierarchical display for JSON/YAML/TOML data.

Uses Textual's built-in Tree widget to display structured data
in an expandable tree format.
"""

import json
from typing import Any, Optional

from textual.app import ComposeResult
from textual.widgets import Static, Tree
from textual.widgets.tree import TreeNode


class TreeViewer(Static):
    """A widget for displaying hierarchical data (JSON, YAML, TOML)."""

    # CSS is in layout.tcss

    def __init__(
        self,
        data: Any = None,
        title: str = "Data",
        format: str = "auto",
        id: str = None,
    ):
        """Initialize the tree viewer.

        Args:
            data: The data to display (dict, list, or primitive)
            title: Root node label
            format: Data format hint ("json", "yaml", "toml", or "auto")
            id: Widget ID
        """
        super().__init__(id=id)
        self._data = data
        self._title = title
        self._format = format
        self._tree: Optional[Tree] = None

    def compose(self) -> ComposeResult:
        """Compose the tree widget."""
        self._tree = Tree(self._title)
        self._tree.root.expand()
        if self._data is not None:
            self._populate_tree(self._tree.root, self._data)
        yield self._tree

    def _populate_tree(self, node: TreeNode, data: Any) -> None:
        """Recursively populate tree nodes from data.

        Args:
            node: Parent tree node
            data: Data to add (dict, list, or primitive)
        """
        if isinstance(data, dict):
            for key, value in data.items():
                if isinstance(value, (dict, list)):
                    # Expandable node for nested structures
                    child = node.add(f"[bold]{key}[/bold]", expand=False)
                    self._populate_tree(child, value)
                else:
                    # Leaf node for primitive values
                    node.add_leaf(self._format_leaf(key, value))
        elif isinstance(data, list):
            for i, item in enumerate(data):
                if isinstance(item, (dict, list)):
                    child = node.add(f"[dim][[/dim]{i}[dim]][/dim]", expand=False)
                    self._populate_tree(child, item)
                else:
                    node.add_leaf(f"[dim][[/dim]{i}[dim]][/dim] {self._format_value(item)}")
        else:
            # Primitive value at root
            node.add_leaf(self._format_value(data))

    def _format_leaf(self, key: str, value: Any) -> str:
        """Format a key-value pair for display.

        Args:
            key: The key name
            value: The value

        Returns:
            Formatted string with Rich markup
        """
        return f"[bold]{key}[/bold]: {self._format_value(value)}"

    def _format_value(self, value: Any) -> str:
        """Format a value for display with appropriate styling.

        Args:
            value: The value to format

        Returns:
            Formatted string with Rich markup
        """
        if value is None:
            return "[dim italic]null[/dim italic]"
        elif isinstance(value, bool):
            return f"[cyan]{str(value).lower()}[/cyan]"
        elif isinstance(value, (int, float)):
            return f"[yellow]{value}[/yellow]"
        elif isinstance(value, str):
            # Escape Rich markup in strings and truncate long ones
            escaped = value.replace("[", "\\[")
            if len(escaped) > 50:
                escaped = escaped[:47] + "..."
            return f'[green]"{escaped}"[/green]'
        else:
            return str(value)

    def set_data(self, data: Any, title: str = None) -> None:
        """Update the tree with new data.

        Args:
            data: New data to display
            title: Optional new title
        """
        self._data = data
        if title:
            self._title = title

        if self._tree:
            # Clear and repopulate
            self._tree.root.remove_children()
            self._tree.root.set_label(self._title)
            if self._data is not None:
                self._populate_tree(self._tree.root, self._data)
            self._tree.root.expand()

    def load_json(self, text: str, title: str = "JSON") -> None:
        """Load and display JSON data.

        Args:
            text: JSON string to parse
            title: Root node label
        """
        try:
            data = json.loads(text)
            self.set_data(data, title)
        except json.JSONDecodeError as e:
            self.set_data({"error": str(e)}, "Parse Error")

    def load_yaml(self, text: str, title: str = "YAML") -> None:
        """Load and display YAML data.

        Args:
            text: YAML string to parse
            title: Root node label
        """
        try:
            import yaml
            data = yaml.safe_load(text)
            self.set_data(data, title)
        except Exception as e:
            self.set_data({"error": str(e)}, "Parse Error")

    def load_toml(self, text: str, title: str = "TOML") -> None:
        """Load and display TOML data.

        Args:
            text: TOML string to parse
            title: Root node label
        """
        try:
            import tomllib
            data = tomllib.loads(text)
            self.set_data(data, title)
        except Exception as e:
            self.set_data({"error": str(e)}, "Parse Error")

    def expand_all(self) -> None:
        """Expand all nodes in the tree."""
        if self._tree:
            self._tree.root.expand_all()

    def collapse_all(self) -> None:
        """Collapse all nodes in the tree."""
        if self._tree:
            self._tree.root.collapse_all()
            self._tree.root.expand()  # Keep root expanded
