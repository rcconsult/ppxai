"""
Configuration package for ppxai.

This package provides thread-safe, lazy-loading configuration management.
All public functions maintain backward compatibility with the original config.py.

Architecture:
- ConfigStore: Thread-safe singleton holding config state
- loader.py: Config file discovery and parsing
- defaults.py: Shell/agent default constants
- providers.py: Provider, model, pricing, capabilities queries
- tools.py: Tool, shell, agent, container queries
- features.py: TUI and session queries
- paths.py: Paths, data directory, server queries
- prompts.py: System prompts, context, bootstrap queries

v1.13.10: Refactored from monolithic config.py
v1.17.0: Split into domain submodules (providers, tools, features, paths, prompts)
"""

from typing import Any, Dict

from ..common.logger import Logger

# Context, injection, bootstrap (no provider/prompt dependencies)
from .context import (
    DEFAULT_BOOTSTRAP_FILES,
    DEFAULT_CONTEXT_LIMIT,
    DEFAULT_CONTEXT_WARN_PERCENT,
    DEFAULT_MAX_INJECTION_SIZE,
    get_bootstrap_config,
    get_bootstrap_files,
    get_context_config,
    get_context_warn_percent,
    get_default_context_limit,
    get_max_injection_size,
    is_bootstrap_enabled,
)
from .defaults import (
    DEFAULT_AGENT_AUTO_RETRY_EMPTY,
    DEFAULT_AGENT_CONTEXT_CHAR_LIMIT,
    # Agent defaults
    DEFAULT_AGENT_MAX_ITERATIONS,
    DEFAULT_AGENT_MAX_SAME_TOOL_CALLS,
    DEFAULT_AGENT_MAX_TOOL_ITERATIONS,
    DEFAULT_AGENT_MIN_TASK_WORDS,
    DEFAULT_ALLOWED_COMMANDS,
    # Shell tool defaults
    DEFAULT_DANGEROUS_COMMANDS,
    DEFAULT_NEVER_ALLOW,
)

# Execution surfaces (ADR 0010 third axis; ADR 0011 one-off tier)
from .execution import (
    get_execution_collect,
    get_execution_config,
    get_execution_default_subagent,
    get_execution_egress_ceiling,
    get_execution_profiles,
    get_execution_run_config,
    get_execution_task_config,
)

# TUI and session
from .features import (
    DEFAULT_FILE_TREE_IGNORE_DIRS,
    get_auto_restore_mode,
    get_auto_save_interval,
    get_debug_log_enabled,
    get_file_tree_config,
    get_file_tree_ignore_dirs,
    get_session_config,
    get_tui_config,
    get_tui_theme,
    set_tui_config,
)
from .loader import (
    # Default capabilities
    DEFAULT_CAPABILITIES,
    EXPORTS_DIR,
    # Path constants
    PPXAI_HOME,
    SESSIONS_DIR,
    USAGE_FILE,
    USER_CONFIG_FILE,
    _convert_models_format,
    _load_json_config,
    # Loading functions
    find_config_file,
    load_config,
)
from .loader import (
    # Initialization
    initialize as _loader_initialize,
)

# Paths, data directory, server
from .paths import (
    get_bin_search_paths,
    get_data_dir,
    get_idle_timeout,
    get_paths_config,
    get_server_config,
)

# System prompts (depends on providers)
from .prompts import (
    DEFAULT_SYSTEM_PROMPTS,
    get_system_prompt,
    get_system_prompt_mode,
)

# Provider, model, pricing, capabilities
from .providers import (
    _get_config,
    _get_models,
    _get_providers,
    calculate_cost,
    get_active_models,
    get_active_pricing,
    get_api_key,
    get_available_providers,
    get_base_url,
    get_coding_model,
    get_config_source,
    get_default_model,
    get_default_provider,
    get_extra_body,
    get_generation_params,
    get_model_context_limit,
    get_model_max_tokens,
    get_model_pricing,
    get_provider_capabilities,
    get_provider_config,
    get_reasoning_trigger,
    provider_needs_tool,
    validate_config,
)
from .store import ConfigStore, get_config, register_reload_callback, reload_config

# Tool, shell, agent, container
from .tools import (
    get_agent_config,
    get_container_config,
    get_shell_config,
    get_tool_config,
    get_tool_description_overrides,
    get_tool_pricing,
    get_vision_model_config,
)

# Legacy compatibility exports
# Note: MODEL_PRICING is deprecated - use get_model_pricing() instead
MODEL_PRICING = {}
# ADR 0012 W5: `sonar-pro` is chat-completions ONLY and Perplexity retires
# that endpoint 2026-09-27 — it is not served on the Responses wire in either
# bare or namespaced form (measured 2026-08-31). `perplexity/sonar` is the
# only Sonar model on the surviving wire, so the shipped default points there.
CODING_MODEL = "perplexity/sonar"


# =============================================================================
# Module-level attributes - populated by initialize()
# =============================================================================
# PROVIDERS and MODELS are module-level dicts that are populated when
# initialize() is called. They are mutated in-place on reload, so all
# existing references see the updated data (no stale snapshots).

PROVIDERS: dict[str, Any] = {}
MODELS: dict[str, Any] = {}
_initialized = False


