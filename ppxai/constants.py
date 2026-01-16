"""
Central constants module for ppxai.

This module consolidates magic strings and default values used throughout
the codebase to improve maintainability and type safety.

v1.13.11: Created as part of technical debt reduction
"""

from enum import Enum
from typing import Final


# =============================================================================
# Provider Names
# =============================================================================

class ProviderName:
    """Provider identifier constants."""
    PERPLEXITY: Final[str] = "perplexity"
    GEMINI: Final[str] = "gemini"
    OPENAI: Final[str] = "openai"
    OPENROUTER: Final[str] = "openrouter"
    LOCAL: Final[str] = "local"
    CUSTOM: Final[str] = "custom"


# =============================================================================
# Message Roles
# =============================================================================

class MessageRole:
    """Chat message role constants."""
    USER: Final[str] = "user"
    ASSISTANT: Final[str] = "assistant"
    SYSTEM: Final[str] = "system"
    TOOL: Final[str] = "tool"


# =============================================================================
# Consent Modes
# =============================================================================

class ConsentMode:
    """Consent behavior mode constants."""
    ALWAYS: Final[str] = "always"
    NEVER: Final[str] = "never"
    PROMPT: Final[str] = "prompt"


class ConsentResponse:
    """Consent response constants."""
    YES: Final[str] = "y"
    NO: Final[str] = "n"
    ALWAYS: Final[str] = "always"
    NEVER: Final[str] = "never"


# =============================================================================
# Configuration Keys
# =============================================================================

class ConfigKey:
    """Configuration dictionary key constants."""
    # Top-level keys
    PROVIDERS: Final[str] = "providers"
    TOOLS: Final[str] = "tools"
    CONTEXT: Final[str] = "context"
    SESSION: Final[str] = "session"
    SERVER: Final[str] = "server"
    TUI: Final[str] = "tui"
    PATHS: Final[str] = "paths"
    DEFAULT_PROVIDER: Final[str] = "default_provider"
    CONFIG_SOURCE: Final[str] = "config_source"

    # Provider config keys
    NAME: Final[str] = "name"
    BASE_URL: Final[str] = "base_url"
    API_KEY_ENV: Final[str] = "api_key_env"
    MODELS: Final[str] = "models"
    PRICING: Final[str] = "pricing"
    CAPABILITIES: Final[str] = "capabilities"
    DEFAULT_MODEL: Final[str] = "default_model"
    CODING_MODEL: Final[str] = "coding_model"
    SYSTEM_PROMPT: Final[str] = "system_prompt"

    # Model config keys
    CONTEXT_LIMIT: Final[str] = "context_limit"
    MAX_TOKENS: Final[str] = "max_tokens"


# =============================================================================
# System Prompt Modes
# =============================================================================

class SystemPromptMode:
    """System prompt combination mode constants."""
    PREPEND: Final[str] = "prepend"
    APPEND: Final[str] = "append"
    REPLACE: Final[str] = "replace"


# =============================================================================
# Tool Settings
# =============================================================================

class ToolSetting:
    """Tool configuration setting name constants."""
    MAX_ITERATIONS: Final[str] = "max_iterations"
    MAX_TOOL_ITERATIONS: Final[str] = "max_tool_iterations"
    AUTO_RETRY_EMPTY: Final[str] = "auto_retry_empty"
    MAX_SAME_TOOL_CALLS: Final[str] = "max_same_tool_calls"
    VERBOSE: Final[str] = "verbose"
    CONTEXT_CHAR_LIMIT: Final[str] = "context_char_limit"
    MIN_TASK_WORDS: Final[str] = "min_task_words"


# =============================================================================
# Default Values
# =============================================================================

class Default:
    """Default configuration values."""
    # Agent/tool limits
    MAX_ITERATIONS: Final[int] = 10
    MAX_TOOL_ITERATIONS: Final[int] = 15
    MAX_SAME_TOOL_CALLS: Final[int] = 3
    AUTO_RETRY_EMPTY: Final[int] = 3
    CONTEXT_CHAR_LIMIT: Final[int] = 2000
    MIN_TASK_WORDS: Final[int] = 3

    # Context limits
    CONTEXT_LIMIT: Final[int] = 128_000
    MAX_INJECTION_SIZE: Final[int] = 100_000
    CONTEXT_WARN_PERCENT: Final[int] = 80

    # Server settings
    IDLE_TIMEOUT: Final[int] = 300
    SERVER_PORT: Final[int] = 54320

    # Session settings
    AUTO_SAVE_INTERVAL: Final[int] = 1


# =============================================================================
# Shell Command Risk Levels
# =============================================================================

class ShellRiskLevel:
    """Shell command risk classification constants."""
    SAFE: Final[str] = "safe"
    DANGEROUS: Final[str] = "dangerous"
    NEVER: Final[str] = "never"


# =============================================================================
# File Encodings
# =============================================================================

class FileEncoding:
    """File encoding constants."""
    UTF8: Final[str] = "utf-8"
    UTF8_WITH_BOM: Final[str] = "utf-8-sig"


# =============================================================================
# API Endpoints (for tools that need external APIs)
# =============================================================================

class APIEndpoint:
    """External API endpoint constants."""
    PERPLEXITY_API: Final[str] = "https://api.perplexity.ai"
    WEATHER_API: Final[str] = "https://wttr.in"
    DUCKDUCKGO_SEARCH: Final[str] = "https://html.duckduckgo.com/html/"


# =============================================================================
# Checkpoint Backend Types
# =============================================================================

class CheckpointBackend:
    """Checkpoint backend type constants."""
    AUTO: Final[str] = "auto"
    GIT: Final[str] = "git"
    FILE: Final[str] = "file"
    NONE: Final[str] = "none"
