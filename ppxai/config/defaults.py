"""
Default configuration values for tools and agent.

This is a LEAF MODULE - no ppxai imports allowed.
Provides centralized default constants that can be overridden by user config.
"""

from typing import Any, Dict, List
from ppxai.constants import Default


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
    # v1.18.5: read-only git verbs — don't mutate refs, working tree, or
    # remotes. Conservative on purpose: write verbs (commit, push, reset,
    # rebase, checkout, merge, fetch, pull, stash without "list", tag <name>)
    # stay DANGEROUS so the user reviews before they fire.
    r"^git\s+(status|log|diff|show|branch|blame|describe|rev-parse|rev-list|ls-files|ls-tree|reflog|shortlog|cat-file|grep|whatchanged)(\s+|$)",
    r"^git\s+stash\s+list(\s+|$)",
    r"^git\s+remote(\s+-v|\s+--verbose)?\s*$",
    r"^git\s+config\s+(--get|--list|-l)(\s+|$)",
    r"^git\s+tag(\s+-l|\s+--list)?\s*$",
    # v1.18.5: gh (GitHub CLI) read-only verbs — `view` / `list` / `status`
    # on the standard nouns are always read-only per the gh contract.
    r"^gh\s+auth\s+status(\s+|$)",
    r"^gh\s+(repo|pr|issue|release|run|workflow|gist|api|browse|search|status|cache|ruleset|variable|secret|label|codespace|extension|alias|attestation|project)\s+(view|list|status)(\s+|$)",
    # v1.18.5: rtk meta-commands — read-only operations on rtk itself (NOT
    # rtk wrapping another tool, which is handled by transparent-prefix
    # stripping). `gain` / `discover` are analytics, `hook check` is the
    # dry-run, `--help` / `--version` are universal CLI conventions.
    # Explicitly excluded (stay DANGEROUS): `rtk init` (writes config),
    # `rtk init --uninstall` (deletes config), `rtk proxy <cmd>` (bypasses
    # rtk filtering — inner command's risk should still be classified).
    r"^rtk\s+(--help|--version|gain|discover|hook\s+check)(\s+|$)",
]


# =============================================================================
# Shell Wrapper Defaults (v1.18.5)
# =============================================================================
#
# Generic shell-command wrapper framework. Each entry is a JSON-shaped dict
# the factory turns into a Wrapper instance. rtk ships as the canonical first
# wrapper; users add more by appending to `tools.shell.wrappers` in
# ppxai-config.json — no ppxai code changes required for the common cases.
#
# Schema (see ppxai/engine/tools/wrappers/factory.py for full validation):
#   name              required — identifier; conflict with user entries
#                     resolves by name (user entries WIN, override or replace).
#   type              required — "probe" or "always".
#   binary            required — name to look up via shutil.which.
#   enabled           "auto" (default) | "always" | "never".
#   transparent_for_safety  bool — consent classifier strips this prefix.
#   prompt_block_path optional — relative to package, ~/.ppxai/wrappers/, or absolute.
#   failure_markers   list of stderr substrings signaling wrapper-side failure
#                     (used by graceful-fallback retry, when enabled).
#   retry_raw_on_failure  bool — retry raw command if wrapper-side failure detected.
#   probe_args        required for type=probe — args to the dry-run command.
#   no_rewrite_marker probe-only — stdout starts with this on no-rewrite.
#   probe_timeout_seconds  probe-only — default 5.0.
#   prefix            required for type=always — string to prepend.

DEFAULT_SHELL_WRAPPERS: List[Dict[str, Any]] = [
    {
        "name": "rtk",
        "type": "probe",
        "binary": "rtk",
        "probe_args": ["hook", "check"],
        "no_rewrite_marker": "No rewrite for:",
        "transparent_for_safety": True,
        "prompt_block_path": "RTK.md",
        "enabled": "auto",
        # Phase 4 graceful fallback ships as a follow-up commit when there's
        # evidence of rtk-side failures in the wild. Markers stay empty until
        # then so we don't preemptively retry on rtk's own non-zero exits
        # that aren't actually breakage.
        "failure_markers": [],
        "retry_raw_on_failure": False,
    },
]


# =============================================================================
# Agent Defaults — canonical values in ppxai/constants.py:Default
# =============================================================================

DEFAULT_AGENT_MAX_ITERATIONS = Default.MAX_ITERATIONS
DEFAULT_AGENT_MAX_TOOL_ITERATIONS = Default.MAX_TOOL_ITERATIONS
DEFAULT_AGENT_MAX_SAME_TOOL_CALLS = Default.MAX_SAME_TOOL_CALLS
DEFAULT_AGENT_CONTEXT_CHAR_LIMIT = Default.CONTEXT_CHAR_LIMIT
DEFAULT_AGENT_MIN_TASK_WORDS = Default.MIN_TASK_WORDS
DEFAULT_AGENT_AUTO_RETRY_EMPTY = Default.AUTO_RETRY_EMPTY
DEFAULT_AGENT_ZOMBIE_THRESHOLD = Default.ZOMBIE_THRESHOLD  # P0 (v1.18.0)
