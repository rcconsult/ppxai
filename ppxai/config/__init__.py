"""
Configuration package for ppxai.

This package provides thread-safe, lazy-loading configuration management.
All public functions maintain backward compatibility with the original config.py.

Architecture:
- ConfigStore: Thread-safe singleton holding config state
- loader.py: Config file discovery and parsing
- Domain modules: Organized by functionality

v1.13.10: Refactored from monolithic config.py
"""

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from .store import ConfigStore, get_config, reload_config
from .loader import (
    # Path constants
    PPXAI_HOME,
    SESSIONS_DIR,
    EXPORTS_DIR,
    USAGE_FILE,
    USER_CONFIG_FILE,
    # Default capabilities
    DEFAULT_CAPABILITIES,
    # Initialization
    initialize,
    # Loading functions
    find_config_file,
    load_config,
    _load_json_config,
    _convert_models_format,
)
from .defaults import (
    # Shell tool defaults
    DEFAULT_DANGEROUS_COMMANDS,
    DEFAULT_NEVER_ALLOW,
    DEFAULT_ALLOWED_COMMANDS,
    # Agent defaults
    DEFAULT_AGENT_MAX_ITERATIONS,
    DEFAULT_AGENT_MAX_TOOL_ITERATIONS,
    DEFAULT_AGENT_MAX_SAME_TOOL_CALLS,
    DEFAULT_AGENT_CONTEXT_CHAR_LIMIT,
    DEFAULT_AGENT_MIN_TASK_WORDS,
    DEFAULT_AGENT_AUTO_RETRY_EMPTY,
)


# =============================================================================
# Computed Constants (derived from ConfigStore)
# =============================================================================

def _get_config() -> Dict[str, Any]:
    """Get config dict from config store.

    Note: Config is loaded lazily on first access to ConfigStore.config.
    After first load, returns cached config dict.
    """
    return ConfigStore.get_instance().config


def _get_providers() -> Dict[str, Any]:
    """Get providers dict from config store."""
    return _get_config().get("providers", {})


def _get_models() -> Dict[str, Any]:
    """Get models from default perplexity provider."""
    return _get_providers().get("perplexity", {}).get("models", {})


# Legacy compatibility exports
# Note: MODEL_PRICING is deprecated - use get_model_pricing() instead
# Keeping empty dict for backward compatibility with code that checks it
MODEL_PRICING = {}
CODING_MODEL = "sonar-pro"


# =============================================================================
# Module-level lazy attributes via __getattr__
# =============================================================================
# PROVIDERS and MODELS need to be dict-like but should not trigger config
# loading at import time. Using __getattr__ defers loading until first use.

_lazy_attrs = {
    "PROVIDERS": _get_providers,
    "MODELS": _get_models,
}


def __getattr__(name: str):
    """Lazy module attribute access for PROVIDERS and MODELS."""
    if name in _lazy_attrs:
        return _lazy_attrs[name]()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


# =============================================================================
# Default System Prompts
# =============================================================================

DEFAULT_SYSTEM_PROMPTS = {
    "global": (
        "You are a helpful AI assistant. Be concise and direct in your responses. "
        "When using tools, report results briefly without unnecessary elaboration."
    ),
    "perplexity": (
        "You are a helpful AI assistant with web search capabilities. "
        "Be concise. Cite sources as markdown links. "
        "For tool results, report essential information only."
    ),
    "gemini": (
        "You are a helpful AI assistant. Be concise and direct. "
        "When using tools, report results briefly. "
        "For web searches, cite sources as markdown links."
    ),
    "openai": (
        "You are a helpful AI assistant. Be concise and direct. "
        "When using tools, report results briefly without elaboration."
    ),
    "custom": (
        "You are a helpful AI coding assistant. Be concise and direct. "
        "When executing tools, report only the essential results. "
        "Avoid lengthy explanations unless explicitly requested."
    ),
}

# Context defaults
DEFAULT_MAX_INJECTION_SIZE = 100_000
DEFAULT_CONTEXT_LIMIT = 128_000
DEFAULT_CONTEXT_WARN_PERCENT = 80


# =============================================================================
# Public API Functions
# =============================================================================

def get_default_provider() -> str:
    """Get the default provider from environment or configuration.

    Checks in order:
    1. MODEL_PROVIDER environment variable
    2. default_provider from config file
    3. Falls back to "perplexity"

    Returns:
        Provider ID string.
    """
    env_provider = os.getenv("MODEL_PROVIDER")
    if env_provider and env_provider in _get_providers():
        return env_provider

    config = ConfigStore.get_instance().config
    default = config.get("default_provider", "perplexity")
    if default in _get_providers():
        return default

    return "perplexity"


