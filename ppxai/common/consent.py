"""
Unified consent management for file editing tools and shell commands.

Provides a client-agnostic consent system where:
- ConsentManager tracks consent decisions per session
- Clients implement their own prompts (TUI uses prompt_toolkit, VSCode uses modals)
- Consent decisions are consistent across all clients

Architecture:
- BaseConsentManager: Shared logic for all consent managers
- ConsentManager: Async consent manager (primary)
- SyncConsentManager: Synchronous consent manager (legacy)
- ConsentDecision: Enum for decision types (YES, NO, ALWAYS, NEVER) - from constants.py
- Clients provide consent_callback that returns (approved: bool, decision: str)
- classify_shell_command(): Standalone function for command risk classification
"""

import re
from dataclasses import dataclass
from typing import Callable, Awaitable, Dict, Set, List, Optional
from pathlib import Path

from .logger import get_logger
from ..constants import (
    ConsentDecision,
    ConsentMode,
    ConsentResponse,
    ShellRiskLevel,
)

logger = get_logger("tui")


def normalize_consent_response(response: str) -> str:
    """Normalize consent responses to standard enum values.

    Handles all variations of user responses (case-insensitive, full words, abbreviations)
    and returns the canonical ConsentResponse enum value.

    Args:
        response: User response (e.g., "yes", "Yes", "YES", "y", "Y", "always", "no", "n")

    Returns:
        Normalized response matching ConsentResponse enum:
        - "y" for yes/approve
        - "n" for no/deny
        - "always" for always approve
        - "never" for always deny

    Examples:
        >>> normalize_consent_response("yes")
        'y'
        >>> normalize_consent_response("YES")
        'y'
        >>> normalize_consent_response("y")
        'y'
        >>> normalize_consent_response("always")
        'always'
        >>> normalize_consent_response("ALWAYS")
        'always'
        >>> normalize_consent_response("no")
        'n'
        >>> normalize_consent_response("n")
        'n'
    """
    if not response:
        return ConsentResponse.NO  # Default to no for empty/None

    response_lower = response.lower().strip()

    # Map all variations to enum values
    yes_variations = ["y", "yes", "approve", "ok", "allow"]
    no_variations = ["n", "no", "deny", "cancel", "reject"]
    always_variations = ["always", "a", "all"]
    never_variations = ["never", "block", "none"]

    if response_lower in yes_variations:
        return ConsentResponse.YES  # "y"
    elif response_lower in no_variations:
        return ConsentResponse.NO   # "n"
    elif response_lower in always_variations:
        return ConsentResponse.ALWAYS  # "always"
    elif response_lower in never_variations:
        return ConsentResponse.NEVER   # "never"
    else:
        # Unknown response, default to no for safety
        logger.warning(f"Unknown consent response '{response}', defaulting to 'no'")
        return ConsentResponse.NO


