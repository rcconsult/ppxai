"""
TUI and session configuration.
"""

import json
from typing import Any, Dict

from .loader import USER_CONFIG_FILE, find_config_file
from .store import ConfigStore


# =============================================================================
# TUI Configuration
# =============================================================================

def get_tui_config() -> Dict[str, Any]:
    """Get TUI-specific configuration."""
    defaults = {
        "theme": "standard",
        "show_version": True,
        "show_cwd": True,
        "show_datetime": False,
    }

    config = ConfigStore.get_instance().config
    tui_config = config.get("tui", {})

    return {**defaults, **tui_config}


def get_tui_theme() -> str:
    """Get the configured TUI theme name."""
    return get_tui_config().get("theme", "standard")


def set_tui_config(key: str, value: Any) -> bool:
    """Set a TUI configuration value and save to config file."""
    config_path = find_config_file()
    if config_path is None:
        config_path = USER_CONFIG_FILE
        config_path.parent.mkdir(parents=True, exist_ok=True)

    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8-sig") as f:
                config_data = json.load(f)
        except (json.JSONDecodeError, IOError):
            config_data = {}
    else:
        config_data = {}

    if "tui" not in config_data:
        config_data["tui"] = {}

    config_data["tui"][key] = value

    try:
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config_data, f, indent=2)

        # Update in-memory config
        store = ConfigStore.get_instance()
        current = store.config
        if "tui" not in current:
            current["tui"] = {}
        current["tui"][key] = value

        return True
    except IOError:
        return False


# =============================================================================
# Session Configuration
# =============================================================================

def get_session_config() -> Dict[str, Any]:
    """Get session-specific configuration."""
    defaults = {
        "auto_restore": "prompt",
        "auto_save_interval": 1,
    }

    config = ConfigStore.get_instance().config
    session_config = config.get("session", {})
    return {**defaults, **session_config}


def get_auto_restore_mode() -> str:
    """Get the auto-restore mode for sessions."""
    mode = get_session_config().get("auto_restore", "prompt")
    if mode not in ("always", "prompt", "never"):
        return "prompt"
    return mode


def get_auto_save_interval() -> int:
    """Get the auto-save interval (number of messages between saves)."""
    interval = get_session_config().get("auto_save_interval", 1)
    return max(0, int(interval))
