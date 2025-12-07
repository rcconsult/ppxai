"""
Configuration and constants for the ppxai application.

Supports hybrid configuration:
- ppxai-config.json: Provider definitions, models, capabilities (can be version controlled)
- .env: API keys and secrets only (never commit)

Config file search order:
1. PPXAI_CONFIG_FILE environment variable (if set)
2. ./ppxai-config.json (project-specific)
3. ~/.ppxai/ppxai-config.json (user-specific)
4. Built-in defaults (Perplexity, Gemini)
"""

import json
import os
from pathlib import Path
from typing import Dict, List, Optional, Any
from dotenv import load_dotenv

# Load .env file from the current working directory (standard behavior)
# This allows users to place .env in their project root
load_dotenv()

# Directories for data storage
PPXAI_HOME = Path.home() / ".ppxai"
SESSIONS_DIR = PPXAI_HOME / "sessions"
EXPORTS_DIR = PPXAI_HOME / "exports"
USAGE_FILE = PPXAI_HOME / "usage.json"
USER_CONFIG_FILE = PPXAI_HOME / "ppxai-config.json"

# Ensure directories exist
SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
EXPORTS_DIR.mkdir(parents=True, exist_ok=True)

# =============================================================================
# Built-in Default Configuration (Perplexity, Gemini)
# =============================================================================

BUILTIN_PROVIDERS = {
    "perplexity": {
        "name": "Perplexity AI",
        "base_url": "https://api.perplexity.ai",
        "api_key_env": "PERPLEXITY_API_KEY",
        "default_model": "sonar-pro",
        "coding_model": "sonar-pro",
        "models": {
            "sonar": {
                "name": "Sonar",
                "description": "Lightweight search model with real-time grounding"
            },
            "sonar-pro": {
                "name": "Sonar Pro",
                "description": "Advanced search model for complex queries"
            },
            "sonar-reasoning": {
                "name": "Sonar Reasoning",
                "description": "Fast reasoning model for problem-solving with search"
            },
            "sonar-reasoning-pro": {
                "name": "Sonar Reasoning Pro",
                "description": "Precision reasoning with Chain of Thought capabilities"
            },
            "sonar-deep-research": {
                "name": "Sonar Deep Research",
                "description": "Exhaustive research with comprehensive reports"
            },
        },
        "pricing": {
            # Prices per million tokens (2025)
            "sonar": {"input": 1.00, "output": 1.00},
            "sonar-pro": {"input": 3.00, "output": 15.00},
            "sonar-reasoning": {"input": 1.00, "output": 5.00},
            "sonar-reasoning-pro": {"input": 2.00, "output": 8.00},
            "sonar-deep-research": {"input": 2.00, "output": 8.00},
        },
        "capabilities": {
            "web_search": True,
            "web_fetch": True,
            "weather": True,
            "realtime_info": True,
        },
    },
    "gemini": {
        "name": "Google Gemini",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "api_key_env": "GEMINI_API_KEY",
        "default_model": "gemini-2.0-flash",
        "coding_model": "gemini-2.5-pro",
        "models": {
            "gemini-2.0-flash": {
                "name": "Gemini 2.0 Flash",
                "description": "Fast model with multimodal support"
            },
            "gemini-2.0-flash-lite": {
                "name": "Gemini 2.0 Flash Lite",
                "description": "Cost-efficient for high-volume tasks"
            },
            "gemini-2.5-flash": {
                "name": "Gemini 2.5 Flash",
                "description": "Latest fast model, best price/performance"
            },
            "gemini-2.5-pro": {
                "name": "Gemini 2.5 Pro",
                "description": "Most capable model for complex reasoning"
            },
        },
        "pricing": {
            # Prices per million tokens (2025)
            "gemini-2.0-flash": {"input": 0.10, "output": 0.40},
            "gemini-2.0-flash-lite": {"input": 0.075, "output": 0.30},
            "gemini-2.5-flash": {"input": 0.15, "output": 0.60},
            "gemini-2.5-pro": {"input": 1.25, "output": 5.00},
        },
        "capabilities": {
            "web_search": False,
            "web_fetch": False,
            "weather": False,
            "realtime_info": False,
        },
    },
}