def _refresh_module_dicts():
    """Re-populate PROVIDERS/MODELS from current config.

    Called by initialize() and registered as a reload callback
    so reload_config() can update these dicts without importing __init__.
    """
    config = ConfigStore.get_instance().config
    PROVIDERS.clear()
    PROVIDERS.update(config.get("providers", {}))
    MODELS.clear()
    MODELS.update(PROVIDERS.get("perplexity", {}).get("models", {}))


# Register so reload_config() in store.py can refresh PROVIDERS/MODELS
# without a circular import back to __init__.py
register_reload_callback(_refresh_module_dicts)


def initialize():
    """Initialize config system and populate module-level PROVIDERS/MODELS.

    This function:
    1. Loads .env files (PERPLEXITY_API_KEY, GEMINI_API_KEY, etc.)
    2. Loads config from ppxai-config.json
    3. Populates PROVIDERS/MODELS dicts

    Safe to call multiple times (idempotent). Uses .clear() + .update()
    to mutate dicts in-place, ensuring existing references see new data.
    """
    global _initialized

    # First, load .env files (from loader.py)
    _loader_initialize()

    # Then populate PROVIDERS/MODELS from config
    _refresh_module_dicts()

    # Restore persisted debug-log state for ALL ppxai clients (Rich, Textual,
    # Web server, VSCode server, benchmarks). Must run inside initialize()
    # so it fires BEFORE any client code — in particular, BEFORE the Rich
    # TUI's session-recovery prompt, which used to swallow evidence of its
    # own silent regressions (see memory/feedback_session_recovery_ordering.md).
    try:
        from .features import get_debug_log_enabled
        if get_debug_log_enabled():
            # Two-step restore:
            # 1. Set PPXAI_DEBUG so any Logger instantiated LATER (engine,
            #    chat, server, etc.) self-enables via the env-var check in
            #    Logger.__init__. Without this, only pre-existing Logger
            #    instances would pick up the flag.
            # 2. Enable every Logger that already exists at this moment
            #    (typically just the "tui" logger that the client's main()
            #    created before calling initialize()).
            import os as _os
            _os.environ.setdefault("PPXAI_DEBUG", "1")
            Logger.enable_all()
    except Exception:
        # Never let a logger-restore failure break startup
        pass

    _initialized = True


# =============================================================================
# Public API Exports
# =============================================================================

__all__ = [
    # Store
    "ConfigStore",
    "get_config",
    "reload_config",
    # Initialization
    "initialize",
    # Path constants
    "PPXAI_HOME",
    "SESSIONS_DIR",
    "EXPORTS_DIR",
    "USAGE_FILE",
    "USER_CONFIG_FILE",
    # Default capabilities
    "DEFAULT_CAPABILITIES",
    "PROVIDERS",
    # Legacy
    "MODEL_PRICING",
    "MODELS",
    "CODING_MODEL",
    # System prompts
    "DEFAULT_SYSTEM_PROMPTS",
    # Context defaults
    "DEFAULT_MAX_INJECTION_SIZE",
    "DEFAULT_CONTEXT_LIMIT",
    "DEFAULT_CONTEXT_WARN_PERCENT",
    # Loading
    "find_config_file",
    "load_config",
    # Provider functions
    "get_default_provider",
    "get_config_source",
    "get_available_providers",
    "get_provider_config",
    "get_active_models",
    "get_active_pricing",
    "get_model_pricing",
    "calculate_cost",
    "get_api_key",
    "get_base_url",
    "get_provider_capabilities",
    "provider_needs_tool",
    "get_coding_model",
    "get_default_model",
    "validate_config",
    # Tool functions
    "get_execution_collect",
    "get_execution_config",
    "get_execution_default_subagent",
    "get_execution_egress_ceiling",
    "get_execution_profiles",
    "get_execution_run_config",
    "get_execution_task_config",
    "get_tool_config",
    "get_tool_description_overrides",
    "get_shell_config",
    "get_container_config",
    "get_vision_model_config",
    "get_tool_pricing",
    # TUI functions
    "get_tui_config",
    "get_tui_theme",
    "set_tui_config",
    "get_debug_log_enabled",
    # Session functions
    "get_session_config",
    "get_auto_restore_mode",
    "get_auto_save_interval",
    # File tree functions (v1.18.7)
    "get_file_tree_config",
    "get_file_tree_ignore_dirs",
    "DEFAULT_FILE_TREE_IGNORE_DIRS",
    # Paths functions
    "get_paths_config",
    "get_bin_search_paths",
    "get_data_dir",
    # Server functions
    "get_server_config",
    "get_idle_timeout",
    # System prompt functions
    "get_system_prompt",
    "get_system_prompt_mode",
    # Context functions
    "get_context_config",
    "get_max_injection_size",
    "get_default_context_limit",
    "get_context_warn_percent",
    "get_model_context_limit",
    "get_model_max_tokens",
    # Generation params
    "get_generation_params",
    # Vendor-specific extra_body pass-through (v1.18.3)
    "get_extra_body",
    # In-prompt reasoning trigger (v1.18.3) — e.g. nemotron's /think convention
    "get_reasoning_trigger",
    # Tool calling config (v1.16.0)
    # Bootstrap functions (v1.14.0)
    "DEFAULT_BOOTSTRAP_FILES",
    "get_bootstrap_config",
    "get_bootstrap_files",
    "is_bootstrap_enabled",
]
