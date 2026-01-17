"""
Central constants module for ppxai.

This module consolidates magic strings and default values used throughout
the codebase to improve maintainability and type safety.

String enums use `str, Enum` pattern for:
- Type safety with IDE autocompletion
- Seamless string comparison (no .value needed)
- Validation via is_valid_*() helpers

v1.13.10: Created as part of technical debt reduction
v1.13.11: Converted to str, Enum with validation helpers
"""

from enum import Enum
from typing import Final, Type, TypeVar

T = TypeVar('T', bound=Enum)


# =============================================================================
# Validation Helpers
# =============================================================================

def is_valid_enum(enum_class: Type[T], value: str) -> bool:
    """Check if value is a valid member of the enum.

    Args:
        enum_class: The enum class to check against
        value: String value to validate

    Returns:
        True if value matches an enum member's value
    """
    return value in {e.value for e in enum_class}


def get_enum_values(enum_class: Type[T]) -> set[str]:
    """Get all valid values for an enum class.

    Args:
        enum_class: The enum class

    Returns:
        Set of all valid string values
    """
    return {e.value for e in enum_class}


# =============================================================================
# Provider Names
# =============================================================================

class ProviderName(str, Enum):
    """Provider identifier constants."""
    PERPLEXITY = "perplexity"
    GEMINI = "gemini"
    OPENAI = "openai"
    OPENROUTER = "openrouter"
    LOCAL = "local"
    CUSTOM = "custom"


def is_valid_provider(value: str) -> bool:
    """Check if value is a valid provider name."""
    return is_valid_enum(ProviderName, value)


# =============================================================================
# Message Roles
# =============================================================================

class MessageRole(str, Enum):
    """Chat message role constants."""
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"


def is_valid_role(value: str) -> bool:
    """Check if value is a valid message role."""
    return is_valid_enum(MessageRole, value)


# =============================================================================
# Consent Modes
# =============================================================================

class ConsentMode(str, Enum):
    """Consent behavior mode constants."""
    ALWAYS = "always"
    NEVER = "never"
    PROMPT = "prompt"


def is_valid_consent_mode(value: str) -> bool:
    """Check if value is a valid consent mode."""
    return is_valid_enum(ConsentMode, value)


class ConsentResponse(str, Enum):
    """Consent response constants - user input values.

    Used for validating user input at consent prompts.
    Accepts short forms: "y", "n" and long forms: "always", "never"
    """
    YES = "y"
    NO = "n"
    ALWAYS = "always"
    NEVER = "never"


def is_valid_consent_response(value: str) -> bool:
    """Check if value is a valid consent response."""
    return is_valid_enum(ConsentResponse, value)


class ConsentDecision(str, Enum):
    """Consent decision constants - internal state values.

    Used for tracking consent decisions internally.
    Uses long forms: "yes", "no", "always", "never"
    """
    YES = "yes"
    NO = "no"
    ALWAYS = "always"
    NEVER = "never"


def is_valid_consent_decision(value: str) -> bool:
    """Check if value is a valid consent decision."""
    return is_valid_enum(ConsentDecision, value)


# =============================================================================
# Configuration Keys (not enums - used as dictionary keys)
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

class SystemPromptMode(str, Enum):
    """System prompt combination mode constants."""
    PREPEND = "prepend"
    APPEND = "append"
    REPLACE = "replace"


def is_valid_prompt_mode(value: str) -> bool:
    """Check if value is a valid system prompt mode."""
    return is_valid_enum(SystemPromptMode, value)


# =============================================================================
# Tool Settings (not enums - used as dictionary keys)
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
# Default Values (not enums - integer values)
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

class ShellRiskLevel(str, Enum):
    """Shell command risk classification constants."""
    SAFE = "safe"
    DANGEROUS = "dangerous"
    NEVER = "never"


def is_valid_risk_level(value: str) -> bool:
    """Check if value is a valid shell risk level."""
    return is_valid_enum(ShellRiskLevel, value)


# =============================================================================
# File Encodings
# =============================================================================

class FileEncoding(str, Enum):
    """File encoding constants."""
    UTF8 = "utf-8"
    UTF8_WITH_BOM = "utf-8-sig"


def is_valid_encoding(value: str) -> bool:
    """Check if value is a valid file encoding."""
    return is_valid_enum(FileEncoding, value)


# =============================================================================
# API Endpoints (not enums - URLs don't benefit from enum semantics)
# =============================================================================

class APIEndpoint:
    """External API endpoint constants."""
    PERPLEXITY_API: Final[str] = "https://api.perplexity.ai"
    WEATHER_API: Final[str] = "https://wttr.in"
    DUCKDUCKGO_SEARCH: Final[str] = "https://html.duckduckgo.com/html/"


# =============================================================================
# Checkpoint Backend Types
# =============================================================================

class CheckpointBackend(str, Enum):
    """Checkpoint backend type constants."""
    AUTO = "auto"
    GIT = "git"
    FILE = "file"
    NONE = "none"


def is_valid_checkpoint_backend(value: str) -> bool:
    """Check if value is a valid checkpoint backend."""
    return is_valid_enum(CheckpointBackend, value)