DEFAULT_CAPABILITIES = {
    "web_search": False,
    "web_fetch": False,
    "weather": False,
    "realtime_info": False,
}


# =============================================================================
# Configuration Loading
# =============================================================================

def _find_config_file() -> Optional[Path]:
    """Find the configuration file following the search order.

    Search order:
    1. PPXAI_CONFIG_FILE environment variable (if set)
    2. ./ppxai-config.json (project-specific)
    3. ~/.ppxai/ppxai-config.json (user-specific)

    Returns:
        Path to config file if found, None otherwise.
    """
    # 1. Check environment variable
    env_config = os.getenv("PPXAI_CONFIG_FILE")
    if env_config:
        path = Path(env_config)
        if path.exists():
            return path

    # 2. Check current directory
    local_config = Path("./ppxai-config.json")
    if local_config.exists():
        return local_config

    # 3. Check user home directory
    if USER_CONFIG_FILE.exists():
        return USER_CONFIG_FILE

    return None


def _load_json_config(config_path: Path) -> Dict[str, Any]:
    """Load and parse JSON configuration file.

    Args:
        config_path: Path to the JSON config file.

    Returns:
        Parsed configuration dictionary.

    Raises:
        ValueError: If the config file is invalid.
    """
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        return config
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in config file {config_path}: {e}")
    except Exception as e:
        raise ValueError(f"Error reading config file {config_path}: {e}")


def _validate_provider_config(provider_id: str, provider: Dict[str, Any]) -> List[str]:
    """Validate a provider configuration.

    Args:
        provider_id: The provider identifier.
        provider: The provider configuration dict.

    Returns:
        List of validation error messages (empty if valid).
    """
    errors = []

    required_fields = ["name", "base_url", "api_key_env", "models"]
    for field in required_fields:
        if field not in provider:
            errors.append(f"Provider '{provider_id}' missing required field: {field}")

    if "models" in provider and not provider["models"]:
        errors.append(f"Provider '{provider_id}' has no models defined")

    return errors


def _build_legacy_custom_provider() -> Optional[Dict[str, Any]]:
    """Build a custom provider from legacy CUSTOM_* environment variables.

    This provides backward compatibility with the old .env-only configuration.

    Returns:
        Provider config dict if legacy variables are set, None otherwise.
    """
    # Check if any legacy custom variables are set
    endpoint = os.getenv("CUSTOM_MODEL_ENDPOINT")
    if not endpoint:
        return None

    model_id = os.getenv("CUSTOM_MODEL_ID", "custom-model")

    return {
        "name": os.getenv("CUSTOM_PROVIDER_NAME", "Custom Self-Hosted"),
        "base_url": endpoint,
        "api_key_env": "CUSTOM_API_KEY",
        "default_model": model_id,
        "coding_model": model_id,
        "models": {
            model_id: {
                "name": os.getenv("CUSTOM_MODEL_NAME", "Custom Model"),
                "description": os.getenv("CUSTOM_MODEL_DESC", "Self-hosted LLM model")
            },
        },
        "pricing": {
            model_id: {"input": 0.0, "output": 0.0},
        },
        "capabilities": {
            "web_search": False,
            "web_fetch": False,
            "weather": False,
            "realtime_info": False,
        },
    }


def _convert_models_format(models: Dict[str, Any]) -> Dict[str, Any]:
    """Convert models from JSON format to internal numbered format.

    JSON format: {"model-id": {"name": "...", "description": "..."}}
    Internal format: {"1": {"id": "model-id", "name": "...", "description": "..."}}

    Args:
        models: Models in JSON format.

    Returns:
        Models in internal numbered format.
    """
    numbered_models = {}
    for idx, (model_id, model_info) in enumerate(models.items(), 1):
        numbered_models[str(idx)] = {
            "id": model_id,
            "name": model_info.get("name", model_id),
            "description": model_info.get("description", ""),
        }
    return numbered_models


