"""
Date and time tool with timezone support.
"""

from datetime import datetime
from typing import TYPE_CHECKING
import time

if TYPE_CHECKING:
    from ..manager import ToolManager


def get_system_timezone() -> str:
    """Detect the system's local timezone.

    Returns:
        IANA timezone name or UTC offset string
    """
    try:
        # Python 3.9+ approach using astimezone
        local_tz = datetime.now().astimezone().tzinfo
        if local_tz is not None:
            tz_name = str(local_tz)
            # Check if it's already an IANA name
            if '/' in tz_name or tz_name in ('UTC', 'GMT'):
                return tz_name
    except Exception:
        pass

    try:
        # Try tzlocal library if available
        from tzlocal import get_localzone
        local_tz = get_localzone()
        return str(local_tz)
    except ImportError:
        pass
    except Exception:
        pass

    try:
        # Fallback: construct offset string from time module
        if time.daylight and time.localtime().tm_isdst:
            offset_seconds = -time.altzone
        else:
            offset_seconds = -time.timezone
        hours, remainder = divmod(abs(offset_seconds), 3600)
        minutes = remainder // 60
        sign = '+' if offset_seconds >= 0 else '-'
        return f"UTC{sign}{hours:02d}:{minutes:02d}"
    except Exception:
        return "UTC"


def get_datetime(timezone: str = "") -> str:
    """Get current date and time with timezone support.

    Args:
        timezone: IANA timezone name (e.g., 'Europe/Zurich', 'America/New_York').
                  If empty, auto-detects system timezone.

    Returns:
        Formatted date/time string
    """
    try:
        # Auto-detect system timezone if not specified
        if not timezone:
            timezone = get_system_timezone()
            auto_detected = True
        else:
            auto_detected = False

        # Handle UTC offset format (e.g., "UTC+01:00")
        if timezone.startswith("UTC") and ('+' in timezone or '-' in timezone[3:]):
            # Use local time with the detected offset
            now = datetime.now().astimezone()
            tz_display = timezone
        else:
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
            tz_display = timezone

        tz_note = " (auto-detected)" if auto_detected else ""
        return (
            f"Current date and time in {tz_display}{tz_note}:\n"
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
                    "description": "IANA timezone name. IMPORTANT: If user asks for 'local time' or doesn't specify a timezone, call this tool WITHOUT passing timezone parameter to auto-detect the system's local timezone. Examples: 'Europe/Zurich', 'America/New_York', 'Asia/Tokyo', 'UTC'"
                }
            },
            "required": []
        },
        handler=get_datetime
    )