def get_config_source() -> str:
    """Get the source of the current configuration."""
    return ConfigStore.get_instance().config.get("config_source", "builtin")


def get_available_providers() -> List[str]:
    """Get list of all available provider IDs."""
    return list(_get_providers().keys())


def get_provider_config(provider: str = None) -> dict:
    """Get configuration for the specified provider."""
    if provider is None:
        provider = get_default_provider()
    providers = _get_providers()
    return providers.get(provider, providers.get("perplexity", {}))


def get_active_models() -> dict:
    """Get models for the active provider."""
    return get_provider_config().get("models", {})


def get_active_pricing() -> dict:
    """Get pricing for the active provider."""
    return get_provider_config().get("pricing", {})


def get_model_pricing(provider: str = None) -> dict:
    """Get pricing for the specified provider."""
    return get_provider_config(provider).get("pricing", {})


def calculate_cost(prompt_tokens: int, completion_tokens: int, model: str, provider: str = None) -> float:
    """Calculate estimated cost in USD for token usage."""
    pricing = get_model_pricing(provider)
    model_pricing = pricing.get(model, {})

    if not model_pricing:
        return 0.0

    input_price = model_pricing.get("input", 0.0)
    output_price = model_pricing.get("output", 0.0)

    input_cost = (prompt_tokens / 1_000_000) * input_price
    output_cost = (completion_tokens / 1_000_000) * output_price

    return input_cost + output_cost


def get_api_key(provider: str = None) -> str:
    """Get API key for the specified provider from environment."""
    config = get_provider_config(provider)
    return os.getenv(config.get("api_key_env", ""), "")


def get_base_url(provider: str = None) -> str:
    """Get base URL for the specified provider."""
    return get_provider_config(provider).get("base_url", "")


def get_provider_capabilities(provider: str = None) -> dict:
    """Get capabilities for the specified provider."""
    config = get_provider_config(provider)
    return config.get("capabilities", DEFAULT_CAPABILITIES)


def provider_needs_tool(provider: str, tool_category: str) -> bool:
    """Check if a provider needs a specific tool category."""
    capabilities = get_provider_capabilities(provider)
    return not capabilities.get(tool_category, False)


def get_tool_config(tool_name: str) -> Dict[str, Any]:
    """Get configuration for a specific tool."""
    config = ConfigStore.get_instance().config
    tools_config = config.get("tools", {})
    return tools_config.get(tool_name, {})


def get_tool_description_overrides(provider: str = None, model: str = None) -> Dict[str, str]:
    """Get tool description overrides from config."""
    config = ConfigStore.get_instance().config
    tools_config = config.get("tools", {})
    result = {}

    global_overrides = tools_config.get("overrides", {})
    result.update(global_overrides)

    if provider:
        provider_overrides = tools_config.get("provider_overrides", {}).get(provider, {})
        result.update(provider_overrides)

    if model:
        model_overrides = tools_config.get("model_overrides", {}).get(model, {})
        result.update(model_overrides)

    return result


def get_shell_config() -> Dict[str, Any]:
    """Get shell tool configuration with defaults from defaults.py."""
    shell_config = get_tool_config("shell")

    default_interactive = [
        'nano', 'vim', 'vi', 'emacs', 'pico', 'joe',
        'less', 'more',
        'top', 'htop', 'btop',
        'python', 'python3', 'ipython', 'node', 'irb', 'ruby',
        'ssh', 'telnet', 'ftp', 'sftp',
        'mysql', 'psql', 'mongo', 'redis-cli',
        'bash', 'zsh', 'sh', 'fish', 'csh', 'tcsh',
    ]

    default_non_interactive_with_args = [
        'python', 'python3', 'ipython', 'node', 'irb', 'ruby',
        'bash', 'zsh', 'sh', 'fish', 'csh', 'tcsh',
        'ssh',
        'mysql', 'psql',
    ]

    return {
        "require_consent": shell_config.get("require_consent", True),
        "dangerous_commands": shell_config.get("dangerous_commands", DEFAULT_DANGEROUS_COMMANDS),
        "allowed_commands": shell_config.get("allowed_commands", DEFAULT_ALLOWED_COMMANDS),
        "never_allow": shell_config.get("never_allow", DEFAULT_NEVER_ALLOW),
        "sandboxed_paths": shell_config.get("sandboxed_paths", []),
        "interactive_commands": shell_config.get("interactive_commands", default_interactive),
        "non_interactive_with_args": shell_config.get("non_interactive_with_args", default_non_interactive_with_args),
    }


