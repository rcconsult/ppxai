"""
Configuration and constants for the ppxai application.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env file from the current working directory (standard behavior)
# This allows users to place .env in their project root
load_dotenv()

# Directories for data storage
SESSIONS_DIR = Path.home() / ".ppxai" / "sessions"
EXPORTS_DIR = Path.home() / ".ppxai" / "exports"
USAGE_FILE = Path.home() / ".ppxai" / "usage.json"

# Ensure directories exist
SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
EXPORTS_DIR.mkdir(parents=True, exist_ok=True)

# Perplexity API pricing (per million tokens) - approximate values
# Source: https://docs.perplexity.ai/guides/pricing
MODEL_PRICING = {
    "sonar": {"input": 0.20, "output": 0.20},
    "sonar-pro": {"input": 3.00, "output": 15.00},
    "sonar-reasoning": {"input": 1.00, "output": 5.00},
    "sonar-reasoning-pro": {"input": 5.00, "output": 15.00},
    "sonar-deep-research": {"input": 5.00, "output": 15.00},
}

# Available Perplexity models
MODELS = {
    "1": {
        "id": "sonar",
        "name": "Sonar",
        "description": "Lightweight search model with real-time grounding"
    },
    "2": {
        "id": "sonar-pro",
        "name": "Sonar Pro",
        "description": "Advanced search model for complex queries"
    },
    "3": {
        "id": "sonar-reasoning",
        "name": "Sonar Reasoning",
        "description": "Fast reasoning model for problem-solving with search"
    },
    "4": {
        "id": "sonar-reasoning-pro",
        "name": "Sonar Reasoning Pro",
        "description": "Precision reasoning with Chain of Thought capabilities"
    },
    "5": {
        "id": "sonar-deep-research",
        "name": "Sonar Deep Research",
        "description": "Exhaustive research with comprehensive reports"
    },
}

# Best model for coding tasks (using Sonar Pro for advanced reasoning)
CODING_MODEL = "sonar-pro"

# =============================================================================
# Provider Configuration
# =============================================================================

# Active provider: "perplexity" or "custom"
MODEL_PROVIDER = os.getenv("MODEL_PROVIDER", "perplexity")

# Provider configurations
PROVIDERS = {
    "perplexity": {
        "name": "Perplexity AI",
        "base_url": "https://api.perplexity.ai",
        "api_key_env": "PERPLEXITY_API_KEY",
        "models": {
            "1": {
                "id": "sonar",
                "name": "Sonar",
                "description": "Lightweight search model with real-time grounding"
            },
            "2": {
                "id": "sonar-pro",
                "name": "Sonar Pro",
                "description": "Advanced search model for complex queries"
            },
            "3": {
                "id": "sonar-reasoning",
                "name": "Sonar Reasoning",
                "description": "Fast reasoning model for problem-solving with search"
            },
            "4": {
                "id": "sonar-reasoning-pro",
                "name": "Sonar Reasoning Pro",
                "description": "Precision reasoning with Chain of Thought capabilities"
            },
            "5": {
                "id": "sonar-deep-research",
                "name": "Sonar Deep Research",
                "description": "Exhaustive research with comprehensive reports"
            },
        },
        "pricing": {
            "sonar": {"input": 0.20, "output": 0.20},
            "sonar-pro": {"input": 3.00, "output": 15.00},
            "sonar-reasoning": {"input": 1.00, "output": 5.00},
            "sonar-reasoning-pro": {"input": 5.00, "output": 15.00},
            "sonar-deep-research": {"input": 5.00, "output": 15.00},
        },
        "default_model": "sonar-pro",
        "coding_model": "sonar-pro",
        # Capabilities define what the provider can do natively (without tools)
        "capabilities": {
            "web_search": True,  # Perplexity has built-in web search
            "web_fetch": True,   # Can fetch URLs via search
            "weather": True,     # Can get weather via search
            "realtime_info": True,  # Has access to real-time information
        },
    },
    "custom": {
        "name": os.getenv("CUSTOM_PROVIDER_NAME", "Custom Self-Hosted"),
        "base_url": os.getenv("CUSTOM_MODEL_ENDPOINT", "http://localhost:8000/v1"),
        "api_key_env": "CUSTOM_API_KEY",
        "models": {
            "1": {
                "id": os.getenv("CUSTOM_MODEL_ID", "gpt-oss-120b"),
                "name": os.getenv("CUSTOM_MODEL_NAME", "GPT OSS 120B"),
                "description": os.getenv("CUSTOM_MODEL_DESC", "Self-hosted LLM model via vLLM")
            },
        },
        "pricing": {
            # Self-hosted models typically have no per-token cost (infrastructure cost only)
            os.getenv("CUSTOM_MODEL_ID", "gpt-oss-120b"): {"input": 0.0, "output": 0.0},
        },
        "default_model": os.getenv("CUSTOM_MODEL_ID", "gpt-oss-120b"),
        "coding_model": os.getenv("CUSTOM_MODEL_ID", "gpt-oss-120b"),
        # Self-hosted models don't have internet access - they need tools
        "capabilities": {
            "web_search": False,  # Needs web_search tool
            "web_fetch": False,   # Needs fetch_url tool
            "weather": False,     # Needs get_weather tool
            "realtime_info": False,  # No real-time info without tools
        },
    },
}


def get_provider_config(provider: str = None) -> dict:
    """Get configuration for the specified provider."""
    if provider is None:
        provider = MODEL_PROVIDER
    return PROVIDERS.get(provider, PROVIDERS["perplexity"])


def get_active_models() -> dict:
    """Get models for the active provider."""
    return get_provider_config()["models"]


def get_active_pricing() -> dict:
    """Get pricing for the active provider."""
    return get_provider_config()["pricing"]


def get_api_key(provider: str = None) -> str:
    """Get API key for the specified provider from environment."""
    config = get_provider_config(provider)
    return os.getenv(config["api_key_env"], "")


def get_base_url(provider: str = None) -> str:
    """Get base URL for the specified provider."""
    return get_provider_config(provider)["base_url"]


def get_provider_capabilities(provider: str = None) -> dict:
    """Get capabilities for the specified provider.

    Capabilities indicate what the provider can do natively without tools:
    - web_search: Can search the web
    - web_fetch: Can fetch and read web pages
    - weather: Can get weather information
    - realtime_info: Has access to real-time information

    Returns dict with capability flags (default False if not specified).
    """
    config = get_provider_config(provider)
    default_capabilities = {
        "web_search": False,
        "web_fetch": False,
        "weather": False,
        "realtime_info": False,
    }
    return config.get("capabilities", default_capabilities)


def provider_needs_tool(provider: str, tool_category: str) -> bool:
    """Check if a provider needs a specific tool category.

    Args:
        provider: Provider name (e.g., 'perplexity', 'custom')
        tool_category: Tool category to check (e.g., 'web_search', 'weather')

    Returns:
        True if the provider needs this tool (doesn't have native capability)
    """
    capabilities = get_provider_capabilities(provider)
    # Provider needs the tool if it doesn't have the native capability
    return not capabilities.get(tool_category, False)


def get_coding_model(provider: str = None) -> str:
    """Get the best model for coding tasks for the provider."""
    return get_provider_config(provider)["coding_model"]
