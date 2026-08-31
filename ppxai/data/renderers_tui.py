"""
TUI renderers for data visualization using Rich.

Renders TableData as Rich Tables and TreeNode as Rich Trees.

v1.13.8: Initial implementation
"""

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text
from rich.tree import Tree

from .parsers import TableData, TreeNode

# Type colors for tree values
TYPE_STYLES = {
    "string": "green",
    "number": "yellow",
    "boolean": "magenta",
    "null": "dim italic",
    "object": "cyan",
    "array": "cyan",
    "unknown": "white",
}


def render_table_tui(
    data: TableData,
    console: Console,
    page: int = 0,
    page_size: int = 50,
    title: str | None = None,
    show_row_numbers: bool = True,
    show_controls: bool = False,
) -> dict:
    """
    Render TableData as a Rich Table with pagination info.

    Args:
        data: TableData to render
        console: Rich Console instance
        page: Current page number (0-indexed)
        page_size: Rows per page
        title: Optional table title
        show_row_numbers: Show row number column
        show_controls: Show keyboard control hints (for interactive mode)

    Returns:
        dict with pagination info: {page, total_pages, start_row, end_row}
    """
    total_pages = max(1, (data.row_count + page_size - 1) // page_size)
    page = max(0, min(page, total_pages - 1))

    start_row = page * page_size
    end_row = min(start_row + page_size, data.row_count)

    # Build title
    if title:
        table_title = title
    else:
        table_title = f"Rows {start_row + 1}-{end_row} of {data.row_count}"
        if data.truncated:
            table_title += " (truncated)"

    table = Table(
        title=table_title,
        show_header=True,
        header_style="bold cyan",
        box=box.ROUNDED,
        row_styles=["", "dim"],  # Alternating row styles
    )

    # Add row number column
    if show_row_numbers:
        table.add_column("#", style="dim", width=6, justify="right")

    # Add data columns
    for header in data.headers:
        # Truncate long headers
        display_header = header[:30] + "..." if len(header) > 30 else header
        table.add_column(display_header, overflow="fold")

    # Add rows for current page
    for i, row in enumerate(data.rows[start_row:end_row], start=start_row + 1):
        if show_row_numbers:
            table.add_row(str(i), *row)
        else:
            table.add_row(*row)

    console.print(table)

    # Show pagination controls (only in interactive mode)
    if show_controls:
        if total_pages > 1:
            controls = Text()
            controls.append(f"Page {page + 1}/{total_pages}", style="bold")
            controls.append(" | ", style="dim")
            controls.append("n", style="bold cyan")
            controls.append("=next ", style="dim")
            controls.append("p", style="bold cyan")
            controls.append("=prev ", style="dim")
            controls.append("g", style="bold cyan")
            controls.append("=goto ", style="dim")
            controls.append("s", style="bold cyan")
            controls.append("=source ", style="dim")
            controls.append("q", style="bold cyan")
            controls.append("=quit", style="dim")
            console.print(controls)
        else:
            controls = Text()
            controls.append("s", style="bold cyan")
            controls.append("=source ", style="dim")
            controls.append("q", style="bold cyan")
            controls.append("=quit", style="dim")
            console.print(controls)

    return {
        "page": page,
        "total_pages": total_pages,
        "start_row": start_row,
        "end_row": end_row,
    }


def render_tree_tui(
    node: TreeNode,
    console: Console,
    expand_depth: int = 2,
    title: str | None = None,
    max_value_length: int = 100,
    show_controls: bool = False,
) -> None:
    """
    Render TreeNode as a Rich Tree.

    Args:
        node: TreeNode to render
        console: Rich Console instance
        expand_depth: Depth to show expanded (deeper nodes show summary)
        title: Optional tree title
        max_value_length: Truncate values longer than this
        show_controls: Show keyboard control hints (for interactive mode)
    """
    # Create root tree
    root_label = _format_node_label(node, max_value_length, is_root=True)
    tree = Tree(root_label)

    # Build tree recursively
    _build_rich_tree(tree, node, current_depth=0, expand_depth=expand_depth, max_value_length=max_value_length)

    # Wrap in panel if title provided
    if title:
        console.print(Panel(tree, title=title, border_style="cyan"))
    else:
        console.print(tree)

    # Show controls (only in interactive mode)
    if show_controls:
        controls = Text()
        controls.append("e", style="bold cyan")
        controls.append("=expand-all ", style="dim")
        controls.append("c", style="bold cyan")
        controls.append("=collapse ", style="dim")
        controls.append("s", style="bold cyan")
        controls.append("=source ", style="dim")
        controls.append("q", style="bold cyan")
        controls.append("=quit", style="dim")
        console.print(controls)


def _build_rich_tree(
    parent: Tree,
    node: TreeNode,
    current_depth: int,
    expand_depth: int,
    max_value_length: int,
) -> None:
    """Recursively build Rich Tree from TreeNode."""
    for child in node.children:
        label = _format_node_label(child, max_value_length)

        if child.is_leaf:
            # Leaf node - just add it
            parent.add(label)
        else:
            # Branch node
            if current_depth < expand_depth:
                # Expand this level
                branch = parent.add(label)
                _build_rich_tree(branch, child, current_depth + 1, expand_depth, max_value_length)
            else:
                # Collapse - show summary
                summary = _get_collapse_summary(child)
                collapsed_label = Text()
                collapsed_label.append(child.key, style="cyan")
                collapsed_label.append(f": {summary}", style="dim")
                parent.add(collapsed_label)


def _format_node_label(
    node: TreeNode,
    max_value_length: int,
    is_root: bool = False,
) -> Text:
    """Format a TreeNode as a Rich Text label."""
    label = Text()

    # Key
    key_style = "bold cyan" if is_root else "cyan"
    label.append(node.key, style=key_style)

    if node.is_leaf:
        # Show value for leaf nodes
        label.append(": ", style="dim")
        value_str = _format_value(node.value, node.node_type, max_value_length)
        label.append(value_str, style=TYPE_STYLES.get(node.node_type, "white"))
    else:
        # Show type indicator for branch nodes
        if node.node_type == "object":
            label.append(f" {{{node.child_count}}}", style="dim")
        elif node.node_type == "array":
            label.append(f" [{node.child_count}]", style="dim")

    return label


def _format_value(value: any, node_type: str, max_length: int) -> str:
    """Format a value for display."""
    if value is None:
        return "null"
    elif node_type == "string":
        s = f'"{value}"'
        if len(s) > max_length:
            return s[:max_length - 3] + '..."'
        return s
    elif node_type == "boolean":
        return str(value).lower()
    else:
        s = str(value)
        if len(s) > max_length:
            return s[:max_length - 3] + "..."
        return s


def _get_collapse_summary(node: TreeNode) -> str:
    """Get a summary string for a collapsed node."""
    if node.node_type == "object":
        return f"{{...{node.child_count} keys}}"
    elif node.node_type == "array":
        return f"[...{node.child_count} items]"
    else:
        return f"({node.child_count} children)"


def render_source_tui(
    content: str,
    filepath: str,
    console: Console,
    line_numbers: bool = True,
    theme: str = "monokai",
) -> None:
    """
    Render file content with syntax highlighting.

    Args:
        content: File content
        filepath: File path (for language detection)
        console: Rich Console instance
        line_numbers: Show line numbers
        theme: Syntax highlighting theme
    """
    # Detect language from extension
    ext = filepath.rsplit(".", 1)[-1].lower() if "." in filepath else ""
    lang_map = {
        "csv": "text",
        "tsv": "text",
        "json": "json",
        "yaml": "yaml",
        "yml": "yaml",
        "toml": "toml",
        "hcl": "hcl",
        "tf": "hcl",
        "tfvars": "hcl",
    }
    lang = lang_map.get(ext, ext or "text")

    syntax = Syntax(
        content,
        lang,
        theme=theme,
        line_numbers=line_numbers,
        word_wrap=True,
    )
    console.print(syntax)

    # Show controls
    controls = Text()
    controls.append("r", style="bold cyan")
    controls.append("=rendered ", style="dim")
    controls.append("q", style="bold cyan")
    controls.append("=quit", style="dim")
    console.print(controls)


class InteractiveTableViewer:
    """
    Interactive table viewer with pagination and view toggle.

    Usage:
        viewer = InteractiveTableViewer(data, console, filepath, content)
        viewer.run()
    """

    def __init__(
        self,
        data: TableData,
        console: Console,
        filepath: str,
        raw_content: str,
        page_size: int = 50,
    ):
        self.data = data
        self.console = console
        self.filepath = filepath
        self.raw_content = raw_content
        self.page_size = page_size
        self.current_page = 0
        self.view_mode = "rendered"  # 'rendered' or 'source'

    def run(self) -> None:
        """Run interactive viewer loop."""
        while True:
            self.console.clear()

            if self.view_mode == "rendered":
                info = render_table_tui(
                    self.data,
                    self.console,
                    page=self.current_page,
                    page_size=self.page_size,
                    show_controls=True,
                )
                total_pages = info["total_pages"]
            else:
                render_source_tui(self.raw_content, self.filepath, self.console)
                total_pages = 1

            # Get user input
            try:
                key = self.console.input("\n[dim]Command: [/dim]").strip().lower()
            except (KeyboardInterrupt, EOFError):
                break

            if key in ("q", "quit", "exit"):
                break
            elif key in ("n", "next") and self.view_mode == "rendered":
                self.current_page = min(self.current_page + 1, total_pages - 1)
            elif key in ("p", "prev", "previous") and self.view_mode == "rendered":
                self.current_page = max(self.current_page - 1, 0)
            elif key.startswith("g") and self.view_mode == "rendered":
                # Go to page
                try:
                    page_num = int(key[1:].strip() or "1") - 1
                    self.current_page = max(0, min(page_num, total_pages - 1))
                except ValueError:
                    pass
            elif key in ("s", "source"):
                self.view_mode = "source"
            elif key in ("r", "rendered"):
                self.view_mode = "rendered"


class InteractiveTreeViewer:
    """
    Interactive tree viewer with expand/collapse and view toggle.

    Usage:
        viewer = InteractiveTreeViewer(tree, console, filepath, content)
        viewer.run()
    """

    def __init__(
        self,
        tree: TreeNode,
        console: Console,
        filepath: str,
        raw_content: str,
        expand_depth: int = 2,
    ):
        self.tree = tree
        self.console = console
        self.filepath = filepath
        self.raw_content = raw_content
        self.expand_depth = expand_depth
        self.view_mode = "rendered"  # 'rendered' or 'source'

    def run(self) -> None:
        """Run interactive viewer loop."""
        while True:
            self.console.clear()

            if self.view_mode == "rendered":
                render_tree_tui(
                    self.tree,
                    self.console,
                    expand_depth=self.expand_depth,
                    show_controls=True,
                )
            else:
                render_source_tui(self.raw_content, self.filepath, self.console)

            # Get user input
            try:
                key = self.console.input("\n[dim]Command: [/dim]").strip().lower()
            except (KeyboardInterrupt, EOFError):
                break

            if key in ("q", "quit", "exit"):
                break
            elif key in ("e", "expand"):
                self.expand_depth = 100  # Expand all
            elif key in ("c", "collapse"):
                self.expand_depth = 1  # Collapse to top level
            elif key.isdigit():
                self.expand_depth = int(key)
            elif key in ("s", "source"):
                self.view_mode = "source"
            elif key in ("r", "rendered"):
                self.view_mode = "rendered"