def get_agent_config() -> Dict[str, Any]:
    """Get agent tool configuration with defaults from defaults.py."""
    agent_config = get_tool_config("agent")

    return {
        "max_iterations": agent_config.get("max_iterations", DEFAULT_AGENT_MAX_ITERATIONS),
        "max_tool_iterations": agent_config.get("max_tool_iterations", DEFAULT_AGENT_MAX_TOOL_ITERATIONS),
        "max_same_tool_calls": agent_config.get("max_same_tool_calls", DEFAULT_AGENT_MAX_SAME_TOOL_CALLS),
        "context_char_limit": agent_config.get("context_char_limit", DEFAULT_AGENT_CONTEXT_CHAR_LIMIT),
        "min_task_words": agent_config.get("min_task_words", DEFAULT_AGENT_MIN_TASK_WORDS),
        "auto_retry_empty": agent_config.get("auto_retry_empty", DEFAULT_AGENT_AUTO_RETRY_EMPTY),
    }


def get_visualization_config() -> Dict[str, Any]:
    """Get data visualization configuration."""
    config = ConfigStore.get_instance().config
    viz_config = config.get("visualization", {})

    return {
        "max_rows": viz_config.get("max_rows", 10000),
        "max_columns": viz_config.get("max_columns", 50),
        "page_size": viz_config.get("page_size", 50),
        "tree_depth": viz_config.get("tree_depth", 3),
        "auto_detect": viz_config.get("auto_detect", True),
        "csv_delimiter": viz_config.get("csv_delimiter", "auto"),
        "theme": viz_config.get("theme", "default"),
    }


def get_container_config() -> Dict[str, Any]:
    """Get container tools configuration."""
    tool_config = get_tool_config("container")

    return {
        "enabled": tool_config.get("enabled", True),
        "require_consent": tool_config.get("require_consent", True),
        "default_runtime": tool_config.get("default_runtime", "auto"),
        "timeout": tool_config.get("timeout", 60),
    }


def get_tool_pricing(tool_name: str, provider: str) -> Dict[str, Any]:
    """Get pricing configuration for a tool provider."""
    tool_config = get_tool_config(tool_name)
    pricing = tool_config.get("pricing", {})
    return pricing.get(provider, {})


def get_coding_model(provider: str = None) -> str:
    """Get the best model for coding tasks for the provider."""
    return get_provider_config(provider).get("coding_model", "")


def get_default_model(provider: str = None) -> str:
    """Get the default model for the provider."""
    return get_provider_config(provider).get("default_model", "")


def validate_config() -> Dict[str, Any]:
    """Validate the current configuration and check API key availability."""
    config = ConfigStore.get_instance().config
    providers = _get_providers()

    result = {
        "valid": True,
        "config_source": config.get("config_source", "builtin"),
        "providers": {},
    }

    for provider_id, provider_config in providers.items():
        api_key = get_api_key(provider_id)
        has_key = bool(api_key)

        result["providers"][provider_id] = {
            "name": provider_config.get("name", provider_id),
            "has_api_key": has_key,
            "api_key_env": provider_config.get("api_key_env", ""),
            "base_url": provider_config.get("base_url", ""),
            "model_count": len(provider_config.get("models", {})),
            "default_model": provider_config.get("default_model", ""),
        }

    return result


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
    import json

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


# =============================================================================
# Paths Configuration
# =============================================================================

import platform


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
    """Get list of directories to search for ppxai binaries."""
    return get_paths_config().get("bin_search_paths", [])


def get_data_dir() -> Path:
    """Get the data directory for sessions, exports, etc."""
    return Path(get_paths_config().get("data_dir", str(Path.home() / ".ppxai")))


# =============================================================================
# Server Configuration
# =============================================================================

def get_server_config() -> Dict[str, Any]:
    """Get server-specific configuration."""
    defaults = {
        "idle_timeout": 300,
        "port": 54320,
    }

    config = ConfigStore.get_instance().config
    server_config = config.get("server", {})

    return {**defaults, **server_config}


def get_idle_timeout() -> int:
    """Get the server idle timeout in seconds."""
    return get_server_config().get("idle_timeout", 300)