def classify_shell_command(command: str, config: Dict[str, List[str]]) -> str:
    """Classify shell command risk level.

    This is a standalone function for use by EngineClient and other modules
    that need command classification without instantiating a ConsentManager.

    Args:
        command: Shell command to classify
        config: Shell config dict with keys:
            - never_allow: List of regex patterns for blocked commands
            - dangerous_commands: List of regex patterns for dangerous commands
            - allowed_commands: List of regex patterns for safe commands

    Returns:
        ShellRiskLevel value: NEVER, DANGEROUS, or SAFE
    """
    # v1.18.5: classify under TWO targets — the original command and the
    # transparent-wrapper-stripped form — and take the worst-of-original
    # never-allow plus best-of-either allowed match. Why both?
    #
    # 1. Original-first matters for wrapper meta-commands: `rtk gain`
    #    must match the `^rtk\s+...` allowed pattern. If we stripped
    #    `rtk` first we'd be classifying just `gain`, which is unknown
    #    → DANGEROUS for a read-only operation. Wrong.
    # 2. Stripped form matters for wrapper-prefixed inner commands:
    #    `rtk git status` doesn't match the rtk meta pattern (because
    #    `git` isn't in the meta list), but stripping yields
    #    `git status` which matches the git read-only pattern. SAFE.
    #
    # Order: NEVER (either form) → DANGEROUS (either form) → SAFE
    # (either form) → DANGEROUS (default).
    stripped = _strip_transparent_wrapper_prefixes(command)
    targets = [command] if stripped == command else [command, stripped]

    # Check never-allow patterns on every target — catastrophic patterns
    # like `rm -rf /` must trigger NEVER even when wrapped (`rtk proxy
    # rm -rf /` strips to `proxy rm -rf /` which still substring-matches).
    for pattern in config.get("never_allow", []):
        try:
            for target in targets:
                if re.search(pattern, target):
                    return ShellRiskLevel.NEVER
        except re.error as e:
            logger.warning(f"Invalid never_allow regex pattern '{pattern}': {e}")

    # Check dangerous patterns on every target.
    for pattern in config.get("dangerous_commands", []):
        try:
            for target in targets:
                if re.search(pattern, target):
                    return ShellRiskLevel.DANGEROUS
        except re.error as e:
            logger.warning(f"Invalid dangerous_commands regex pattern '{pattern}': {e}")

    # Check allowed patterns — original first so wrapper meta-commands
    # match, stripped second so wrapper-prefixed inner commands match.
    for pattern in config.get("allowed_commands", []):
        try:
            for target in targets:
                if re.search(pattern, target):
                    return ShellRiskLevel.SAFE
        except re.error as e:
            logger.warning(f"Invalid allowed_commands regex pattern '{pattern}': {e}")

    # Unknown commands are treated as dangerous for safety
    return ShellRiskLevel.DANGEROUS


def _strip_transparent_wrapper_prefixes(command: str) -> str:
    """Best-effort strip of transparent wrapper prefixes via the registry.

    Lazy-imported to avoid a circular dependency: the wrapper framework
    pulls in config code that imports parts of common; importing
    consent at module load from inside the framework would cycle.
    Falls back to the raw command on any error so safety classification
    is never blocked by a misconfigured registry.
    """
    try:
        from ..engine.tools.wrappers import get_registry
        return get_registry().strip_transparent_prefixes(command)
    except Exception:
        return command


@dataclass
class ConsentRequest:
    """Request for file editing consent."""
    file_path: str
    operation: str = "edit"  # edit, create, delete
    tool_name: str = "unknown"


@dataclass
class ShellConsentRequest:
    """Request for shell command execution consent."""
    command: str
    working_dir: str = "."
    risk_level: str = "unknown"  # safe, dangerous, never
    tool_name: str = "shell"


