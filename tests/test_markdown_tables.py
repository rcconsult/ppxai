"""
Tests for markdown table parser.

Ensures tables are properly rendered in the TUI without regression.
"""

import pytest
from io import StringIO
from rich.console import Console
from ppxai.markdown_tables import (
    parse_table_alignment,
    parse_markdown_table,
    is_table_block,
    split_markdown_content,
    render_markdown_with_tables,
)


class TestTableAlignment:
    """Test table alignment parsing."""

    def test_left_alignment(self):
        """Test left-aligned columns."""
        alignment_row = "|---|---|---|"
        result = parse_table_alignment(alignment_row)
        assert result == ['left', 'left', 'left']

    def test_center_alignment(self):
        """Test center-aligned columns."""
        alignment_row = "|:---:|:---:|:---:|"
        result = parse_table_alignment(alignment_row)
        assert result == ['center', 'center', 'center']

    def test_right_alignment(self):
        """Test right-aligned columns."""
        alignment_row = "|---:|---:|---:|"
        result = parse_table_alignment(alignment_row)
        assert result == ['right', 'right', 'right']

    def test_mixed_alignment(self):
        """Test mixed alignment."""
        alignment_row = "|:---|:---:|---:|"
        result = parse_table_alignment(alignment_row)
        assert result == ['left', 'center', 'right']

    def test_alignment_with_spaces(self):
        """Test alignment with extra spaces."""
        alignment_row = "| :--- | :---: | ---: |"
        result = parse_table_alignment(alignment_row)
        assert result == ['left', 'center', 'right']


class TestTableParsing:
    """Test markdown table parsing."""

    def test_simple_table(self):
        """Test parsing a simple table."""
        table_md = """| Feature | Status |
|:---|:---|
| Tables | Working |
| Alignment | Working |"""

        table = parse_markdown_table(table_md)
        assert table is not None
        assert len(table.columns) == 2

    def test_table_with_alignment(self):
        """Test table with different alignments."""
        table_md = """| Left | Center | Right |
|:---|:---:|---:|
| A | B | C |
| D | E | F |"""

        table = parse_markdown_table(table_md)
        assert table is not None
        assert len(table.columns) == 3
        # Check column alignment
        assert table.columns[0].justify == 'left'
        assert table.columns[1].justify == 'center'
        assert table.columns[2].justify == 'right'

    def test_table_with_emojis(self):
        """Test table containing emojis."""
        table_md = """| Status | Symbol |
|:---|:---:|
| Success | ✅ |
| Failed | ❌ |
| Pending | ⏳ |"""

        table = parse_markdown_table(table_md)
        assert table is not None
        assert len(table.columns) == 2

    def test_table_with_code(self):
        """Test table containing inline code."""
        table_md = """| Command | Description |
|:---|:---|
| `/help` | Show help |
| `/quit` | Exit app |"""

        table = parse_markdown_table(table_md)
        assert table is not None

    def test_table_without_alignment_row(self):
        """Test table without explicit alignment row."""
        table_md = """| Name | Value |
| Alice | 100 |
| Bob | 200 |"""

        table = parse_markdown_table(table_md)
        assert table is not None
        assert len(table.columns) == 2
        # Should default to left alignment
        assert table.columns[0].justify == 'left'
        assert table.columns[1].justify == 'left'

    def test_empty_cells(self):
        """Test table with empty cells."""
        table_md = """| A | B | C |
|---|---|---|
| 1 | | 3 |
| | 2 | |"""

        table = parse_markdown_table(table_md)
        assert table is not None

    def test_uneven_columns(self):
        """Test table with uneven column counts (should handle gracefully)."""
        table_md = """| A | B | C |
|---|---|---|
| 1 | 2 |
| X | Y | Z | Extra |"""

        table = parse_markdown_table(table_md)
        assert table is not None


class TestTableDetection:
    """Test markdown table block detection."""

    def test_is_table_block_positive(self):
        """Test detection of valid table blocks."""
        table = """| Feature | Status |
|:---|:---|
| Tables | Working |"""
        assert is_table_block(table) is True

    def test_is_table_block_negative(self):
        """Test detection of non-table blocks."""
        assert is_table_block("This is just text") is False
        assert is_table_block("# Heading") is False
        assert is_table_block("") is False
        assert is_table_block("   ") is False

    def test_is_table_block_single_line(self):
        """Test single-line table (should be False)."""
        assert is_table_block("| A | B | C |") is False

    def test_is_table_block_with_leading_text(self):
        """Test table with leading text (should be False)."""
        text = "Some text before | A | B |"
        assert is_table_block(text) is False


