"""
Context, injection, and bootstrap configuration.

This module sits below providers.py and prompts.py in the import DAG.
It depends only on store.py (no provider/prompt dependencies).
"""

from typing import Any

from .store import ConfigStore

# =============================================================================
# Context Defaults
# =============================================================================

DEFAULT_MAX_INJECTION_SIZE = 100_000
DEFAULT_CONTEXT_LIMIT = 128_000
DEFAULT_CONTEXT_WARN_PERCENT = 80


# =============================================================================
# Context Configuration
# =============================================================================

def get_context_config() -> dict[str, Any]:
    """Get context and truncation configuration."""
    defaults = {
        "max_injection_size": DEFAULT_MAX_INJECTION_SIZE,
        "default_context_limit": DEFAULT_CONTEXT_LIMIT,
        "warn_at_percent": DEFAULT_CONTEXT_WARN_PERCENT,
    }

    config = ConfigStore.get_instance().config
    context_config = config.get("context", {})
    return {**defaults, **context_config}


def get_max_injection_size() -> int:
    """Get the maximum size (in chars) for @file/@git/@tree injections."""
    return get_context_config().get("max_injection_size", DEFAULT_MAX_INJECTION_SIZE)


def get_default_context_limit() -> int:
    """Get the default model context limit in tokens."""
    return get_context_config().get("default_context_limit", DEFAULT_CONTEXT_LIMIT)


def get_context_warn_percent() -> int:
    """Get the percentage threshold for context usage warnings."""
    return get_context_config().get("warn_at_percent", DEFAULT_CONTEXT_WARN_PERCENT)


# =============================================================================
# Bootstrap Configuration (v1.14.0)
# =============================================================================

# Default bootstrap file aliases (checked in order)
DEFAULT_BOOTSTRAP_FILES = ["AGENTS.md", "CLAUDE.md", "INSTRUCTIONS.md"]


def get_bootstrap_config() -> dict[str, Any]:
    """Get bootstrap context configuration.

    Returns:
        Dict with 'files' (list of filenames) and 'enabled' (bool)
    """
    defaults = {
        "files": DEFAULT_BOOTSTRAP_FILES,
        "enabled": True,
    }

    config = ConfigStore.get_instance().config
    bootstrap_config = config.get("bootstrap", {})
    return {**defaults, **bootstrap_config}


def get_bootstrap_files() -> list[str]:
    """Get list of bootstrap file aliases to search for.

    Returns:
        List of filenames (e.g., ["AGENTS.md", "CLAUDE.md"])
    """
    return get_bootstrap_config().get("files", DEFAULT_BOOTSTRAP_FILES)


def is_bootstrap_enabled() -> bool:
    """Check if bootstrap context loading is enabled.

    Returns:
        True if bootstrap is enabled (default), False if disabled
    """
    config = get_bootstrap_config()
    # Disabled if enabled=false OR if files list is empty
    if not config.get("enabled", True):
        return False
    if not config.get("files", DEFAULT_BOOTSTRAP_FILES):
        return False
    return True