class BaseConsentManager:
    """
    Base class for consent managers with shared logic.

    Contains all non-callback-dependent logic:
    - State initialization
    - Shell config loading and pattern matching
    - Command classification
    - Status reporting
    - File/command approval checking (non-prompting)
    """

    def __init__(self, shell_config: Optional[Dict] = None):
        """
        Initialize base consent manager state.

        Args:
            shell_config: Shell tool configuration with dangerous/allowed/never patterns
        """
        # File editing consent state
        self._always_approve = False
        self._never_approve = False
        self._approved_files: Set[str] = set()
        self._denied_files: Set[str] = set()

        # Shell command consent state
        self._always_approve_shell = False
        self._never_approve_shell = False
        self._approved_commands: Set[str] = set()
        self._denied_commands: Set[str] = set()

        # Load shell configuration patterns
        self._load_shell_config(shell_config or {})

    def _load_shell_config(self, config: Dict):
        """
        Load shell command patterns from configuration.

        Args:
            config: Shell tool configuration dict with dangerous/allowed/never patterns
        """
        self._dangerous_patterns: List[re.Pattern] = []
        self._allowed_patterns: List[re.Pattern] = []
        self._never_allow_patterns: List[re.Pattern] = []

        # Compile dangerous command patterns
        for pattern in config.get("dangerous_commands", []):
            try:
                self._dangerous_patterns.append(re.compile(pattern))
            except re.error as e:
                logger.warning(f"Invalid dangerous_commands regex pattern '{pattern}': {e}")

        # Compile allowed command patterns (bypass consent)
        for pattern in config.get("allowed_commands", []):
            try:
                self._allowed_patterns.append(re.compile(pattern))
            except re.error as e:
                logger.warning(f"Invalid allowed_commands regex pattern '{pattern}': {e}")

        # Compile never-allow patterns (always block)
        for pattern in config.get("never_allow", []):
            try:
                self._never_allow_patterns.append(re.compile(pattern))
            except re.error as e:
                logger.warning(f"Invalid never_allow regex pattern '{pattern}': {e}")

    def _is_never_allowed_command(self, command: str) -> bool:
        """
        Check if command matches never-allow patterns (catastrophic).

        Args:
            command: Shell command to check

        Returns:
            bool: True if command should never be allowed
        """
        for pattern in self._never_allow_patterns:
            if pattern.search(command):
                return True
        return False

    def _is_allowed_command(self, command: str) -> bool:
        """
        Check if command matches allowed patterns (safe).

        Args:
            command: Shell command to check

        Returns:
            bool: True if command is safe and doesn't need consent
        """
        for pattern in self._allowed_patterns:
            if pattern.search(command):
                return True
        return False

    def _is_dangerous_command(self, command: str) -> bool:
        """
        Check if command matches dangerous patterns.

        Args:
            command: Shell command to check

        Returns:
            bool: True if command is dangerous and needs consent
        """
        for pattern in self._dangerous_patterns:
            if pattern.search(command):
                return True
        return False

    def _classify_command(self, command: str) -> str:
        """
        Classify command risk level.

        Args:
            command: Shell command to classify

        Returns:
            str: Risk level - ShellRiskLevel value
        """
        # v1.18.5: classify under both the original and wrapper-stripped
        # forms — see classify_shell_command for the full rationale.
        stripped = _strip_transparent_wrapper_prefixes(command)
        targets = [command] if stripped == command else [command, stripped]

        if any(self._is_never_allowed_command(t) for t in targets):
            return ShellRiskLevel.NEVER
        if any(self._is_dangerous_command(t) for t in targets):
            return ShellRiskLevel.DANGEROUS
        if any(self._is_allowed_command(t) for t in targets):
            return ShellRiskLevel.SAFE
        # Unknown command - treat as dangerous for safety
        return ShellRiskLevel.DANGEROUS

    def reset(self):
        """Reset all consent decisions (new session)."""
        # File editing reset
        self._always_approve = False
        self._never_approve = False
        self._approved_files.clear()
        self._denied_files.clear()

        # Shell command reset
        self._always_approve_shell = False
        self._never_approve_shell = False
        self._approved_commands.clear()
        self._denied_commands.clear()

    def get_status(self) -> Dict[str, any]:
        """
        Get current consent status.

        Returns:
            dict: Status information for files and shell commands
        """
        return {
            "file_mode": ConsentMode.ALWAYS if self._always_approve else (ConsentMode.NEVER if self._never_approve else ConsentMode.PROMPT),
            "approved_files": len(self._approved_files),
            "denied_files": len(self._denied_files),
            "shell_mode": ConsentMode.ALWAYS if self._always_approve_shell else (ConsentMode.NEVER if self._never_approve_shell else ConsentMode.PROMPT),
            "approved_commands": len(self._approved_commands),
            "denied_commands": len(self._denied_commands),
        }

    def is_file_approved(self, file_path: str) -> bool:
        """
        Check if file is already approved (without prompting).

        Args:
            file_path: Path to check

        Returns:
            bool: True if in approved set or always_approve mode
        """
        if self._always_approve:
            return True

        if self._never_approve:
            return False

        file_path_normalized = str(Path(file_path).resolve())
        return file_path_normalized in self._approved_files

    def is_command_approved(self, command: str) -> bool:
        """
        Check if command is already approved (without prompting).

        Args:
            command: Shell command to check

        Returns:
            bool: True if approved, False if denied or unknown
        """
        # Check risk level
        risk_level = self._classify_command(command)

        # Never-allow always returns False
        if risk_level == ShellRiskLevel.NEVER:
            return False

        # Safe commands always return True
        if risk_level == ShellRiskLevel.SAFE:
            return True

        # Check session-wide decisions
        if self._always_approve_shell:
            return True

        if self._never_approve_shell:
            return False

        # Check command-specific cache
        return command in self._approved_commands

    def _process_file_decision(self, decision: str, file_path_normalized: str) -> bool:
        """
        Process a consent decision for file operations.

        Args:
            decision: The decision string (always, never, yes, y, no, etc.)
            file_path_normalized: Normalized file path

        Returns:
            bool: True if approved, False if denied
        """
        decision = decision.lower().strip()

        if decision == ConsentDecision.ALWAYS:
            self._always_approve = True
            return True
        elif decision == ConsentDecision.NEVER:
            self._never_approve = True
            return False
        elif decision in [ConsentDecision.YES, ConsentResponse.YES]:
            self._approved_files.add(file_path_normalized)
            return True
        else:  # "no", "n", or anything else
            self._denied_files.add(file_path_normalized)
            return False

    def _process_shell_decision(self, decision: str, command: str) -> bool:
        """
        Process a consent decision for shell commands.

        Args:
            decision: The decision string (always, never, yes, y, no, etc.)
            command: The shell command

        Returns:
            bool: True if approved, False if denied
        """
        decision = decision.lower().strip()

        if decision == ConsentDecision.ALWAYS:
            self._always_approve_shell = True
            return True
        elif decision == ConsentDecision.NEVER:
            self._never_approve_shell = True
            return False
        elif decision in [ConsentDecision.YES, ConsentResponse.YES]:
            self._approved_commands.add(command)
            return True
        else:  # "no", "n", or anything else
            self._denied_commands.add(command)
            return False