class TestContentSplitting:
    """Test splitting markdown content into table and non-table blocks."""

    def test_split_table_only(self):
        """Test content with only a table."""
        content = """| Feature | Status |
|:---|:---|
| Tables | Working |"""

        blocks = split_markdown_content(content)
        assert len(blocks) == 1
        assert blocks[0][0] == 'table'

    def test_split_markdown_only(self):
        """Test content with only markdown (no tables)."""
        content = """# Heading

This is a paragraph with **bold** and *italic* text."""

        blocks = split_markdown_content(content)
        assert len(blocks) == 1
        assert blocks[0][0] == 'markdown'

    def test_split_mixed_content(self):
        """Test content with both tables and markdown."""
        content = """# Feature Comparison

Here's a comparison table:

| Feature | Status |
|:---|:---|
| Tables | Working |
| Code | Working |

And here's more text after the table."""

        blocks = split_markdown_content(content)
        # Should have: markdown, table, markdown
        assert len(blocks) >= 3

        # Find table block
        table_blocks = [b for b in blocks if b[0] == 'table']
        assert len(table_blocks) == 1

    def test_split_multiple_tables(self):
        """Test content with multiple tables."""
        content = """## First Table

| A | B |
|---|---|
| 1 | 2 |

## Second Table

| X | Y |
|---|---|
| 3 | 4 |"""

        blocks = split_markdown_content(content)
        table_blocks = [b for b in blocks if b[0] == 'table']
        assert len(table_blocks) == 2


class TestRenderingIntegration:
    """Test the full rendering pipeline."""

    def test_render_table_only(self):
        """Test rendering content with only a table."""
        content = """| Feature | Status |
|:---|:---|
| Tables | ✅ Working |
| Tests | ✅ Passing |"""

        # Capture output
        string_io = StringIO()
        console = Console(file=string_io, force_terminal=True, width=80)

        render_markdown_with_tables(content, console)

        output = string_io.getvalue()
        # Should not contain raw markdown table syntax
        assert '|:---|:---|' not in output

    def test_render_mixed_content(self):
        """Test rendering mixed table and markdown content."""
        content = """# Test Report

Here are the results:

| Test | Result |
|:---|:---:|
| Unit Tests | ✅ |
| Integration | ✅ |

All tests passed!"""

        string_io = StringIO()
        console = Console(file=string_io, force_terminal=True, width=80)

        render_markdown_with_tables(content, console)

        output = string_io.getvalue()
        # Should contain the heading (markdown rendering)
        assert 'Test Report' in output
        # Should not show raw table separators
        assert '|:---|:---:|' not in output

    def test_render_empty_content(self):
        """Test rendering empty content (should not crash)."""
        string_io = StringIO()
        console = Console(file=string_io, force_terminal=True, width=80)

        render_markdown_with_tables("", console)
        render_markdown_with_tables("   ", console)

        # Should not raise any exceptions

    def test_render_complex_table(self):
        """Test rendering a complex table from the bug screenshot."""
        content = """## Competitive Response to Gemini 3 & Claude Code

**Gemini 3.0** (late 2025) emphasizes "agentic" capabilities:
- **Tool orchestration**: Browser interaction, code execution, API calls
- **Agent-first architecture**: Moves from Q&A to "ambient AI"

| Gemini 3 Capability | Claude Code | ppxai Response |
|:---|:---|:---|
| **Multi-step autonomy** | ✅ Autonomous (72.7% SWE-bench) | ✅ v1.11.0: `/agent` loop |
| **Tool orchestration** | ✅ Native | ✅ v1.11.0: `edit_file` tool |
| **Code review workflows** | ⚠️ Manual | ✅ v1.11.0: `@git` context |

**ppxai's Roadmap Response**: Multi-provider agentic workflows."""

        string_io = StringIO()
        console = Console(file=string_io, force_terminal=True, width=120)

        render_markdown_with_tables(content, console)

        output = string_io.getvalue()
        # Should render without raw markdown table syntax
        assert '|:---|:---|:---|' not in output
        # Should contain content
        assert 'Gemini 3 Capability' in output or 'Competitive Response' in output


