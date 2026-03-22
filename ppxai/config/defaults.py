"""
Default configuration values for tools and agent.

This is a LEAF MODULE - no ppxai imports allowed.
Provides centralized default constants that can be overridden by user config.
"""

from typing import List


# =============================================================================
# Shell Tool Defaults
# =============================================================================

# Commands that require user confirmation (regex patterns)
DEFAULT_DANGEROUS_COMMANDS: List[str] = [
    r"^rm\s+",
    r"^mv\s+",
    r"^dd\s+",
    r"^chmod\s+",
    r"^chown\s+",
    r"^sudo\s+",
    r"^curl.*\|.*bash",
    r"^wget.*\|.*bash",
    r">\s*/dev/",
    r"^kill\s+",
    r"^pkill\s+",
    r"^killall\s+",
]

# Commands that are NEVER allowed (blocked immediately)
DEFAULT_NEVER_ALLOW: List[str] = [
    r"rm\s+-rf\s+/",
    r"dd\s+.*of=/dev/",
    r":\(\)\{\s*:\|:&\s*\};:",  # Fork bomb
    r"mkfs\.",
    r"^\s*>\s*/dev/sda",
]

# Commands that are always safe (auto-approved)
DEFAULT_ALLOWED_COMMANDS: List[str] = [
    r"^ls\s+",
    r"^cat\s+(?!.*[><])",  # cat without redirection
    r"^grep\s+",
    r"^echo\s+(?!.*>)",  # echo without redirection
    r"^pwd$",
    r"^which\s+",
    r"^whoami$",
    r"^date$",
    r"^uname\s+",
]


# =============================================================================
# Agent Defaults — canonical values in ppxai/constants.py:Default
# =============================================================================

from ppxai.constants import Default

DEFAULT_AGENT_MAX_ITERATIONS = Default.MAX_ITERATIONS
DEFAULT_AGENT_MAX_TOOL_ITERATIONS = Default.MAX_TOOL_ITERATIONS
DEFAULT_AGENT_MAX_SAME_TOOL_CALLS = Default.MAX_SAME_TOOL_CALLS
DEFAULT_AGENT_CONTEXT_CHAR_LIMIT = Default.CONTEXT_CHAR_LIMIT
DEFAULT_AGENT_MIN_TASK_WORDS = Default.MIN_TASK_WORDS
DEFAULT_AGENT_AUTO_RETRY_EMPTY = Default.AUTO_RETRY_EMPTY
