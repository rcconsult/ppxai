"""
Date and time tool with timezone support.
"""

from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..manager import ToolManager


def get_datetime(timezone: str = "UTC") -> str:
    """Get current date and time with timezone support.

    Args:
        timezone: IANA timezone name (e.g., 'Europe/Zurich', 'America/New_York')

    Returns:
        Formatted date/time string
    """
    try:
        try:
            import zoneinfo
            tz = zoneinfo.ZoneInfo(timezone)
        except Exception:
            # Fallback for older Python or invalid timezone
            try:
                import pytz
                tz = pytz.timezone(timezone)
            except Exception:
                return f"Error: Invalid timezone '{timezone}'. Use IANA format like 'Europe/Zurich', 'America/New_York', 'UTC'"

        now = datetime.now(tz)
        return (
            f"Current date and time in {timezone}:\n"
            f"  Date: {now.strftime('%A, %B %d, %Y')}\n"
            f"  Time: {now.strftime('%H:%M:%S')}\n"
            f"  ISO format: {now.isoformat()}\n"
            f"  Unix timestamp: {int(now.timestamp())}"
        )
    except Exception as e:
        return f"Error getting datetime: {str(e)}"


def register_tools(manager: 'ToolManager'):
    """Register datetime tools with the manager."""

    manager.register_function(
        name="get_datetime",
        description="Get the current date and time with timezone support. Use IANA timezone names like 'Europe/Zurich', 'America/New_York', 'Asia/Tokyo', 'UTC'",
        parameters={
            "type": "object",
            "properties": {
                "timezone": {
                    "type": "string",
                    "description": "IANA timezone name (default: 'UTC'). Examples: 'Europe/Zurich', 'America/New_York', 'Asia/Tokyo'"
                }
            },
            "required": []
        },
        handler=get_datetime
    )