class TestRegressionPrevention:
    """Tests specifically designed to prevent regression of the table rendering bug."""

    def test_table_bug_from_screenshot(self):
        """
        Test the exact scenario from tui-md-render-bug.png.

        This ensures the bug doesn't regress.
        """
        # This is the type of table that was showing as raw markdown
        content = """| Feature | Status |
|:---|:---|
| Multi-step autonomy | ✅ Autonomous |
| Tool orchestration | ✅ Native |"""

        string_io = StringIO()
        console = Console(file=string_io, force_terminal=True, width=80)

        render_markdown_with_tables(content, console)

        output = string_io.getvalue()

        # The bug was showing "|:---|:---|" in output
        # This should NOT appear anymore
        assert '|:---|:---|' not in output, "Table alignment markers should not appear in rendered output"

        # The content should be present (table was rendered, not broken)
        assert 'Multi-step autonomy' in output
        # Note: ✅ is converted to '*' for consistent panel alignment
        assert 'Autonomous' in output
        assert 'Tool orchestration' in output

    def test_no_markdown_class_for_tables(self):
        """Ensure tables are NOT rendered via rich.markdown.Markdown."""
        # This test verifies our architectural fix
        table_content = """| A | B |
|---|---|
| 1 | 2 |"""

        blocks = split_markdown_content(table_content)
        assert len(blocks) == 1
        assert blocks[0][0] == 'table', "Table content should be identified as 'table', not 'markdown'"

    def test_multiple_tables_no_crosstalk(self):
        """Ensure multiple tables don't interfere with each other."""
        content = """## Table 1

| A | B |
|:---|---:|
| Left | Right |

## Table 2

| X | Y | Z |
|:---:|:---:|:---:|
| Center | Center | Center |"""

        string_io = StringIO()
        console = Console(file=string_io, force_terminal=True, width=80)

        render_markdown_with_tables(content, console)

        output = string_io.getvalue()
        # Should not show alignment markers from either table
        assert '|:---|---:|' not in output
        assert '|:---:|:---:|:---:|' not in output


class TestLinkConversion:
    """Test markdown link to Rich clickable link conversion (OSC 8)."""

    def test_convert_single_link(self):
        """Test converting a single markdown link."""
        from ppxai.markdown_tables import convert_markdown_links_to_rich

        text = "See [1](https://docs.python.org) for details."
        result = convert_markdown_links_to_rich(text)

        assert "[link=https://docs.python.org]" in result
        assert "[bold cyan]1[/bold cyan]" in result
        assert "[/link]" in result

    def test_convert_multiple_links(self):
        """Test converting multiple markdown links."""
        from ppxai.markdown_tables import convert_markdown_links_to_rich

        text = "Check [Google](https://google.com) and [Python](https://python.org)."
        result = convert_markdown_links_to_rich(text)

        assert "[link=https://google.com]" in result
        assert "[bold cyan]Google[/bold cyan]" in result
        assert "[link=https://python.org]" in result
        assert "[bold cyan]Python[/bold cyan]" in result

    def test_no_links_unchanged(self):
        """Test that text without links is unchanged."""
        from ppxai.markdown_tables import convert_markdown_links_to_rich

        text = "This is plain text without any links."
        result = convert_markdown_links_to_rich(text)

        assert result == text

    def test_http_and_https_links(self):
        """Test both HTTP and HTTPS links are converted."""
        from ppxai.markdown_tables import convert_markdown_links_to_rich

        text = "[Secure](https://example.com) and [Insecure](http://example.org)"
        result = convert_markdown_links_to_rich(text)

        assert "[link=https://example.com]" in result
        assert "[link=http://example.org]" in result

    def test_links_with_special_chars(self):
        """Test links with special characters in URL."""
        from ppxai.markdown_tables import convert_markdown_links_to_rich

        text = "[Search](https://google.com/search?q=python&lang=en)"
        result = convert_markdown_links_to_rich(text)

        assert "[link=https://google.com/search?q=python&lang=en]" in result

    def test_citation_style_links(self):
        """Test citation-style links like [1], [2], etc."""
        from ppxai.markdown_tables import convert_markdown_links_to_rich

        text = "This is explained in [1](https://source1.com), [2](https://source2.com), and [3](https://source3.com)."
        result = convert_markdown_links_to_rich(text)

        assert result.count("[link=") == 3
        assert "[bold cyan]1[/bold cyan]" in result
        assert "[bold cyan]2[/bold cyan]" in result
        assert "[bold cyan]3[/bold cyan]" in result

    def test_render_with_links_produces_osc8(self):
        """Test that rendering produces OSC 8 hyperlink escape codes."""
        string_io = StringIO()
        console = Console(file=string_io, force_terminal=True, width=80)

        content = "Here is a citation [1](https://example.com)."
        render_markdown_with_tables(content, console)

        output = string_io.getvalue()

        # OSC 8 hyperlink format: \x1b]8;id=...;URL\x1b\\TEXT\x1b]8;;\x1b\\
        assert '\x1b]8;' in output, "OSC 8 escape sequence should be present"
        assert 'https://example.com' in output
        assert '1' in output  # The link text

    def test_links_in_mixed_content(self):
        """Test links mixed with other markdown content."""
        string_io = StringIO()
        console = Console(file=string_io, force_terminal=True, width=80)

        content = """## References

Check out [Python Docs](https://docs.python.org) for more information.

| Source | URL |
|---|---|
| Python | python.org |

See also [1](https://example.com) and [2](https://example.org)."""

        render_markdown_with_tables(content, console)

        output = string_io.getvalue()
        # Should have rendered the links (OSC 8 codes present)
        assert '\x1b]8;' in output
        # Should not show raw table syntax
        assert '|---|---|' not in output


