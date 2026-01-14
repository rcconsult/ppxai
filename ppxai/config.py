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
from io import StringIO
from pathlib import Path
from typing import Dict, List, Optional, Any
from dotenv import load_dotenv


def _load_dotenv_with_bom_handling(dotenv_path: Path) -> None:
    """Load .env file with UTF-8 BOM handling.

    python-dotenv does NOT handle UTF-8 BOM, which corrupts the first key.
    Windows PowerShell's Out-File creates files with BOM by default.
    This function strips the BOM before parsing.
    """
    if not dotenv_path.exists():
        return

    try:
        # Read with utf-8-sig to automatically strip BOM
        content = dotenv_path.read_text(encoding='utf-8-sig')
        # Load from string stream instead of file
        load_dotenv(stream=StringIO(content))
    except Exception:
        # Fallback to standard loading if anything goes wrong
        load_dotenv(dotenv_path)


# Load .env files in priority order:
# 1. Current working directory (project-specific)
# 2. ~/.ppxai/.env (user-specific, for standalone binaries)
# Later loads don't override existing environment variables
# Use BOM-safe loading for Windows PowerShell compatibility
_load_dotenv_with_bom_handling(Path.cwd() / ".env")
_load_dotenv_with_bom_handling(Path.home() / ".ppxai" / ".env")

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
            "gemini-2.5-flash-lite": {
                "name": "Gemini 2.5 Flash Lite",
                "description": "For simple tasks that need to be done quickly"
            },
            "gemini-2.5-pro": {
                "name": "Gemini 2.5 Pro",
                "description": "Most capable model for complex reasoning"
            },
            "gemini-3-flash-preview": {
                "name": "Gemini 3 Flash Preview",
                "description": "Speed-optimized preview with frontier intelligence and 1M context"
            },
            "gemini-3-pro-preview": {
                "name": "Gemini 3 Pro Preview",
                "description": "Most powerful agentic model with 1M context, code execution, and search grounding"
            },
        },
        "pricing": {
            # Prices per million tokens (2025)
            "gemini-2.0-flash": {"input": 0.10, "output": 0.40},
            "gemini-2.0-flash-lite": {"input": 0.075, "output": 0.30},
            "gemini-2.5-flash": {"input": 0.15, "output": 0.60},
            "gemini-2.5-flash-lite": {"input": 0.075, "output": 0.30},
            "gemini-2.5-pro": {"input": 1.25, "output": 5.00},
            "gemini-3-flash-preview": {"input": 0.15, "output": 0.60},  # Estimated, preview pricing
            "gemini-3-pro-preview": {"input": 1.25, "output": 5.00},  # Estimated, preview pricing
        },
        "capabilities": {
            "web_search": True,
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

def find_config_file() -> Optional[Path]:
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
        # Use utf-8-sig to handle UTF-8 BOM (PowerShell on Windows may add BOM)
        with open(config_path, 'r', encoding='utf-8-sig') as f:
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
    config_path = find_config_file()

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
            "tools": json_config.get("tools", {}),  # v1.11.2: Include tools configuration
            "context": json_config.get("context", {}),  # v1.13.9: Context limits
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
            "tools": {},  # v1.11.2: No tools config when using builtin
            "context": {},  # v1.13.9: No context config when using builtin
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


def get_model_pricing(provider: str = None) -> dict:
    """Get pricing for the specified provider.

    Args:
        provider: Provider ID. If None, uses active provider.

    Returns:
        Dict of model pricing.
    """
    return get_provider_config(provider).get("pricing", {})


def calculate_cost(prompt_tokens: int, completion_tokens: int, model: str, provider: str = None) -> float:
    """Calculate estimated cost in USD for token usage.

    Args:
        prompt_tokens: Number of input tokens
        completion_tokens: Number of output tokens
        model: Model ID used
        provider: Provider ID. If None, uses active provider.

    Returns:
        Estimated cost in USD (0.0 if pricing not available)
    """
    pricing = get_model_pricing(provider)
    model_pricing = pricing.get(model, {})

    if not model_pricing:
        return 0.0

    # Prices are per million tokens
    input_price = model_pricing.get("input", 0.0)
    output_price = model_pricing.get("output", 0.0)

    input_cost = (prompt_tokens / 1_000_000) * input_price
    output_cost = (completion_tokens / 1_000_000) * output_price

    return input_cost + output_cost


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


def get_tool_config(tool_name: str) -> Dict[str, Any]:
    """Get configuration for a specific tool.

    Args:
        tool_name: Tool name (e.g., 'web_search', 'shell')

    Returns:
        Tool configuration dict, or empty dict if not configured
    """
    tools_config = _config.get("tools", {})
    return tools_config.get(tool_name, {})


def get_tool_description_overrides(provider: str = None, model: str = None) -> Dict[str, str]:
    """Get tool description overrides from config (v1.13.11).

    Allows customizing tool descriptions per provider/model to optimize
    tool selection accuracy for different models.

    Config structure:
    ```json
    {
      "tools": {
        "overrides": {
          "search_files": "Find files by glob pattern (*.py, test*)"
        },
        "provider_overrides": {
          "ollama": {
            "search_files": "Search for files using patterns like *.py"
          }
        },
        "model_overrides": {
          "qwen2.5-coder:0.5b": {
            "search_files": "Find files by pattern"
          }
        }
      }
    }
    ```

    Priority order (highest to lowest):
    1. model_overrides[model][tool]
    2. provider_overrides[provider][tool]
    3. overrides[tool]
    4. Default tool description (not returned here)

    Args:
        provider: Provider name (e.g., 'ollama', 'perplexity')
        model: Model name (e.g., 'qwen2.5-coder:0.5b')

    Returns:
        Dict mapping tool names to description overrides
    """
    tools_config = _config.get("tools", {})
    result = {}

    # Layer 1: Global overrides
    global_overrides = tools_config.get("overrides", {})
    result.update(global_overrides)

    # Layer 2: Provider-specific overrides
    if provider:
        provider_overrides = tools_config.get("provider_overrides", {}).get(provider, {})
        result.update(provider_overrides)

    # Layer 3: Model-specific overrides (highest priority)
    if model:
        model_overrides = tools_config.get("model_overrides", {}).get(model, {})
        result.update(model_overrides)

    return result


def get_shell_config() -> Dict[str, Any]:
    """Get shell tool configuration with defaults (v1.13.6).

    Returns:
        Shell config dict with:
        - require_consent: bool (default True)
        - dangerous_commands: list of regex patterns
        - allowed_commands: list of regex patterns
        - never_allow: list of regex patterns
        - interactive_commands: list of commands that need TTY
        - non_interactive_with_args: list of commands that are non-interactive when given args
    """
    shell_config = get_tool_config("shell")

    # Default interactive commands (always blocked without args)
    default_interactive = [
        'nano', 'vim', 'vi', 'emacs', 'pico', 'joe',  # Text editors
        'less', 'more',  # Pagers
        'top', 'htop', 'btop',  # System monitors
        'python', 'python3', 'ipython', 'node', 'irb', 'ruby',  # REPLs
        'ssh', 'telnet', 'ftp', 'sftp',  # Remote connections
        'mysql', 'psql', 'mongo', 'redis-cli',  # Database CLIs
        'bash', 'zsh', 'sh', 'fish', 'csh', 'tcsh',  # Shells
    ]

    # Commands that become non-interactive when given arguments
    default_non_interactive_with_args = [
        'python', 'python3', 'ipython', 'node', 'irb', 'ruby',  # REPLs
        'bash', 'zsh', 'sh', 'fish', 'csh', 'tcsh',  # Shells
        'ssh',  # ssh host command runs non-interactively
        'mysql', 'psql',  # mysql -e 'query', psql -c 'query'
    ]

    return {
        "require_consent": shell_config.get("require_consent", True),
        "dangerous_commands": shell_config.get("dangerous_commands", []),
        "allowed_commands": shell_config.get("allowed_commands", []),
        "never_allow": shell_config.get("never_allow", []),
        "sandboxed_paths": shell_config.get("sandboxed_paths", []),
        "interactive_commands": shell_config.get("interactive_commands", default_interactive),
        "non_interactive_with_args": shell_config.get("non_interactive_with_args", default_non_interactive_with_args),
    }


def get_visualization_config() -> Dict[str, Any]:
    """Get data visualization configuration (v1.13.8).

    Returns:
        Visualization config dict with:
        - max_rows: Maximum rows to load for CSV/TSV (default: 10000)
        - max_columns: Maximum columns to display (default: 50)
        - page_size: Rows per page in TUI table view (default: 50)
        - tree_depth: Initial expansion depth for JSON/YAML trees (default: 3)
        - auto_detect: Auto-detect format from content (default: True)
        - csv_delimiter: CSV delimiter ('auto', ',', '\\t', ';', '|') (default: 'auto')
        - theme: Color theme ('default', 'monochrome') (default: 'default')
    """
    config = load_config()
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
    """Get container tools configuration (v1.13.8).

    Returns:
        Container config dict with:
        - enabled: Enable container tools (default: True)
        - require_consent: Require consent for destructive operations (default: True)
        - default_runtime: Container runtime ('auto', 'docker', 'podman') (default: 'auto')
        - timeout: Command timeout in seconds (default: 60)
    """
    tool_config = get_tool_config("container")

    return {
        "enabled": tool_config.get("enabled", True),
        "require_consent": tool_config.get("require_consent", True),
        "default_runtime": tool_config.get("default_runtime", "auto"),
        "timeout": tool_config.get("timeout", 60),
    }


def get_tool_pricing(tool_name: str, provider: str) -> Dict[str, Any]:
    """Get pricing configuration for a tool provider.

    Args:
        tool_name: Tool name (e.g., 'web_search')
        provider: Provider name (e.g., 'perplexity', 'gemini')

    Returns:
        Pricing dict with rates, or empty dict if not configured
    """
    tool_config = get_tool_config(tool_name)
    pricing = tool_config.get("pricing", {})
    return pricing.get(provider, {})


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


def get_default_provider() -> str:
    """Get the default provider from environment or configuration.

    Checks in order:
    1. DEFAULT_PROVIDER environment variable
    2. First available provider from config/built-ins
    3. Falls back to "perplexity"

    Returns:
        Provider ID string.
    """
    # Check environment variable first
    env_provider = os.getenv("DEFAULT_PROVIDER")
    if env_provider:
        return env_provider

    # Get first available provider from config
    available = get_available_providers()
    if available:
        return available[0]

    # Fallback to perplexity
    return "perplexity"


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


# =============================================================================
# TUI Configuration (v1.12.0 - Enhanced TUI Experiment)
# =============================================================================

def get_tui_config() -> Dict[str, Any]:
    """Get TUI-specific configuration.

    Reads from ppxai-config.json under the "tui" key:
    {
        "tui": {
            "theme": "standard",  // or "tron-legacy", "matrix", "nord"
            "show_version": true,
            "show_cwd": true,
            "show_datetime": false
        }
    }

    Returns:
        Dict with TUI configuration options.
    """
    defaults = {
        "theme": "standard",
        "show_version": True,
        "show_cwd": True,
        "show_datetime": False,
    }

    # Check if config has tui section
    tui_config = _config.get("tui", {})

    # Merge with defaults
    return {**defaults, **tui_config}


def get_tui_theme() -> str:
    """Get the configured TUI theme name.

    Returns:
        Theme name string (e.g., "standard", "tron-legacy").
    """
    return get_tui_config().get("theme", "standard")


def set_tui_config(key: str, value: Any) -> bool:
    """Set a TUI configuration value and save to config file.

    Args:
        key: Configuration key (e.g., "show_datetime", "theme")
        value: Value to set

    Returns:
        True if saved successfully, False otherwise.
    """
    import json

    # Find or create config file path
    config_path = find_config_file()
    if config_path is None:
        # Create user config file
        config_path = USER_CONFIG_FILE
        config_path.parent.mkdir(parents=True, exist_ok=True)

    # Load existing config or create empty
    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8-sig") as f:
                config_data = json.load(f)
        except (json.JSONDecodeError, IOError):
            config_data = {}
    else:
        config_data = {}

    # Ensure tui section exists
    if "tui" not in config_data:
        config_data["tui"] = {}

    # Set the value
    config_data["tui"][key] = value

    # Save config file
    try:
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config_data, f, indent=2)

        # Update in-memory config
        global _config
        if "tui" not in _config:
            _config["tui"] = {}
        _config["tui"][key] = value

        return True
    except IOError:
        return False