def load_config() -> Dict[str, Any]:
    """Load the complete configuration from JSON file and environment.

    Returns:
        Complete configuration dictionary with:
        - config_source: Path to loaded config file or "builtin"
        - default_provider: Default provider ID
        - providers: Dict of all provider configurations
    """
    config_path = _find_config_file()

    if config_path:
        # Load from JSON file
        json_config = _load_json_config(config_path)

        # Validate and process providers
        providers = {}
        validation_errors = []

        for provider_id, provider_config in json_config.get("providers", {}).items():
            errors = _validate_provider_config(provider_id, provider_config)
            if errors:
                validation_errors.extend(errors)
                continue

            # Convert models format and ensure all fields
            processed = {
                "name": provider_config["name"],
                "base_url": provider_config["base_url"],
                "api_key_env": provider_config["api_key_env"],
                "default_model": provider_config.get("default_model"),
                "coding_model": provider_config.get("coding_model", provider_config.get("default_model")),
                "models": _convert_models_format(provider_config.get("models", {})),
                "pricing": provider_config.get("pricing", {}),
                "capabilities": {**DEFAULT_CAPABILITIES, **provider_config.get("capabilities", {})},
            }

            # Set default_model to first model if not specified
            if not processed["default_model"] and processed["models"]:
                first_model = processed["models"].get("1", {})
                processed["default_model"] = first_model.get("id")
                processed["coding_model"] = processed["coding_model"] or processed["default_model"]

            providers[provider_id] = processed

        if validation_errors:
            import warnings
            for error in validation_errors:
                warnings.warn(f"Config validation: {error}")

        # Determine default provider
        default_provider = json_config.get("default_provider", "perplexity")

        # Ensure perplexity is always available as fallback
        if "perplexity" not in providers:
            providers["perplexity"] = {
                **BUILTIN_PROVIDERS["perplexity"],
                "models": _convert_models_format(BUILTIN_PROVIDERS["perplexity"]["models"]),
            }

        return {
            "config_source": str(config_path),
            "default_provider": default_provider,
            "providers": providers,
        }

    else:
        # No config file found - use builtin providers + legacy custom provider
        providers = {}
        for provider_id, provider_config in BUILTIN_PROVIDERS.items():
            providers[provider_id] = {
                **provider_config,
                "models": _convert_models_format(provider_config["models"]),
            }

        # Check for legacy custom provider
        legacy_custom = _build_legacy_custom_provider()
        if legacy_custom:
            providers["custom"] = {
                **legacy_custom,
                "models": _convert_models_format(legacy_custom["models"]),
            }

        return {
            "config_source": "builtin",
            "default_provider": "perplexity",
            "providers": providers,
        }


# =============================================================================
# Global Configuration State
# =============================================================================

# Load configuration at module import
_config = load_config()

# Active provider (can be overridden by MODEL_PROVIDER env var)
MODEL_PROVIDER = os.getenv("MODEL_PROVIDER", _config["default_provider"])

# Providers dictionary (for backward compatibility)
PROVIDERS = _config["providers"]

# Legacy compatibility exports
MODEL_PRICING = BUILTIN_PROVIDERS["perplexity"]["pricing"]
MODELS = _config["providers"].get("perplexity", {}).get("models", {})
CODING_MODEL = "sonar-pro"


# =============================================================================
# Public API Functions
# =============================================================================

def get_config_source() -> str:
    """Get the source of the current configuration.

    Returns:
        Path to config file or "builtin" if using defaults.
    """
    return _config["config_source"]


def get_available_providers() -> List[str]:
    """Get list of all available provider IDs.

    Returns:
        List of provider ID strings.
    """
    return list(PROVIDERS.keys())


