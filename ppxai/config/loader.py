"""
Configuration loading and parsing.

Handles:
- Finding config files (env var, local, user home)
- Loading JSON config with BOM handling
- Provider validation and conversion
- First-run config seeding from bundled example

v1.13.10: Extracted from config.py as part of package refactoring
v1.13.10: Removed BUILTIN_PROVIDERS - use ppxai-config.example.json instead
"""

import json
import os
import shutil
import sys
import warnings
from io import StringIO
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv


# =============================================================================
# Path Constants
# =============================================================================

PPXAI_HOME = Path.home() / ".ppxai"
SESSIONS_DIR = PPXAI_HOME / "sessions"
EXPORTS_DIR = PPXAI_HOME / "exports"
USAGE_FILE = PPXAI_HOME / "usage.json"
USER_CONFIG_FILE = PPXAI_HOME / "ppxai-config.json"

# Bundled example config (for first-run seeding)
# When running from source: project_root/ppxai-config.example.json
# When running from PyInstaller: _MEIPASS/ppxai-config.example.json
EXAMPLE_CONFIG_NAME = "ppxai-config.example.json"


# =============================================================================
# Default Capabilities (used when provider doesn't specify)
# =============================================================================

DEFAULT_CAPABILITIES = {
    "web_search": False,
    "web_fetch": False,
    "weather": False,
    "realtime_info": False,
}


# =============================================================================
# Initialization State
# =============================================================================

_initialized = False


# =============================================================================
# Environment Loading
# =============================================================================

def _load_dotenv_with_bom_handling(dotenv_path: Path) -> None:
    """Load .env file with UTF-8 BOM handling.

    python-dotenv does NOT handle UTF-8 BOM, which corrupts the first key.
    Windows PowerShell's Out-File creates files with BOM by default.
    This function strips the BOM before parsing.
    """
    if not dotenv_path.exists():
        return

    try:
        content = dotenv_path.read_text(encoding='utf-8-sig')
        load_dotenv(stream=StringIO(content))
    except Exception:
        load_dotenv(dotenv_path)


def _ensure_directories() -> None:
    """Ensure required directories exist."""
    PPXAI_HOME.mkdir(parents=True, exist_ok=True)
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    EXPORTS_DIR.mkdir(parents=True, exist_ok=True)


def _find_example_config() -> Optional[Path]:
    """Find the bundled example config file.

    Search order:
    1. PyInstaller bundle (_MEIPASS)
    2. Project root (for development)
    3. Package directory
    """
    # PyInstaller bundle
    if hasattr(sys, '_MEIPASS'):
        bundled = Path(sys._MEIPASS) / EXAMPLE_CONFIG_NAME
        if bundled.exists():
            return bundled

    # Project root (development)
    project_root = Path(__file__).parent.parent.parent / EXAMPLE_CONFIG_NAME
    if project_root.exists():
        return project_root

    # Package directory
    package_dir = Path(__file__).parent / EXAMPLE_CONFIG_NAME
    if package_dir.exists():
        return package_dir

    return None


def _seed_config_on_first_run() -> bool:
    """Seed default config on first run if no config exists.

    Returns:
        True if config was seeded, False otherwise.
    """
    if USER_CONFIG_FILE.exists():
        return False

    example_config = _find_example_config()
    if not example_config:
        return False

    try:
        _ensure_directories()
        shutil.copy(example_config, USER_CONFIG_FILE)
        print(f"\n✓ Created default config at: {USER_CONFIG_FILE}")
        print("  Edit this file to configure providers and API keys.")
        print(f"  Also create {PPXAI_HOME / '.env'} with your API keys.\n")
        return True
    except Exception as e:
        warnings.warn(f"Failed to seed default config: {e}")
        return False


def initialize() -> None:
    """Initialize the configuration system.

    This function should be called explicitly by application entry points
    (TUI, server, desktop) before using config. It:
    1. Seeds default config on first run
    2. Loads .env files
    3. Creates required directories

    Safe to call multiple times - only initializes once.
    """
    global _initialized
    if _initialized:
        return

    # Seed config on first run (before loading .env)
    _seed_config_on_first_run()

    # Load .env files
    _load_dotenv_with_bom_handling(Path.cwd() / ".env")
    _load_dotenv_with_bom_handling(PPXAI_HOME / ".env")

    # Ensure directories exist
    _ensure_directories()

    _initialized = True


# Legacy alias for backward compatibility
def initialize_environment() -> None:
    """Legacy alias for initialize(). Use initialize() instead."""
    initialize()


# =============================================================================
# Configuration File Discovery
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
    env_config = os.getenv("PPXAI_CONFIG_FILE")
    if env_config:
        path = Path(env_config)
        if path.exists():
            return path

    local_config = Path("./ppxai-config.json")
    if local_config.exists():
        return local_config

    if USER_CONFIG_FILE.exists():
        return USER_CONFIG_FILE

    return None


# =============================================================================
# Configuration Parsing
# =============================================================================

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


# =============================================================================
# Main Configuration Loading
# =============================================================================

def load_config() -> Dict[str, Any]:
    """Load the complete configuration from JSON file and environment.

    Returns:
        Complete configuration dictionary with:
        - config_source: Path to loaded config file or "builtin"
        - default_provider: Default provider ID
        - providers: Dict of all provider configurations
        - tools: Tool configuration
        - context: Context limits configuration
    """
    config_path = find_config_file()

    if config_path:
        json_config = _load_json_config(config_path)

        providers = {}
        validation_errors = []

        for provider_id, provider_config in json_config.get("providers", {}).items():
            errors = _validate_provider_config(provider_id, provider_config)
            if errors:
                validation_errors.extend(errors)
                continue

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

            if not processed["default_model"] and processed["models"]:
                first_model = processed["models"].get("1", {})
                processed["default_model"] = first_model.get("id")
                processed["coding_model"] = processed["coding_model"] or processed["default_model"]

            providers[provider_id] = processed

        if validation_errors:
            for error in validation_errors:
                warnings.warn(f"Config validation: {error}")

        default_provider = json_config.get("default_provider")

        # If no default_provider specified, use first provider in config
        if not default_provider and providers:
            default_provider = next(iter(providers.keys()))

        return {
            "config_source": str(config_path),
            "default_provider": default_provider,
            "providers": providers,
            "tools": json_config.get("tools", {}),
            "context": json_config.get("context", {}),
        }

    else:
        # No config file found - check for legacy environment variables
        legacy_custom = _build_legacy_custom_provider()
        if legacy_custom:
            return {
                "config_source": "legacy_env",
                "default_provider": "custom",
                "providers": {
                    "custom": {
                        **legacy_custom,
                        "models": _convert_models_format(legacy_custom["models"]),
                    }
                },
                "tools": {},
                "context": {},
            }

        # No config at all - return empty config with clear indicator
        # The application should handle this and guide the user
        return {
            "config_source": "none",
            "default_provider": None,
            "providers": {},
            "tools": {},
            "context": {},
        }