class ConsentManager(BaseConsentManager):
    """
    Async session-scoped consent manager.

    Tracks consent decisions and enforces policies:
    - Per-file consent (YES/NO)
    - Session-wide always/never
    - Approved files cache

    Usage:
        # TUI
        async def tui_consent_prompt(request):
            response = await prompt_toolkit_input("Allow edit? ")
            return (response in ['y', 'yes', 'always'], response)

        manager = ConsentManager(consent_callback=tui_consent_prompt)
        approved = await manager.request_consent("/path/to/file.py")

        # VSCode (via HTTP)
        async def vscode_consent_prompt(request):
            response = await send_sse_event("consent_request", request)
            return (response.approved, response.decision)

        manager = ConsentManager(consent_callback=vscode_consent_prompt)
        approved = await manager.request_consent("/path/to/file.py")
    """

    def __init__(
        self,
        consent_callback: Callable[[ConsentRequest], Awaitable[tuple[bool, str]]] = None,
        shell_consent_callback: Callable[[ShellConsentRequest], Awaitable[tuple[bool, str]]] = None,
        shell_config: Optional[Dict] = None
    ):
        """
        Initialize async consent manager.

        Args:
            consent_callback: Async function that prompts user for file edit consent
            shell_consent_callback: Async function that prompts user for shell command consent
            shell_config: Shell tool configuration with dangerous/allowed/never patterns
        """
        super().__init__(shell_config)
        self.consent_callback = consent_callback
        self.shell_consent_callback = shell_consent_callback

    async def request_consent(
        self,
        file_path: str,
        operation: str = "edit",
        tool_name: str = "unknown"
    ) -> bool:
        """
        Request consent for file operation.

        Args:
            file_path: Path to file that needs editing
            operation: Type of operation (edit, create, delete)
            tool_name: Name of tool requesting consent

        Returns:
            bool: True if approved, False if denied
        """
        # Check session-wide decisions
        if self._never_approve:
            return False

        if self._always_approve:
            return True

        # Check file-specific cache
        file_path_normalized = str(Path(file_path).resolve())

        if file_path_normalized in self._approved_files:
            return True

        if file_path_normalized in self._denied_files:
            return False

        # Need to ask user
        if not self.consent_callback:
            # No callback provided - deny for safety
            return False

        request = ConsentRequest(
            file_path=file_path,
            operation=operation,
            tool_name=tool_name
        )

        try:
            approved, decision = await self.consent_callback(request)
            return self._process_file_decision(decision, file_path_normalized)

        except Exception:
            # Error during consent - deny for safety
            return False

    async def request_shell_consent(
        self,
        command: str,
        working_dir: str = "."
    ) -> bool:
        """
        Request consent for shell command execution.

        Args:
            command: Shell command to execute
            working_dir: Working directory for command

        Returns:
            bool: True if approved, False if denied or blocked
        """
        # Classify command risk
        risk_level = self._classify_command(command)

        # Never-allow commands are always blocked
        if risk_level == ShellRiskLevel.NEVER:
            return False

        # Safe commands are always allowed (no consent needed)
        if risk_level == ShellRiskLevel.SAFE:
            return True

        # Check session-wide shell decisions
        if self._never_approve_shell:
            return False

        if self._always_approve_shell:
            return True

        # Check command-specific cache
        if command in self._approved_commands:
            return True

        if command in self._denied_commands:
            return False

        # Need to ask user
        if not self.shell_consent_callback:
            # No callback provided - deny for safety
            return False

        request = ShellConsentRequest(
            command=command,
            working_dir=working_dir,
            risk_level=risk_level,
            tool_name="shell"
        )

        try:
            approved, decision = await self.shell_consent_callback(request)
            return self._process_shell_decision(decision, command)

        except Exception:
            # Error during consent - deny for safety
            return False


