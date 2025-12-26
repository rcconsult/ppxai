"""
Markdown table parser and link converter for Rich TUI.

This module provides utilities to:
- Parse markdown tables and convert them to Rich Table objects
- Convert markdown links to Rich clickable terminal links (OSC 8)
- Handle inline markdown formatting (bold, italic, code)

For proper rendering in the terminal with clickable citations.
"""

import re
from typing import List, Tuple, Union
from rich.table import Table
from rich.markdown import Markdown
from rich.console import Console, RenderableType
from rich.text import Text


def convert_markdown_links_to_rich(content: str) -> str:
    """
    Convert markdown links to Rich markup for clickable terminal links.

    Transforms [text](url) to [link=url]text[/link] format which Rich renders
    as clickable hyperlinks in terminals that support OSC 8 (iTerm2, Windows
    Terminal, GNOME Terminal 3.26+, etc.).

    Args:
        content: Markdown content with links like [Source](https://example.com)

    Returns:
        Content with Rich-style clickable links

    Examples:
        >>> convert_markdown_links_to_rich("See [1](https://docs.python.org)")
        'See [link=https://docs.python.org][bold cyan]1[/bold cyan][/link]'

        >>> convert_markdown_links_to_rich("[Google](https://google.com) is popular")
        '[link=https://google.com][bold cyan]Google[/bold cyan][/link] is popular'
    """
    # Pattern to match markdown links: [text](url)
    # Match text that doesn't contain ] and url that doesn't contain )
    link_pattern = r'\[([^\]]+)\]\(([^)]+)\)'

    def replace_link(match):
        text = match.group(1)
        url = match.group(2)
        # Use bold cyan style for visibility + link for clickability
        return f'[link={url}][bold cyan]{text}[/bold cyan][/link]'

    return re.sub(link_pattern, replace_link, content)


def parse_inline_markdown(text: str) -> Text:
    """
    Parse inline markdown elements in text and return Rich Text with styling.

    Currently supports:
    - Inline code: `code` -> cyan monospace on grey background
    - Bold: **text** or __text__ -> bold style
    - Italic: *text* or _text_ -> italic style

    Note: Standard markdown does not support underline. Use bold or italic instead.

    Args:
        text: Text potentially containing inline markdown

    Returns:
        Rich Text object with appropriate styling
    """
    result = Text()
    pos = 0

    # Pattern to match inline code (backticks), bold, and italic
    # Order matters: longer patterns first to avoid partial matches
    # Use non-greedy matching (.+?) to handle nested or adjacent formatting
    inline_pattern = r'(`[^`]+`)|(\*\*(.+?)\*\*)|(__(.+?)__)|(\*([^*]+?)\*)|(_([^_]+?)_)'

    for match in re.finditer(inline_pattern, text):
        # Add text before match
        if match.start() > pos:
            result.append(text[pos:match.start()])

        matched_text = match.group(0)

        if matched_text.startswith('`') and matched_text.endswith('`'):
            # Inline code
            code_text = matched_text[1:-1]  # Remove backticks
            result.append(code_text, style="bold cyan on grey23")
        elif matched_text.startswith('**'):
            # Bold (double asterisk)
            bold_text = matched_text[2:-2]
            result.append(bold_text, style="bold")
        elif matched_text.startswith('__'):
            # Bold (double underscore)
            bold_text = matched_text[2:-2]
            result.append(bold_text, style="bold")
        elif matched_text.startswith('*'):
            # Italic (single asterisk)
            italic_text = matched_text[1:-1]
            result.append(italic_text, style="italic")
        elif matched_text.startswith('_'):
            # Italic (single underscore)
            italic_text = matched_text[1:-1]
            result.append(italic_text, style="italic")

        pos = match.end()

    # Add remaining text
    if pos < len(text):
        result.append(text[pos:])

    return result


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
        # Parse inline markdown in headers too (convert to plain string for column names)
        # Rich Table column headers need plain strings, not Text objects
        table.add_column(header, justify=justify)

    # Add data rows
    for line in lines[data_start:]:
        if line.strip():
            cells = [cell.strip() for cell in line.split('|')[1:-1]]
            # Pad cells if needed to match column count
            while len(cells) < len(header_cells):
                cells.append("")
            # Parse inline markdown in each cell
            parsed_cells = [parse_inline_markdown(cell) for cell in cells[:len(header_cells)]]
            table.add_row(*parsed_cells)

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
    Render markdown content with proper table and link support.

    This function:
    1. Splits content into table and non-table blocks
    2. Renders tables using Rich Table objects
    3. Converts markdown links [text](url) to clickable Rich links
    4. Renders other markdown using Rich Markdown

    Clickable links work in terminals supporting OSC 8 hyperlinks:
    iTerm2, Windows Terminal, GNOME Terminal 3.26+, Kitty, etc.

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
                # Check if content has markdown links that should be clickable
                # Pattern: [text](url) - note: also matches [text](relative) but we only make http(s) clickable
                has_links = re.search(r'\[[^\]]+\]\(https?://[^)]+\)', block_content)

                if has_links:
                    # Convert markdown links to Rich clickable links, then render
                    # We use Rich markup directly for links since Markdown() strips link URLs
                    rich_content = convert_markdown_links_to_rich(block_content)
                    console.print(rich_content)
                else:
                    # No links - use standard Markdown rendering
                    console.print(Markdown(block_content))
