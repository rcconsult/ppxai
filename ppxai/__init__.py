"""
ppxai - AI Text UI Application

A terminal-based interface for interacting with LLM providers (Perplexity AI or custom self-hosted models).
"""

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
from .client import AIClient, PerplexityClient
from .prompts import CODING_PROMPTS, SPEC_GUIDELINES, SPEC_TEMPLATES
from .ui import (
    console,
    display_welcome,
    display_spec_help,
    display_models,
    select_model,
    select_provider,
    display_sessions,
    display_usage,
    display_global_usage,
    display_tools_table,
)
from .utils import read_file_content
from .commands import CommandHandler, send_coding_task

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
    # Client
    "AIClient",
    "PerplexityClient",  # Backward compatibility alias
    # Prompts
    "CODING_PROMPTS",
    "SPEC_GUIDELINES",
    "SPEC_TEMPLATES",
    # UI
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
    # Utils
    "read_file_content",
    # Commands
    "CommandHandler",
    "send_coding_task",
]

__version__ = "1.6.0"
