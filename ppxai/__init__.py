"""
ppxai - Perplexity AI Text UI Application

A terminal-based interface for interacting with Perplexity AI models.
"""

from .config import (
    SESSIONS_DIR,
    EXPORTS_DIR,
    USAGE_FILE,
    MODEL_PRICING,
    MODELS,
    CODING_MODEL,
)
from .client import PerplexityClient
from .prompts import CODING_PROMPTS, SPEC_GUIDELINES, SPEC_TEMPLATES
from .ui import (
    console,
    display_welcome,
    display_spec_help,
    display_models,
    select_model,
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
    # Client
    "PerplexityClient",
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

__version__ = "1.0.0"
