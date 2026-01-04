"""
ppxai - AI Text UI Application

A terminal-based interface for interacting with LLM providers (Perplexity AI or custom self-hosted models).

v1.12.0+: Use EngineClient for programmatic access:
    from ppxai.engine import EngineClient
    engine = EngineClient()
    engine.set_provider("perplexity")
    engine.set_model("sonar-pro")

Note: TUI-specific imports (commands, main, ui) are lazy-loaded to allow
the server to import ppxai submodules without requiring prompt_toolkit.
"""

# Core imports - these are safe for both server and TUI
from .config import (
    SESSIONS_DIR,
    EXPORTS_DIR,
    USAGE_FILE,
    MODEL_PRICING,
    MODELS,
    CODING_MODEL,
    MODEL_PROVIDER,
    PROVIDERS,
    get_provider_config,
    get_active_models,
    get_active_pricing,
    get_api_key,
    get_base_url,
    get_coding_model,
    get_default_model,
    get_config_source,
    get_available_providers,
    get_provider_capabilities,
    set_active_provider,
    reload_config,
    validate_config,
)
from .prompts import CODING_PROMPTS, SPEC_GUIDELINES, SPEC_TEMPLATES
from .utils import read_file_content
from .version import __version__

# Export EngineClient as the primary client interface
from .engine import EngineClient

# TUI-specific imports are lazy-loaded via __getattr__ below
# This allows the server to import ppxai.* without requiring prompt_toolkit

__all__ = [
    # Config
    "SESSIONS_DIR",
    "EXPORTS_DIR",
    "USAGE_FILE",
    "MODEL_PRICING",
    "MODELS",
    "CODING_MODEL",
    "MODEL_PROVIDER",
    "PROVIDERS",
    "get_provider_config",
    "get_active_models",
    "get_active_pricing",
    "get_api_key",
    "get_base_url",
    "get_coding_model",
    "get_default_model",
    "get_config_source",
    "get_available_providers",
    "get_provider_capabilities",
    "set_active_provider",
    "reload_config",
    "validate_config",
    # Engine (v1.12.0+)
    "EngineClient",
    # Prompts
    "CODING_PROMPTS",
    "SPEC_GUIDELINES",
    "SPEC_TEMPLATES",
    # Utils
    "read_file_content",
    # Version
    "__version__",
    # UI (lazy-loaded)
    "console",
    "display_welcome",
    "display_spec_help",
    "display_models",
    "select_model",
    "select_provider",
    "display_sessions",
    "display_usage",
    "display_global_usage",
    "display_tools_table",
    "display_tool_help",
    # Commands (lazy-loaded)
    "CommandHandler",
    "send_coding_task",
    # Main (lazy-loaded)
    "main",
]

# Lazy loading for TUI-specific modules
# These require prompt_toolkit which is not available in server builds
_lazy_imports = {
    # UI module exports
    "console": ".ui",
    "display_welcome": ".ui",
    "display_spec_help": ".ui",
    "display_models": ".ui",
    "select_model": ".ui",
    "select_provider": ".ui",
    "display_sessions": ".ui",
    "display_usage": ".ui",
    "display_global_usage": ".ui",
    "display_tools_table": ".ui",
    "display_tool_help": ".ui",
    # Commands module exports
    "CommandHandler": ".commands",
    "send_coding_task": ".commands",
    # Main module exports
    "main": ".main",
}


def __getattr__(name: str):
    """Lazy load TUI-specific modules on first access."""
    if name in _lazy_imports:
        module_name = _lazy_imports[name]
        import importlib
        module = importlib.import_module(module_name, package="ppxai")
        return getattr(module, name)
    raise AttributeError(f"module 'ppxai' has no attribute {name!r}")
