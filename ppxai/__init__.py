"""
ppxai - AI Text UI Application

A terminal-based interface for interacting with LLM providers (Perplexity AI or custom self-hosted models).

v1.12.0+: Use EngineClient for programmatic access:
    from ppxai.engine import EngineClient
    engine = EngineClient()
    engine.set_provider("perplexity")
    engine.set_model("sonar-pro")

Note: TUI-specific imports are properly isolated - server builds exclude
prompt_toolkit via PyInstaller spec, so no lazy loading is needed.
"""

# Core imports - these are safe for both server and TUI
from .config import (
    CODING_MODEL,
    EXPORTS_DIR,
    MODEL_PRICING,
    MODELS,
    PROVIDERS,
    SESSIONS_DIR,
    USAGE_FILE,
    get_active_models,
    get_active_pricing,
    get_api_key,
    get_available_providers,
    get_base_url,
    get_coding_model,
    get_config_source,
    get_default_model,
    get_default_provider,
    get_provider_capabilities,
    get_provider_config,
    reload_config,
    validate_config,
)

# Export EngineClient as the primary client interface
from .engine import EngineClient
from .prompts import CODING_PROMPTS, SPEC_GUIDELINES, SPEC_TEMPLATES
from .version import __version__

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
    "PROVIDERS",
    "get_default_provider",
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
    "reload_config",
    "validate_config",
    # Engine (v1.12.0+)
    "EngineClient",
    # Prompts
    "CODING_PROMPTS",
    "SPEC_GUIDELINES",
    "SPEC_TEMPLATES",
    # Version
    "__version__",
]
