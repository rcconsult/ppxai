"""
Paths, data directory, and server configuration.
"""

import platform
import sys
from pathlib import Path
from typing import Any, Dict, List

from ..common.logger import get_logger
from .store import ConfigStore

logger = get_logger("config")


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


def get_default_working_dir() -> str:
    """The deployment-wide default working directory.

    `server.working_dir` from config when set and existing, else the user's
    home. Used for every new session engine AND as the fallback working dir of
    an unsealed task run — so a run's relative tool paths never silently depend
    on where the server process happened to be launched from.

    Lives HERE, not in `server/session_manager.py` where it was originally
    written, because it reads config and touches the filesystem and holds no
    session state whatsoever. The old home made it un-importable from the
    engine layer without inverting Engine -> Server -> Clients, which blocked
    `engine/task_runner.py`. `server.session_manager` re-exports the name.
    """
    configured = get_server_config().get("working_dir")
    if configured:
        path = Path(configured).expanduser()
        if path.is_dir():
            return str(path)
        logger.warning(
            f"Configured working_dir '{configured}' does not exist, "
            f"falling back to home"
        )
    return str(Path.home())
