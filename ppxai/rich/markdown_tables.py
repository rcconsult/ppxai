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


def _extract_markdown_links(text: str) -> List[Tuple[int, int, str, str]]:
    """Find all [text](url) links using bracket/paren depth counting.

    Handles edge cases that defeat simple regex:
    - Nested brackets in link text: [API [v2]](url)
    - Parentheses in URLs:          [docs](https://example.com/func(v2))

    Returns:
        List of (start, end, link_text, url) tuples.
        start/end are byte offsets into text (end is exclusive).
    """
    results: List[Tuple[int, int, str, str]] = []
    i = 0
    n = len(text)
    while i < n:
        if text[i] != '[':
            i += 1
            continue

        # Scan for matching ']' counting bracket depth
        depth = 1
        j = i + 1
        while j < n and depth > 0:
            if text[j] == '[':
                depth += 1
            elif text[j] == ']':
                depth -= 1
            j += 1

        if depth != 0 or j >= n or text[j] != '(':
            i += 1
            continue

        # j points at '(' — scan for matching ')' counting paren depth
        url_start = j + 1
        depth = 1
        k = url_start
        while k < n and depth > 0:
            if text[k] == '(':
                depth += 1
            elif text[k] == ')':
                depth -= 1
            k += 1

        if depth != 0:
            i = j
            continue

        link_text = text[i + 1:j - 1]   # content between [ and ]
        url = text[url_start:k - 1]       # content between ( and )
        results.append((i, k, link_text, url))
        i = k

    return results


def convert_markdown_links_to_rich(content: str, working_dir: str = None) -> str:
    """
    Convert markdown links to Rich markup for clickable terminal links.

    Transforms [text](url) to [link=url]text[/link] format which Rich renders
    as clickable hyperlinks in terminals that support OSC 8 (iTerm2, Windows
    Terminal, GNOME Terminal 3.26+, etc.).

    For local file paths (relative or absolute), converts to file:// URIs
    so they're clickable in the terminal.

    Uses bracket/paren depth counting (not regex) to correctly handle:
    - Nested brackets in link text: [API [v2]](url)
    - Parentheses in URLs:          [docs](https://en.wikipedia.org/wiki/Foo_(bar))

    Args:
        content: Markdown content with links like [Source](https://example.com)
        working_dir: Working directory for resolving relative paths (defaults to cwd)

    Returns:
        Content with Rich-style clickable links

    Examples:
        >>> convert_markdown_links_to_rich("See [1](https://docs.python.org)")
        'See [link=https://docs.python.org][bold cyan]1[/bold cyan][/link]'

        >>> convert_markdown_links_to_rich("[Google](https://google.com) is popular")
        '[link=https://google.com][bold cyan]Google[/bold cyan][/link] is popular'

        >>> convert_markdown_links_to_rich("[README](./README.md)")  # Converts to file:// URI
        '[link=file:///path/to/README.md][bold cyan]README[/bold cyan][/link]'
    """
    import os
    from pathlib import Path

    if working_dir is None:
        working_dir = os.getcwd()

    links = _extract_markdown_links(content)
    if not links:
        return content

    parts: List[str] = []
    prev_end = 0
    for start, end, link_text, url in links:
        parts.append(content[prev_end:start])

        if url.startswith(('http://', 'https://', 'file://')):
            final_url = url
            display_text = link_text
        else:
            if url.startswith('./') or url.startswith('../') or not url.startswith('/'):
                abs_path = (Path(working_dir) / url).resolve()
            else:
                abs_path = Path(url)
            final_url = f"file://{abs_path}"
            if link_text == url or link_text.endswith(url) or url.endswith(link_text):
                display_text = abs_path.name
            else:
                display_text = link_text

        parts.append(f'[link={final_url}][bold cyan]{display_text}[/bold cyan][/link]')
        prev_end = end

    parts.append(content[prev_end:])
    return ''.join(parts)


def parse_inline_markdown(text: str) -> Text:
    """
    Parse inline markdown elements in text and return Rich Text with styling.

    Supports:
    - Inline code: `code`      → cyan monospace on grey background (highest priority)
    - Bold:        **text**    → bold style
    - Bold:        __text__    → bold style
    - Italic:      *text*      → italic style
    - Italic:      _text_      → italic style

    Uses a single linear pass with explicit priority ordering so that:
    - Code spans are never broken by bold/italic markers inside them
    - Adjacent spans like **a** **b** are both correctly formatted
    - Bold is recognised before italic (double marker beats single)

    Args:
        text: Text potentially containing inline markdown

    Returns:
        Rich Text object with appropriate styling
    """
    result = Text()
    pos = 0
    n = len(text)

    while pos < n:
        c = text[pos]

        # 1. Code span: `code`  (highest priority — consumes until next backtick)
        if c == '`':
            end = text.find('`', pos + 1)
            if end != -1:
                result.append(text[pos + 1:end], style="bold cyan on grey23")
                pos = end + 1
                continue

        # 2. Bold: **text** or __text__  (double marker — check before italic)
        if c in ('*', '_') and pos + 1 < n and text[pos + 1] == c:
            marker = c + c
            end = text.find(marker, pos + 2)
            if end != -1:
                result.append(text[pos + 2:end], style="bold")
                pos = end + 2
                continue

        # 3. Italic: *text* or _text_  (single marker not followed by same char)
        if c in ('*', '_'):
            end = text.find(c, pos + 1)
            # Require the closing char NOT to be immediately followed by the same
            # char (which would make it a bold opener, not an italic closer)
            if end != -1 and (end + 1 >= n or text[end + 1] != c):
                result.append(text[pos + 1:end], style="italic")
                pos = end + 1
                continue

        # No formatting — literal character
        result.append(c)
        pos += 1

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


def render_markdown_with_tables(
    content: str,
    console: Console,
    working_dir: str = None,
    normalize_emojis: bool = True,
) -> None:
    """
    Render markdown content with proper table and link support.

    This function:
    1. Normalizes emoji widths for consistent panel alignment
    2. Splits content into table and non-table blocks
    3. Renders tables using Rich Table objects
    4. Converts markdown links [text](url) to clickable Rich links
    5. Renders other markdown using Rich Markdown

    Clickable links work in terminals supporting OSC 8 hyperlinks:
    iTerm2, Windows Terminal, GNOME Terminal 3.26+, Kitty, etc.

    Args:
        content: Markdown content to render
        console: Rich Console instance
        working_dir: Working directory for resolving relative paths (defaults to cwd)
        normalize_emojis: Whether to normalize emoji widths for panel alignment
    """
    if not content.strip():
        return

    # Normalize emoji widths to prevent panel misalignment
    if normalize_emojis:
        from ppxai.rich.ui_components import sanitize_for_panel
        content = sanitize_for_panel(content)

    blocks = split_markdown_content(content)

    for block_type, block_content in blocks:
        if block_type == 'table':
            table = parse_markdown_table(block_content)
            console.print(table)
        else:
            if block_content.strip():
                # Check if content has any markdown links (web URLs or local files)
                has_links = _extract_markdown_links(block_content)

                if has_links:
                    # Convert markdown links to Rich clickable links, then render
                    # We use Rich markup directly for links since Markdown() strips link URLs
                    rich_content = convert_markdown_links_to_rich(block_content, working_dir)
                    console.print(rich_content)
                else:
                    # No links - use standard Markdown rendering
                    console.print(Markdown(block_content))
