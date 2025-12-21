"""
Tests for ppxai UI functions.

Tests UI display functions including help displays and markdown rendering.
"""

import pytest
from unittest.mock import patch, MagicMock
from ppxai.ui import display_file_editing_help


class TestFileEditingHelp:
    """Test display_file_editing_help function."""

    @patch('ppxai.ui.console')
    @patch('ppxai.ui.Panel')
    @patch('ppxai.ui.Markdown')
    def test_display_file_editing_help_called(self, mock_markdown, mock_panel, mock_console):
        """Test that display_file_editing_help renders help content."""
        display_file_editing_help()

        # Should create Markdown object
        assert mock_markdown.call_count == 1

        # Should create Panel with Markdown
        assert mock_panel.call_count == 1

        # Should print the panel
        assert mock_console.print.call_count == 1

    @patch('ppxai.ui.console')
    @patch('ppxai.ui.Panel')
    @patch('ppxai.ui.Markdown')
    def test_display_file_editing_help_content(self, mock_markdown, mock_panel, mock_console):
        """Test that help content includes key sections."""
        display_file_editing_help()

        # Get the markdown content passed to Markdown()
        help_content = mock_markdown.call_args[0][0]

        # Should include key sections
        assert "File Editing Tools Guide" in help_content
        assert "Overview" in help_content
        assert "Quick Start" in help_content
        assert "Consent System" in help_content
        assert "Available Tools" in help_content
        assert "apply_patch" in help_content
        assert "replace_block" in help_content
        assert "insert_text" in help_content
        assert "delete_lines" in help_content
        assert "Pro Tips" in help_content or "Practical Examples" in help_content
        assert "Safety Features" in help_content
        assert "Troubleshooting" in help_content
        assert "Commands" in help_content  # Section header is "Commands" not "Commands Reference"

    @patch('ppxai.ui.console')
    @patch('ppxai.ui.Panel')
    @patch('ppxai.ui.Markdown')
    def test_display_file_editing_help_consent_options(self, mock_markdown, mock_panel, mock_console):
        """Test that help includes all consent options."""
        display_file_editing_help()

        help_content = mock_markdown.call_args[0][0]

        # Should include all consent options
        assert "y/n/always/never" in help_content
        assert "y (yes)" in help_content or "**y**" in help_content
        assert "n (no)" in help_content or "**n**" in help_content
        assert "always" in help_content
        assert "never" in help_content

    @patch('ppxai.ui.console')
    @patch('ppxai.ui.Panel')
    @patch('ppxai.ui.Markdown')
    def test_display_file_editing_help_panel_styling(self, mock_markdown, mock_panel, mock_console):
        """Test that Panel is created with correct styling."""
        display_file_editing_help()

        # Check Panel was created with correct parameters
        panel_call = mock_panel.call_args
        assert panel_call is not None

        # Should have title, border_style, and padding
        kwargs = panel_call[1]
        assert 'title' in kwargs
        assert 'File Editing Tools' in kwargs['title'] or 'Interactive Guide' in kwargs['title']
        assert kwargs.get('border_style') == 'green'
        assert kwargs.get('padding') == (1, 2)

    @patch('ppxai.ui.console')
    @patch('ppxai.ui.Panel')
    @patch('ppxai.ui.Markdown')
    def test_display_file_editing_help_examples(self, mock_markdown, mock_panel, mock_console):
        """Test that help includes practical examples."""
        display_file_editing_help()

        help_content = mock_markdown.call_args[0][0]

        # Should include example usage
        assert "Example" in help_content or "example" in help_content.lower()

        # Should mention /tools commands
        assert "/tools enable" in help_content or "`/tools enable`" in help_content
        assert "/tools status" in help_content or "`/tools status`" in help_content