class TestEmojiConversion:
    """Test emoji to text symbol conversion for panel alignment."""

    def test_warning_emoji_converted(self):
        """Test warning emoji is converted to '!'."""
        from ppxai.ui_components import emojis_to_text_symbols

        assert emojis_to_text_symbols("⚠️ Warning") == "! Warning"
        assert emojis_to_text_symbols("⚠ Note") == "! Note"

    def test_success_emoji_converted(self):
        """Test checkmark emoji is converted to '*'."""
        from ppxai.ui_components import emojis_to_text_symbols

        assert emojis_to_text_symbols("✅ Done") == "* Done"
        assert emojis_to_text_symbols("✓ OK") == "* OK"

    def test_error_emoji_converted(self):
        """Test error emoji is converted to 'X'."""
        from ppxai.ui_components import emojis_to_text_symbols

        assert emojis_to_text_symbols("❌ Failed") == "X Failed"

    def test_multiple_emojis_converted(self):
        """Test multiple emojis in one string."""
        from ppxai.ui_components import emojis_to_text_symbols

        text = "✅ Step 1\n⚠️ Step 2\n❌ Step 3"
        result = emojis_to_text_symbols(text)
        assert result == "* Step 1\n! Step 2\nX Step 3"

    def test_no_emojis_unchanged(self):
        """Test text without emojis is unchanged."""
        from ppxai.ui_components import emojis_to_text_symbols

        text = "Plain text without emojis"
        assert emojis_to_text_symbols(text) == text

    def test_sanitize_for_panel_uses_text_symbols(self):
        """Test sanitize_for_panel converts emojis by default."""
        from ppxai.ui_components import sanitize_for_panel

        text = "⚠️ Warning: ✅ check, ❌ fail"
        result = sanitize_for_panel(text)
        assert "⚠️" not in result
        assert "✅" not in result
        assert "❌" not in result
        assert "!" in result  # warning converted
        assert "*" in result  # success converted
        assert "X" in result  # error converted

    def test_tables_with_emojis_aligned(self):
        """Test that tables with emojis render with consistent alignment."""
        string_io = StringIO()
        console = Console(file=string_io, force_terminal=True, width=80)

        content = """| Status | Description |
|--------|-------------|
| ✅ | Success |
| ⚠️ | Warning |
| ❌ | Error |"""

        render_markdown_with_tables(content, console)
        output = string_io.getvalue()

        # Emojis should be converted to text symbols
        # The exact characters depend on the mapping
        assert "Success" in output
        assert "Warning" in output
        assert "Error" in output
