"""
Paths, data directory, and server configuration.
"""

import platform
import sys
from pathlib import Path
from typing import Any, Dict, List

from .store import ConfigStore


def _expand_path_template(template: str) -> str:
    """Expand path template variables."""
    return template.replace("{home}", str(Path.home())).replace("{platform}", platform.system().lower())


def get_paths_config() -> Dict[str, Any]:
    """Get paths configuration for binary and data locations."""
    defaults = {
        "bin_search_paths": [
            "{home}/.ppxai/bin",
            "{home}/.local/bin",
            "{home}/bin",
            "/usr/local/bin",
            "{home}/AppData/Local/ppxai",
        ],
        "data_dir": "{home}/.ppxai",
    }

    config = ConfigStore.get_instance().config
    paths_config = config.get("paths", {})
    merged = {**defaults, **paths_config}

    result = {}
    for key, value in merged.items():
        if isinstance(value, list):
            result[key] = [_expand_path_template(p) for p in value]
        elif isinstance(value, str):
            result[key] = _expand_path_template(value)
        else:
            result[key] = value

    return result


def get_bin_search_paths() -> List[str]:
    """Get list of directories to search for ppxai binaries (platform-aware).

    Returns only paths relevant to the current platform:
    - Windows: Excludes Unix system paths (/usr/*)
    - Unix/macOS/Linux: Excludes Windows AppData paths
    """
    all_paths = get_paths_config().get("bin_search_paths", [])

    # Filter platform-specific paths for efficiency
    if sys.platform == 'win32':
        # Windows: Skip Unix system paths
        return [p for p in all_paths if not p.startswith('/usr')]
    else:
        # Unix/macOS/Linux: Skip Windows AppData
        return [p for p in all_paths if 'AppData' not in p]


def get_data_dir() -> Path:
    """Get the data directory for sessions, exports, etc."""
    return Path(get_paths_config().get("data_dir", str(Path.home() / ".ppxai")))


def get_server_config() -> Dict[str, Any]:
    """Get server-specific configuration."""
    defaults = {
        "idle_timeout": 300,
        "port": 54320,
        "working_dir": None,
    }

    config = ConfigStore.get_instance().config
    server_config = config.get("server", {})

    return {**defaults, **server_config}


def get_idle_timeout() -> int:
    """Get the server idle timeout in seconds."""
    return get_server_config().get("idle_timeout", 300)
