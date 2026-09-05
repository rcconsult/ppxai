"""
TUI and session configuration.
"""

import json
from typing import Any

from ..common.logger import get_logger
from .loader import find_config_file, find_writable_config_file
from .store import ConfigStore

logger = get_logger("config")


# =============================================================================
# TUI Configuration
# =============================================================================

def get_tui_config() -> dict[str, Any]:
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


def get_debug_log_enabled() -> bool:
    """Get the persisted debug-log enable flag.

    Persisted so the logger can be re-enabled during startup, BEFORE
    the session-recovery prompt fires — otherwise `/debug-log on` only
    takes effect from the next command onward and early-startup
    regressions escape into the void.
    """
    return bool(get_tui_config().get("debug_log", False))


def set_tui_config(key: str, value: Any) -> bool:
    """Set a TUI configuration value and save it to the USER config file.

    The write target is :func:`find_writable_config_file`, never the file
    reads resolve to. Until v1.19.1 this used `find_config_file()`, which
    prefers a project-local `./ppxai-config.json` — so toggling `/debug-log`
    from inside a checkout rewrote that repo's own tracked config. The ppxai
    test suite did it to ppxai on every run (debt Item 70): a smoke test
    POSTs a body to every route, `/debug-log` persists, and pytest's cwd is
    the repo root.

    When the two paths diverge the setting still applies to the running
    session (the in-memory `ConfigStore` is updated below) but the project
    config shadows it on the next start, because `load_config` takes the
    first hit rather than merging. That is worth a warning, not silence.
    """
    config_path = find_writable_config_file()

    active = find_config_file()
    if active is not None and active.resolve() != config_path.resolve():
        logger.warning(
            f"tui.{key} saved to {config_path}, but {active.resolve()} "
            f"shadows it on the next start (reads take the first config "
            f"found, they do not merge)"
        )

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
            json.dump(config_data, f, indent=2, ensure_ascii=False)
            f.write("\n")

        # Update in-memory config
        store = ConfigStore.get_instance()
        current = store.config
        if "tui" not in current:
            current["tui"] = {}
        current["tui"][key] = value

        return True
    except IOError as e:
        logger.warning(f"Config save failed: {e}")
        return False


# =============================================================================
# Session Configuration
# =============================================================================

def get_session_config() -> dict[str, Any]:
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


# =============================================================================
# File Tree Configuration (v1.18.7)
# =============================================================================

# Directories the file-tree + search routes skip by default. Pre-v1.18.7
# this was hard-coded in ppxai/server/routes/files.py:22 as a module-level
# constant — invisible to users and not overridable. Promoted to config
# in v1.18.7 because users with workflows that touch `venv/` or `build/`
# directly need to see them in the sidebar (e.g. inspecting a packaged
# wheel under dist/, or a freshly-built virtualenv).
#
# Override semantics:
#   - If `file_tree.ignore_dirs` is unset → use DEFAULT_FILE_TREE_IGNORE_DIRS
#   - If set to a list → use that list verbatim (REPLACE, not merge)
#   - To add to the defaults, copy the default list into your config and
#     extend it. To unhide a single dir, copy the default list minus that dir.
#   - Empty list → show everything (no ignore)
#
# REPLACE-not-merge semantics keep the behavior predictable: what you write
# is what you get. A merge would force users to learn an exclusion syntax
# to remove a default, which is a worse UX than copy-edit.
DEFAULT_FILE_TREE_IGNORE_DIRS = [
    '.git', 'node_modules', '__pycache__',
    '.venv', 'venv', '.tox', 'dist', 'build', '.eggs', '.mypy_cache',
]


def get_file_tree_config() -> dict[str, Any]:
    """Get file-tree-specific configuration."""
    defaults = {
        "ignore_dirs": list(DEFAULT_FILE_TREE_IGNORE_DIRS),
    }
    config = ConfigStore.get_instance().config
    ft_config = config.get("file_tree", {})
    return {**defaults, **ft_config}


def get_file_tree_ignore_dirs() -> set:
    """Get the directory-name set the file tree + search should skip.

    Returns a set (not a list) because the only operations are membership
    checks (`name in ignored_set` / `any(d in path.parts for d in ignored_set)`).
    Set lookup is O(1); list lookup is O(n). The three call sites in
    ppxai/server/routes/files.py would otherwise each pay the O(n) cost
    per directory entry.
    """
    raw = get_file_tree_config().get("ignore_dirs", DEFAULT_FILE_TREE_IGNORE_DIRS)
    # Defensive: tolerate user config where ignore_dirs is None / not-a-list
    if not isinstance(raw, list):
        logger.warning(
            f"file_tree.ignore_dirs is not a list ({type(raw).__name__}); "
            f"falling back to defaults"
        )
        raw = DEFAULT_FILE_TREE_IGNORE_DIRS
    return set(raw)