# =============================================================================
# Session Configuration (v1.13.9 - Session persistence and auto-recovery)
# =============================================================================

def get_session_config() -> Dict[str, Any]:
    """Get session-specific configuration.

    Reads from ppxai-config.json under the "session" key:
    {
        "session": {
            "auto_restore": "prompt",  // "always", "prompt", "never"
            "auto_save_interval": 1    // save after N messages (0=every message)
        }
    }

    auto_restore modes:
        - "always": Automatically restore last session on startup
        - "prompt": Ask user whether to restore (default)
        - "never": Always start fresh session

    Returns:
        Dict with session configuration options.
    """
    defaults = {
        "auto_restore": "prompt",  # Default: ask user
        "auto_save_interval": 1,   # Save after every message
    }

    # Get config, merge with defaults
    session_config = _config.get("session", {})
    return {**defaults, **session_config}


def get_auto_restore_mode() -> str:
    """Get the auto-restore mode for sessions.

    Returns:
        One of "always", "prompt", "never"
    """
    mode = get_session_config().get("auto_restore", "prompt")
    if mode not in ("always", "prompt", "never"):
        return "prompt"
    return mode


def get_auto_save_interval() -> int:
    """Get the auto-save interval (number of messages between saves).

    Returns:
        Number of messages between auto-saves (0 = every message)
    """
    interval = get_session_config().get("auto_save_interval", 1)
    return max(0, int(interval))