class SyncConsentManager(BaseConsentManager):
    """
    Synchronous consent manager for legacy code.

    Provides synchronous versions of request_consent and request_shell_consent.
    Inherits all other functionality from BaseConsentManager.
    """

    def __init__(
        self,
        consent_callback: Callable[[ConsentRequest], tuple[bool, str]] = None,
        shell_consent_callback: Callable[[ShellConsentRequest], tuple[bool, str]] = None,
        shell_config: Optional[Dict] = None
    ):
        """
        Initialize sync consent manager.

        Args:
            consent_callback: Synchronous function that prompts user for file edits
            shell_consent_callback: Synchronous function that prompts user for shell commands
            shell_config: Shell tool configuration
        """
        super().__init__(shell_config)
        self.consent_callback = consent_callback
        self.shell_consent_callback = shell_consent_callback

    def request_consent(
        self,
        file_path: str,
        operation: str = "edit",
        tool_name: str = "unknown"
    ) -> bool:
        """
        Request consent for file operation (synchronous).

        Args:
            file_path: Path to file that needs editing
            operation: Type of operation
            tool_name: Name of tool requesting consent

        Returns:
            bool: True if approved, False if denied
        """
        # Check session-wide decisions
        if self._never_approve:
            return False

        if self._always_approve:
            return True

        # Check file-specific cache
        file_path_normalized = str(Path(file_path).resolve())

        if file_path_normalized in self._approved_files:
            return True

        if file_path_normalized in self._denied_files:
            return False

        # Need to ask user
        if not self.consent_callback:
            return False

        request = ConsentRequest(
            file_path=file_path,
            operation=operation,
            tool_name=tool_name
        )

        try:
            approved, decision = self.consent_callback(request)
            return self._process_file_decision(decision, file_path_normalized)

        except Exception:
            return False

    def request_shell_consent(
        self,
        command: str,
        working_dir: str = "."
    ) -> bool:
        """
        Request consent for shell command execution (synchronous).

        Args:
            command: Shell command to execute
            working_dir: Working directory for command

        Returns:
            bool: True if approved, False if denied or blocked
        """
        # Classify command risk
        risk_level = self._classify_command(command)

        # Never-allow commands are always blocked
        if risk_level == ShellRiskLevel.NEVER:
            return False

        # Safe commands are always allowed
        if risk_level == ShellRiskLevel.SAFE:
            return True

        # Check session-wide shell decisions
        if self._never_approve_shell:
            return False

        if self._always_approve_shell:
            return True

        # Check command-specific cache
        if command in self._approved_commands:
            return True

        if command in self._denied_commands:
            return False

        # Need to ask user
        if not self.shell_consent_callback:
            return False

        request = ShellConsentRequest(
            command=command,
            working_dir=working_dir,
            risk_level=risk_level,
            tool_name="shell"
        )

        try:
            approved, decision = self.shell_consent_callback(request)
            return self._process_shell_decision(decision, command)

        except Exception:
            return False
