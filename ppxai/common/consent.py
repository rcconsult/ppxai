"""
Unified consent management for file editing tools.

Provides a client-agnostic consent system where:
- ConsentManager tracks consent decisions per session
- Clients implement their own prompts (TUI uses prompt_toolkit, VSCode uses modals)
- Consent decisions are consistent across all clients

Architecture:
- ConsentManager: Session-scoped consent tracking
- ConsentDecision: Enum for decision types (YES, NO, ALWAYS, NEVER)
- Clients provide consent_callback that returns (approved: bool, decision: str)

Version: v1.11.2
"""

from enum import Enum
from dataclasses import dataclass
from typing import Callable, Awaitable, Dict, Set
from pathlib import Path


class ConsentDecision(Enum):
    """Possible consent decisions."""
    YES = "yes"          # Allow this file
    NO = "no"            # Deny this file
    ALWAYS = "always"    # Allow all files (session)
    NEVER = "never"      # Deny all files (session)


@dataclass
class ConsentRequest:
    """Request for file editing consent."""
    file_path: str
    operation: str = "edit"  # edit, create, delete
    tool_name: str = "unknown"


class ConsentManager:
    """
    Session-scoped file editing consent manager.

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
        consent_callback: Callable[[ConsentRequest], Awaitable[tuple[bool, str]]] = None
    ):
        """
        Initialize consent manager.

        Args:
            consent_callback: Async function that prompts user and returns:
                (approved: bool, decision: str) where decision is "yes", "no", "always", "never"
        """
        self.consent_callback = consent_callback
        self._always_approve = False
        self._never_approve = False
        self._approved_files: Set[str] = set()
        self._denied_files: Set[str] = set()

    def reset(self):
        """Reset all consent decisions (new session)."""
        self._always_approve = False
        self._never_approve = False
        self._approved_files.clear()
        self._denied_files.clear()

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
            decision = decision.lower().strip()

            # Process decision
            if decision == "always":
                self._always_approve = True
                return True
            elif decision == "never":
                self._never_approve = True
                return False
            elif decision in ["yes", "y"]:
                self._approved_files.add(file_path_normalized)
                return True
            else:  # "no", "n", or anything else
                self._denied_files.add(file_path_normalized)
                return False

        except Exception as e:
            # Error during consent - deny for safety
            return False

    def get_status(self) -> Dict[str, any]:
        """
        Get current consent status.

        Returns:
            dict: Status information
        """
        return {
            "mode": "always" if self._always_approve else ("never" if self._never_approve else "prompt"),
            "approved_files": len(self._approved_files),
            "denied_files": len(self._denied_files),
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


# Synchronous wrapper for non-async contexts
class SyncConsentManager:
    """
    Synchronous consent manager for legacy code.

    Wraps ConsentManager with synchronous interface.
    """

    def __init__(self, consent_callback: Callable[[ConsentRequest], tuple[bool, str]] = None):
        """
        Initialize sync consent manager.

        Args:
            consent_callback: Synchronous function that prompts user
        """
        self.consent_callback = consent_callback
        self._always_approve = False
        self._never_approve = False
        self._approved_files: Set[str] = set()
        self._denied_files: Set[str] = set()

    def reset(self):
        """Reset all consent decisions."""
        self._always_approve = False
        self._never_approve = False
        self._approved_files.clear()
        self._denied_files.clear()

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
            decision = decision.lower().strip()

            if decision == "always":
                self._always_approve = True
                return True
            elif decision == "never":
                self._never_approve = True
                return False
            elif decision in ["yes", "y"]:
                self._approved_files.add(file_path_normalized)
                return True
            else:
                self._denied_files.add(file_path_normalized)
                return False

        except Exception:
            return False

    def get_status(self) -> Dict[str, any]:
        """Get current consent status."""
        return {
            "mode": "always" if self._always_approve else ("never" if self._never_approve else "prompt"),
            "approved_files": len(self._approved_files),
            "denied_files": len(self._denied_files),
        }
