"""
Markdown table parser for Rich TUI.

This module provides utilities to parse markdown tables and convert them
to Rich Table objects for proper rendering in the terminal.
"""

import re
from typing import List, Tuple
from rich.table import Table
from rich.markdown import Markdown
from rich.console import Console, RenderableType


def parse_table_alignment(alignment_row: str) -> List[str]:
    """
    Parse table alignment markers.

    Args:
        alignment_row: The alignment row (e.g., "|:---|:---:|---:|")

    Returns:
        List of alignment strings: "left", "center", or "right"
    """
    cells = [cell.strip() for cell in alignment_row.split('|')[1:-1]]
    alignments = []

    for cell in cells:
        if cell.startswith(':') and cell.endswith(':'):
            alignments.append('center')
        elif cell.endswith(':'):
            alignments.append('right')
        else:
            alignments.append('left')

    return alignments


def parse_markdown_table(table_str: str) -> Table:
    """
    Convert markdown table string to Rich Table.

    Args:
        table_str: Markdown table as string

    Returns:
        Rich Table object
    """
    lines = [line.strip() for line in table_str.strip().split('\n') if line.strip()]

    if not lines:
        return Table()

    # Parse header row
    header_cells = [cell.strip() for cell in lines[0].split('|')[1:-1]]

    # Check for alignment row
    alignments = []
    data_start = 1

    if len(lines) > 1 and re.match(r'^[\|\s:-]+$', lines[1]):
        alignments = parse_table_alignment(lines[1])
        data_start = 2
    else:
        alignments = ['left'] * len(header_cells)

    # Create Rich table
    table = Table(show_header=True, header_style="bold cyan", border_style="dim")

    # Add columns with alignment
    for i, header in enumerate(header_cells):
        justify = alignments[i] if i < len(alignments) else 'left'
        table.add_column(header, justify=justify)

    # Add data rows
    for line in lines[data_start:]:
        if line.strip():
            cells = [cell.strip() for cell in line.split('|')[1:-1]]
            # Pad cells if needed to match column count
            while len(cells) < len(header_cells):
                cells.append("")
            table.add_row(*cells[:len(header_cells)])

    return table


def is_table_block(text: str) -> bool:
    """
    Check if a text block is a markdown table.

    Args:
        text: Text to check

    Returns:
        True if text appears to be a markdown table
    """
    text = text.strip()
    if not text:
        return False

    lines = text.split('\n')
    # Must have at least 2 lines (header + alignment or header + data)
    if len(lines) < 2:
        return False

    # First line must start with |
    if not lines[0].strip().startswith('|'):
        return False

    # Check if it looks like a table (has | characters)
    return '|' in lines[0]


def split_markdown_content(content: str) -> List[Tuple[str, str]]:
    """
    Split markdown content into table and non-table blocks.

    Args:
        content: Full markdown content

    Returns:
        List of (block_type, content) tuples where block_type is 'table' or 'markdown'
    """
    # Pattern to match markdown tables
    # Matches: line starting with |, followed by optional alignment row, followed by data rows
    # Made trailing \n optional to handle last line without newline
    table_pattern = r'(\|[^\n]+\|(?:\n|$)(?:\|[-:|\s]+\|(?:\n|$))?(?:\|[^\n]+\|(?:\n|$))*)'

    parts = re.split(table_pattern, content, flags=re.MULTILINE)

    blocks = []
    for part in parts:
        if not part or not part.strip():
            continue

        if is_table_block(part):
            blocks.append(('table', part))
        else:
            blocks.append(('markdown', part))

    return blocks


def render_markdown_with_tables(content: str, console: Console) -> None:
    """
    Render markdown content with proper table support.

    This function splits markdown content into table and non-table blocks,
    rendering tables using Rich Table and other content using Rich Markdown.

    Args:
        content: Markdown content to render
        console: Rich Console instance
    """
    if not content.strip():
        return

    blocks = split_markdown_content(content)

    for block_type, block_content in blocks:
        if block_type == 'table':
            table = parse_markdown_table(block_content)
            console.print(table)
        else:
            if block_content.strip():
                console.print(Markdown(block_content))