# =============================================================================
# Paths Configuration (v1.13.2 - Cross-platform binary discovery)
# =============================================================================

def _expand_path_template(template: str) -> str:
    """Expand path template variables.

    Supports:
        {home} - User's home directory
        {platform} - Platform name (win32, darwin, linux)

    Args:
        template: Path string with optional {home} and {platform} placeholders

    Returns:
        Expanded path string
    """
    import platform
    return template.replace("{home}", str(Path.home())).replace("{platform}", platform.system().lower())


def get_paths_config() -> Dict[str, Any]:
    """Get paths configuration for binary and data locations.

    Reads from ppxai-config.json under the "paths" key:
    {
        "paths": {
            "bin_search_paths": ["{home}/.ppxai/bin", ...],
            "data_dir": "{home}/.ppxai"
        }
    }

    Returns:
        Dict with expanded paths (templates like {home} are resolved).
    """
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

    # Get config, merge with defaults
    paths_config = _config.get("paths", {})
    merged = {**defaults, **paths_config}

    # Expand templates
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
    """Get list of directories to search for ppxai binaries.

    Returns:
        List of expanded directory paths to search.
    """
    return get_paths_config().get("bin_search_paths", [])


def get_data_dir() -> Path:
    """Get the data directory for sessions, exports, etc.

    Returns:
        Path to data directory.
    """
    return Path(get_paths_config().get("data_dir", str(Path.home() / ".ppxai")))