# =============================================================================
# System Prompt Configuration
# =============================================================================

def get_system_prompt(provider: str = None) -> str:
    """Get the system prompt for the specified provider."""
    if provider is None:
        provider = get_default_provider()

    config_path = find_config_file()
    if config_path:
        json_config = _load_json_config(config_path)

        provider_config = json_config.get("providers", {}).get(provider, {})
        if provider_config.get("system_prompt"):
            return provider_config["system_prompt"]

        if json_config.get("system_prompt"):
            return json_config["system_prompt"]

    return DEFAULT_SYSTEM_PROMPTS.get(provider, DEFAULT_SYSTEM_PROMPTS["global"])


def get_system_prompt_mode(provider: str = None) -> str:
    """Get the system prompt mode for the specified provider."""
    if provider is None:
        provider = get_default_provider()

    config_path = find_config_file()
    if config_path:
        json_config = _load_json_config(config_path)

        provider_config = json_config.get("providers", {}).get(provider, {})
        if provider_config.get("system_prompt_mode"):
            return provider_config["system_prompt_mode"]

        if json_config.get("system_prompt_mode"):
            return json_config["system_prompt_mode"]

    return "prepend"


# =============================================================================
# Context Configuration
# =============================================================================

def get_context_config() -> Dict[str, Any]:
    """Get context and truncation configuration."""
    defaults = {
        "max_injection_size": DEFAULT_MAX_INJECTION_SIZE,
        "default_context_limit": DEFAULT_CONTEXT_LIMIT,
        "warn_at_percent": DEFAULT_CONTEXT_WARN_PERCENT,
    }

    config = ConfigStore.get_instance().config
    context_config = config.get("context", {})
    return {**defaults, **context_config}


# =============================================================================
# Bootstrap Configuration (v1.14.0)
# =============================================================================

# Default bootstrap file aliases (checked in order)
DEFAULT_BOOTSTRAP_FILES = ["AGENTS.md", "CLAUDE.md"]


def get_bootstrap_config() -> Dict[str, Any]:
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


def get_bootstrap_files() -> List[str]:
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


def get_max_injection_size() -> int:
    """Get the maximum size (in chars) for @file/@git/@tree injections."""
    return get_context_config().get("max_injection_size", DEFAULT_MAX_INJECTION_SIZE)


def get_default_context_limit() -> int:
    """Get the default model context limit in tokens."""
    return get_context_config().get("default_context_limit", DEFAULT_CONTEXT_LIMIT)


def get_context_warn_percent() -> int:
    """Get the percentage threshold for context usage warnings."""
    return get_context_config().get("warn_at_percent", DEFAULT_CONTEXT_WARN_PERCENT)


def get_model_context_limit(provider: str = None, model: str = None) -> int:
    """Get the context limit for a specific model."""
    if provider is None:
        provider = get_default_provider()

    if model is None:
        model = get_default_model(provider)

    config_path = find_config_file()
    if config_path:
        json_config = _load_json_config(config_path)
        provider_config = json_config.get("providers", {}).get(provider, {})
        models = provider_config.get("models", {})
        model_config = models.get(model, {})

        if "context_limit" in model_config:
            return model_config["context_limit"]

    return get_default_context_limit()


def get_model_max_tokens(provider: str = None, model: str = None) -> Optional[int]:
    """Get the max_tokens setting for output generation."""
    if provider is None:
        provider = get_default_provider()

    if model is None:
        model = get_default_model(provider)

    config_path = find_config_file()
    if config_path:
        json_config = _load_json_config(config_path)
        provider_config = json_config.get("providers", {}).get(provider, {})

        models = provider_config.get("models", {})
        model_config = models.get(model, {})
        if "max_tokens" in model_config:
            return model_config["max_tokens"]

        if "default_max_tokens" in provider_config:
            return provider_config["default_max_tokens"]

    return None


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
    "get_tool_config",
    "get_tool_description_overrides",
    "get_shell_config",
    "get_visualization_config",
    "get_container_config",
    "get_tool_pricing",
    # TUI functions
    "get_tui_config",
    "get_tui_theme",
    "set_tui_config",
    # Session functions
    "get_session_config",
    "get_auto_restore_mode",
    "get_auto_save_interval",
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
    # Bootstrap functions (v1.14.0)
    "DEFAULT_BOOTSTRAP_FILES",
    "get_bootstrap_config",
    "get_bootstrap_files",
    "is_bootstrap_enabled",
]
