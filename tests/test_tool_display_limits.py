"""Tests for configurable tool result display limits (v1.15.3)."""

import pytest
from ppxai.engine.tools.manager import ToolManager


class TestToolDisplayLimits:
    """Test configurable, format-aware display limits for tool results."""

    def test_default_display_limit(self):
        """Test default limit for tools without specific configuration."""
        manager = ToolManager()
        limit = manager.get_tool_display_limit("unknown_tool")
        assert limit == 2000  # Default

    def test_weather_tool_short_format(self):
        """Test weather tool with short format gets smaller limit."""
        manager = ToolManager()
        limit = manager.get_tool_display_limit("get_weather", {"format": "short"})
        assert limit == 500

    def test_weather_tool_detailed_format(self):
        """Test weather tool with detailed format gets medium limit."""
        manager = ToolManager()
        limit = manager.get_tool_display_limit("get_weather", {"format": "detailed"})
        assert limit == 1500

    def test_weather_tool_forecast_format(self):
        """Test weather tool with forecast format gets large limit."""
        manager = ToolManager()
        limit = manager.get_tool_display_limit("get_weather", {"format": "forecast"})
        assert limit == 5000

    def test_weather_tool_default_format(self):
        """Test weather tool without format parameter uses default."""
        manager = ToolManager()
        # No format specified
        limit = manager.get_tool_display_limit("get_weather", {})
        assert limit == 2000  # Falls back to default

        # Format not in config
        limit = manager.get_tool_display_limit("get_weather", {"format": "unknown"})
        assert limit == 2000  # Falls back to default

    def test_weather_tool_no_args(self):
        """Test weather tool with no args dict uses default."""
        manager = ToolManager()
        limit = manager.get_tool_display_limit("get_weather", None)
        assert limit == 2000  # Falls back to default

    def test_fetch_url_limit(self):
        """Test fetch_url has higher limit for web pages."""
        manager = ToolManager()
        limit = manager.get_tool_display_limit("fetch_url")
        assert limit == 5000

    def test_web_search_limit(self):
        """Test web_search has higher limit for multiple results."""
        manager = ToolManager()
        limit = manager.get_tool_display_limit("web_search")
        assert limit == 3000

    def test_list_directory_limit(self):
        """Test list_directory has higher limit for large dirs."""
        manager = ToolManager()
        limit = manager.get_tool_display_limit("list_directory")
        assert limit == 3000

    def test_read_file_limit(self):
        """Test read_file has highest limit for code files."""
        manager = ToolManager()
        limit = manager.get_tool_display_limit("read_file")
        assert limit == 10000

    def test_custom_limits_configuration(self):
        """Test that custom limits can be configured on manager instance."""
        manager = ToolManager()

        # Override default limit
        manager.default_display_limit = 3000
        limit = manager.get_tool_display_limit("unknown_tool")
        assert limit == 3000

        # Override tool-specific limit
        manager.tool_display_limits["custom_tool"] = 7500
        limit = manager.get_tool_display_limit("custom_tool")
        assert limit == 7500

        # Override weather format limit
        manager.tool_display_limits["get_weather"]["short"] = 1000
        limit = manager.get_tool_display_limit("get_weather", {"format": "short"})
        assert limit == 1000