# =============================================================================
# Server Configuration (v1.14.0 - Idle shutdown)
# =============================================================================

def get_server_config() -> Dict[str, Any]:
    """Get server-specific configuration.

    Reads from ppxai-config.json under the "server" key:
    {
        "server": {
            "idle_timeout": 300,  // Shutdown after N seconds of inactivity (0 = disabled)
            "port": 54320
        }
    }

    Returns:
        Dict with server configuration options.
    """
    defaults = {
        "idle_timeout": 300,  # 5 minutes, 0 = disabled
        "port": 54320,
    }

    # Check if config has server section
    server_config = _config.get("server", {})

    # Merge with defaults
    return {**defaults, **server_config}


def get_idle_timeout() -> int:
    """Get the server idle timeout in seconds.

    Returns:
        Idle timeout in seconds (0 = disabled).
    """
    return get_server_config().get("idle_timeout", 300)


# =============================================================================
# System Prompt Configuration (v1.13.6)
# =============================================================================

# Default system prompts for each provider type
# These provide sensible defaults to reduce chattiness and improve tool usage
DEFAULT_SYSTEM_PROMPTS = {
    # Global default - applies to all providers unless overridden
    "global": (
        "You are a helpful AI assistant. Be concise and direct in your responses. "
        "When using tools, report results briefly without unnecessary elaboration."
    ),
    # Provider-specific defaults
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


def get_system_prompt(provider: str = None) -> str:
    """Get the system prompt for the specified provider.

    System prompts are configured in ppxai-config.json:
    {
        "system_prompt": "Global default prompt...",  // Optional global override
        "providers": {
            "custom": {
                "system_prompt": "Provider-specific prompt...",  // Per-provider override
                ...
            }
        }
    }

    Priority order (highest first):
    1. Provider-specific system_prompt in config
    2. Global system_prompt in config
    3. DEFAULT_SYSTEM_PROMPTS for the provider
    4. DEFAULT_SYSTEM_PROMPTS["global"]

    Args:
        provider: Provider ID. If None, uses active provider.

    Returns:
        System prompt string.
    """
    if provider is None:
        provider = MODEL_PROVIDER

    config_path = find_config_file()
    if config_path:
        json_config = _load_json_config(config_path)

        # Check provider-specific system_prompt
        provider_config = json_config.get("providers", {}).get(provider, {})
        if provider_config.get("system_prompt"):
            return provider_config["system_prompt"]

        # Check global system_prompt
        if json_config.get("system_prompt"):
            return json_config["system_prompt"]

    # Fall back to defaults
    return DEFAULT_SYSTEM_PROMPTS.get(provider, DEFAULT_SYSTEM_PROMPTS["global"])


def get_system_prompt_mode(provider: str = None) -> str:
    """Get the system prompt mode for the specified provider.

    Modes:
    - "prepend" (default): Add custom prompt before tool instructions
    - "append": Add custom prompt after tool instructions
    - "replace": Use custom prompt only, no tool instructions

    Args:
        provider: Provider ID. If None, uses active provider.

    Returns:
        System prompt mode string.
    """
    if provider is None:
        provider = MODEL_PROVIDER

    config_path = find_config_file()
    if config_path:
        json_config = _load_json_config(config_path)

        # Check provider-specific mode
        provider_config = json_config.get("providers", {}).get(provider, {})
        if provider_config.get("system_prompt_mode"):
            return provider_config["system_prompt_mode"]

        # Check global mode
        if json_config.get("system_prompt_mode"):
            return json_config["system_prompt_mode"]

    return "prepend"  # Default mode


# =============================================================================
# Context Configuration (v1.13.9 - Configurable context limits)
# =============================================================================

# Default context limits
DEFAULT_MAX_INJECTION_SIZE = 100_000  # 100KB per @file/@git/@tree
DEFAULT_CONTEXT_LIMIT = 128_000  # 128K tokens default
DEFAULT_CONTEXT_WARN_PERCENT = 80  # Warn at 80% usage


def get_context_config() -> Dict[str, Any]:
    """Get context and truncation configuration.

    Reads from ppxai-config.json under the "context" key:
    {
        "context": {
            "max_injection_size": 100000,   // Max chars per @file/@git/@tree
            "default_context_limit": 128000, // Default model context in tokens
            "warn_at_percent": 80           // Warn when exceeding this %
        }
    }

    Returns:
        Dict with context configuration options.
    """
    defaults = {
        "max_injection_size": DEFAULT_MAX_INJECTION_SIZE,
        "default_context_limit": DEFAULT_CONTEXT_LIMIT,
        "warn_at_percent": DEFAULT_CONTEXT_WARN_PERCENT,
    }

    # Get config, merge with defaults
    context_config = _config.get("context", {})
    return {**defaults, **context_config}


def get_max_injection_size() -> int:
    """Get the maximum size (in chars) for @file/@git/@tree injections.

    Returns:
        Max injection size in characters.
    """
    return get_context_config().get("max_injection_size", DEFAULT_MAX_INJECTION_SIZE)


def get_default_context_limit() -> int:
    """Get the default model context limit in tokens.

    This is used when a model doesn't have a specific context_limit set.

    Returns:
        Context limit in tokens.
    """
    return get_context_config().get("default_context_limit", DEFAULT_CONTEXT_LIMIT)


def get_context_warn_percent() -> int:
    """Get the percentage threshold for context usage warnings.

    Returns:
        Warning threshold percentage (0-100, 0 = disabled).
    """
    return get_context_config().get("warn_at_percent", DEFAULT_CONTEXT_WARN_PERCENT)


def get_model_context_limit(provider: str = None, model: str = None) -> int:
    """Get the context limit for a specific model.

    Checks in order:
    1. Model-specific context_limit in provider config
    2. Default context_limit from context config
    3. Built-in default (128K tokens)

    Args:
        provider: Provider ID. If None, uses active provider.
        model: Model ID. If None, uses provider's default model.

    Returns:
        Context limit in tokens.
    """
    if provider is None:
        provider = MODEL_PROVIDER

    if model is None:
        model = get_default_model(provider)

    # Try to get model-specific context_limit from config file
    config_path = find_config_file()
    if config_path:
        json_config = _load_json_config(config_path)
        provider_config = json_config.get("providers", {}).get(provider, {})
        models = provider_config.get("models", {})
        model_config = models.get(model, {})

        if "context_limit" in model_config:
            return model_config["context_limit"]

    # Fall back to default
    return get_default_context_limit()