def get_provider_config(provider: str = None) -> dict:
    """Get configuration for the specified provider.

    Args:
        provider: Provider ID. If None, uses active provider.

    Returns:
        Provider configuration dictionary.
    """
    if provider is None:
        provider = MODEL_PROVIDER
    return PROVIDERS.get(provider, PROVIDERS.get("perplexity", {}))


def get_active_models() -> dict:
    """Get models for the active provider.

    Returns:
        Dict of models in numbered format.
    """
    return get_provider_config()["models"]


def get_active_pricing() -> dict:
    """Get pricing for the active provider.

    Returns:
        Dict of model pricing.
    """
    return get_provider_config().get("pricing", {})


def get_api_key(provider: str = None) -> str:
    """Get API key for the specified provider from environment.

    Args:
        provider: Provider ID. If None, uses active provider.

    Returns:
        API key string (empty if not set).
    """
    config = get_provider_config(provider)
    return os.getenv(config.get("api_key_env", ""), "")


def get_base_url(provider: str = None) -> str:
    """Get base URL for the specified provider.

    Args:
        provider: Provider ID. If None, uses active provider.

    Returns:
        Base URL string.
    """
    return get_provider_config(provider).get("base_url", "")


def get_provider_capabilities(provider: str = None) -> dict:
    """Get capabilities for the specified provider.

    Capabilities indicate what the provider can do natively without tools:
    - web_search: Can search the web
    - web_fetch: Can fetch and read web pages
    - weather: Can get weather information
    - realtime_info: Has access to real-time information

    Args:
        provider: Provider ID. If None, uses active provider.

    Returns:
        Dict with capability flags (default False if not specified).
    """
    config = get_provider_config(provider)
    return config.get("capabilities", DEFAULT_CAPABILITIES)


def provider_needs_tool(provider: str, tool_category: str) -> bool:
    """Check if a provider needs a specific tool category.

    Args:
        provider: Provider name (e.g., 'perplexity', 'openai')
        tool_category: Tool category to check (e.g., 'web_search', 'weather')

    Returns:
        True if the provider needs this tool (doesn't have native capability)
    """
    capabilities = get_provider_capabilities(provider)
    # Provider needs the tool if it doesn't have the native capability
    return not capabilities.get(tool_category, False)


def get_coding_model(provider: str = None) -> str:
    """Get the best model for coding tasks for the provider.

    Args:
        provider: Provider ID. If None, uses active provider.

    Returns:
        Model ID string.
    """
    return get_provider_config(provider).get("coding_model", "")


def get_default_model(provider: str = None) -> str:
    """Get the default model for the provider.

    Args:
        provider: Provider ID. If None, uses active provider.

    Returns:
        Model ID string.
    """
    return get_provider_config(provider).get("default_model", "")


def set_active_provider(provider: str) -> bool:
    """Set the active provider.

    Args:
        provider: Provider ID to activate.

    Returns:
        True if provider was set successfully, False if provider not found.
    """
    global MODEL_PROVIDER
    if provider in PROVIDERS:
        MODEL_PROVIDER = provider
        return True
    return False


def reload_config() -> Dict[str, Any]:
    """Reload configuration from file.

    This can be used to pick up changes to the config file without restarting.

    Returns:
        The newly loaded configuration.
    """
    global _config, PROVIDERS, MODEL_PROVIDER
    _config = load_config()
    PROVIDERS = _config["providers"]
    # Re-apply MODEL_PROVIDER override if set
    env_provider = os.getenv("MODEL_PROVIDER")
    if env_provider and env_provider in PROVIDERS:
        MODEL_PROVIDER = env_provider
    elif _config["default_provider"] in PROVIDERS:
        MODEL_PROVIDER = _config["default_provider"]
    return _config


def validate_config() -> Dict[str, Any]:
    """Validate the current configuration and check API key availability.

    Returns:
        Dict with validation results:
        - valid: bool, overall validity
        - config_source: str, where config was loaded from
        - providers: dict, per-provider validation status
    """
    result = {
        "valid": True,
        "config_source": _config["config_source"],
        "providers": {},
    }

    for provider_id, provider_config in PROVIDERS.items():
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
