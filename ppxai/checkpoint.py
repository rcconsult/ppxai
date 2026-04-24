"""
Checkpoint system for atomic multi-file rollback in agent mode.

Supports two backends:
1. Git-based (preferred): Auto-commit before agent tasks, `git revert HEAD` to undo
2. File-based (fallback): Copy files to ~/.ppxai/checkpoints/, restore from snapshot

Usage:
    manager = CheckpointManager("/path/to/project")

    # Before agent task
    checkpoint_id = manager.create_checkpoint("Refactor auth module")

    # If something goes wrong or user wants to undo
    manager.restore_checkpoint(checkpoint_id)
"""

import os
import shutil
import subprocess
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Tuple

from .config import SESSIONS_DIR
from .common.logger import get_logger

logger = get_logger("tui")


class CheckpointBackend(ABC):
    """Abstract base class for checkpoint backends."""

    @abstractmethod
    def is_available(self) -> bool:
        """Check if this backend can be used in the current directory."""
        pass

    @abstractmethod
    def create_checkpoint(self, description: str) -> str:
        """Create a checkpoint and return its ID."""
        pass

    @abstractmethod
    def restore_checkpoint(self, checkpoint_id: str) -> bool:
        """Restore a checkpoint. Returns True on success."""
        pass

    @abstractmethod
    def list_checkpoints(self) -> List[Tuple[str, str, str]]:
        """List available checkpoints. Returns [(id, description, timestamp), ...]."""
        pass

    @abstractmethod
    def get_backend_name(self) -> str:
        """Get human-readable backend name."""
        pass


class GitCheckpointBackend(CheckpointBackend):
    """Git-based checkpoint backend using auto-commits."""

    def __init__(self, working_dir: Path):
        self.working_dir = working_dir

    def is_available(self) -> bool:
        """Check if we're in a git repository."""
        git_dir = self.working_dir / ".git"
        return git_dir.exists() and git_dir.is_dir()

    def is_checkpoint_valid(self, checkpoint_id: str) -> Tuple[bool, str]:
        """Check if a checkpoint is still valid (not stale).

        A checkpoint is valid if:
        - It is HEAD (the current commit)
        - It is HEAD~1 (the parent of the current commit)

        This prevents reverting old commits that have been superseded by newer work.

        Args:
            checkpoint_id: The commit hash to validate

        Returns:
            Tuple of (is_valid: bool, reason: str)
        """
        if not checkpoint_id:
            return False, "No checkpoint ID provided"

        try:
            # Get HEAD commit
            result = self._run_git("rev-parse", "HEAD", check=False)
            if result.returncode != 0:
                return False, "Could not determine HEAD commit"
            head_commit = result.stdout.strip()

            # Get HEAD~1 commit (parent)
            result = self._run_git("rev-parse", "HEAD~1", check=False)
            parent_commit = result.stdout.strip() if result.returncode == 0 else None

            # Expand short hash to full hash for comparison
            result = self._run_git("rev-parse", checkpoint_id, check=False)
            if result.returncode != 0:
                return False, f"Checkpoint commit {checkpoint_id} not found"
            full_checkpoint_id = result.stdout.strip()

            # Check if checkpoint is HEAD or HEAD~1
            if full_checkpoint_id == head_commit:
                return True, "Checkpoint is HEAD"
            if parent_commit and full_checkpoint_id == parent_commit:
                return True, "Checkpoint is HEAD~1"

            # Checkpoint is stale
            return False, f"Checkpoint is stale: newer commits exist after {checkpoint_id[:8]}"

        except subprocess.CalledProcessError as e:
            return False, f"Git error: {e}"

    def _run_git(self, *args, check=True, capture_output=True) -> subprocess.CompletedProcess:
        """Run a git command in the working directory."""
        return subprocess.run(
            ["git", *args],
            cwd=self.working_dir,
            check=check,
            capture_output=capture_output,
            text=True
        )

    def _has_changes(self) -> bool:
        """Check if there are uncommitted changes."""
        result = self._run_git("status", "--porcelain", check=False)
        return bool(result.stdout.strip())

    def create_checkpoint(self, description: str) -> str:
        """Create a git commit checkpoint."""
        if not self._has_changes():
            # No changes to commit, return empty checkpoint ID
            return ""

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        commit_message = f"ppxai checkpoint: {description}\n\n[{timestamp}]"

        # Add all changes (tracked and untracked)
        self._run_git("add", "-A")

        # Create commit
        self._run_git("commit", "-m", commit_message)

        # Get commit hash
        result = self._run_git("rev-parse", "HEAD")
        commit_hash = result.stdout.strip()

        return commit_hash

    def restore_checkpoint(self, checkpoint_id: str) -> bool:
        """Restore by reverting the last commit."""
        if not checkpoint_id:
            return False

        try:
            # Verify the commit exists and is a ppxai commit (checkpoint or agent)
            result = self._run_git("log", "-1", "--format=%s", checkpoint_id, check=False)
            msg = result.stdout.strip()
            # Accept both checkpoint commits and agent task commits
            if not (msg.startswith("ppxai checkpoint:") or msg.startswith("ppxai agent:")):
                return False

            # Revert the commit
            self._run_git("revert", "--no-edit", checkpoint_id)
            return True
        except subprocess.CalledProcessError:
            return False

    def list_checkpoints(self) -> List[Tuple[str, str, str]]:
        """List ppxai checkpoint and agent commits (undoable commits)."""
        try:
            # Include both checkpoint and agent commits
            result = self._run_git(
                "log",
                "--grep=^ppxai checkpoint:\\|^ppxai agent:",
                "--format=%H|%s|%ai",
                "-n", "10",
                check=False
            )

            checkpoints = []
            for line in result.stdout.strip().split("\n"):
                if not line:
                    continue
                commit_hash, message, timestamp = line.split("|", 2)
                # Extract description from "ppxai checkpoint: <desc>" or "ppxai agent: <desc>"
                if message.startswith("ppxai checkpoint: "):
                    description = message.replace("ppxai checkpoint: ", "")
                elif message.startswith("ppxai agent: "):
                    description = message.replace("ppxai agent: ", "")
                else:
                    description = message
                checkpoints.append((commit_hash[:8], description, timestamp))

            return checkpoints
        except (subprocess.CalledProcessError, ValueError):
            return []

    def get_backend_name(self) -> str:
        return "git"


class FileCheckpointBackend(CheckpointBackend):
    """File-based checkpoint backend using snapshots."""

    def __init__(self, working_dir: Path, session_id: str):
        self.working_dir = working_dir
        self.session_id = session_id
        self.checkpoint_dir = Path(SESSIONS_DIR) / "checkpoints" / session_id
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)

        # Track modified files
        self.modified_files: List[Path] = []

    def is_available(self) -> bool:
        """File backend is always available."""
        return True

    def is_checkpoint_valid(self, checkpoint_id: str) -> Tuple[bool, str]:
        """Check if a checkpoint is still valid.

        File-based checkpoints are always valid if the snapshot directory exists.
        Unlike git, there's no concept of "newer commits" invalidating old snapshots.

        Args:
            checkpoint_id: The checkpoint ID to validate

        Returns:
            Tuple of (is_valid: bool, reason: str)
        """
        if not checkpoint_id:
            return False, "No checkpoint ID provided"

        snapshot_dir = self.checkpoint_dir / checkpoint_id
        if snapshot_dir.exists() and (snapshot_dir / "metadata.txt").exists():
            return True, "Snapshot exists"
        return False, f"Snapshot {checkpoint_id} not found"

    def register_file(self, file_path: Path):
        """Register a file that will be modified (call before editing)."""
        if file_path not in self.modified_files:
            self.modified_files.append(file_path)

    def create_checkpoint(self, description: str) -> str:
        """Create a file snapshot checkpoint."""
        if not self.modified_files:
            return ""

        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        checkpoint_id = f"cp-{timestamp}"
        snapshot_dir = self.checkpoint_dir / checkpoint_id

        # Create snapshot directory
        snapshot_dir.mkdir(parents=True, exist_ok=True)

        # Save metadata
        metadata_file = snapshot_dir / "metadata.txt"
        metadata_file.write_text(
            f"Description: {description}\n"
            f"Timestamp: {datetime.now().isoformat()}\n"
            f"Files:\n",
            encoding="utf-8",
        )

        # Copy each modified file
        for file_path in self.modified_files:
            if not file_path.exists():
                continue

            # Preserve directory structure
            rel_path = file_path.relative_to(self.working_dir)
            dest_path = snapshot_dir / rel_path
            dest_path.parent.mkdir(parents=True, exist_ok=True)

            # Copy file
            shutil.copy2(file_path, dest_path)

            # Append to metadata
            with metadata_file.open("a", encoding="utf-8") as f:
                f.write(f"  - {rel_path}\n")

        return checkpoint_id

    def restore_checkpoint(self, checkpoint_id: str) -> bool:
        """Restore files from snapshot."""
        snapshot_dir = self.checkpoint_dir / checkpoint_id
        if not snapshot_dir.exists():
            return False

        try:
            # Read metadata to get file list
            metadata_file = snapshot_dir / "metadata.txt"
            if not metadata_file.exists():
                return False

            # Restore each file
            for item in snapshot_dir.rglob("*"):
                if item.is_file() and item.name != "metadata.txt":
                    rel_path = item.relative_to(snapshot_dir)
                    dest_path = self.working_dir / rel_path
                    dest_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(item, dest_path)

            return True
        except (OSError, IOError):
            return False

    def list_checkpoints(self) -> List[Tuple[str, str, str]]:
        """List file-based checkpoints."""
        checkpoints = []
        for checkpoint_dir in sorted(self.checkpoint_dir.iterdir(), reverse=True):
            if not checkpoint_dir.is_dir():
                continue

            metadata_file = checkpoint_dir / "metadata.txt"
            if not metadata_file.exists():
                continue

            # Parse metadata
            metadata = metadata_file.read_text(encoding="utf-8")
            lines = metadata.split("\n")
            description = "Unknown"
            timestamp = "Unknown"

            for line in lines:
                if line.startswith("Description: "):
                    description = line.replace("Description: ", "")
                elif line.startswith("Timestamp: "):
                    timestamp = line.replace("Timestamp: ", "")

            checkpoints.append((checkpoint_dir.name, description, timestamp))

        return checkpoints[:10]  # Return last 10

    def get_backend_name(self) -> str:
        return "file"

    def cleanup_old_checkpoints(self, keep_last: int = 10):
        """Remove old checkpoints, keeping the most recent ones."""
        checkpoints = sorted(self.checkpoint_dir.iterdir(), reverse=True)
        for checkpoint_dir in checkpoints[keep_last:]:
            if checkpoint_dir.is_dir():
                shutil.rmtree(checkpoint_dir)


class CheckpointManager:
    """Manages checkpoints with automatic backend selection."""

    def __init__(self, working_dir: str, session_id: str = "default", backend: str = "auto"):
        """
        Initialize checkpoint manager.

        Args:
            working_dir: Working directory for the project
            session_id: Session identifier for file-based checkpoints
            backend: "auto" (detect), "git" (git-only), "file" (file-only), or "none" (disabled)
        """
        self.working_dir = Path(working_dir).resolve()
        self.session_id = session_id
        self.backend_mode = backend
        self.backend: Optional[CheckpointBackend] = None

        self._initialize_backend()

    def _initialize_backend(self):
        """Initialize the appropriate backend based on configuration."""
        if self.backend_mode == "none":
            self.backend = None
            return

        # Try git first (if not explicitly set to "file")
        if self.backend_mode in ("auto", "git"):
            git_backend = GitCheckpointBackend(self.working_dir)
            if git_backend.is_available():
                self.backend = git_backend
                return

            # If git-only mode, fail
            if self.backend_mode == "git":
                self.backend = None
                return

        # Fallback to file-based
        self.backend = FileCheckpointBackend(self.working_dir, self.session_id)

    def is_enabled(self) -> bool:
        """Check if checkpointing is enabled."""
        return self.backend is not None

    def get_backend_name(self) -> str:
        """Get the name of the active backend."""
        if not self.backend:
            return "none"
        return self.backend.get_backend_name()

    def create_checkpoint(self, description: str) -> Optional[str]:
        """
        Create a checkpoint before agent task execution.

        Returns:
            Checkpoint ID if successful, None if checkpointing is disabled or failed
        """
        if not self.backend:
            return None

        try:
            checkpoint_id = self.backend.create_checkpoint(description)
            return checkpoint_id if checkpoint_id else None
        except Exception as e:
            logger.debug(f"Checkpoint creation failed: {e}")
            # Better to let agent run than block on checkpoint failure
            return None

    def restore_checkpoint(self, checkpoint_id: str) -> bool:
        """
        Restore a checkpoint (undo).

        Returns:
            True if restoration successful, False otherwise
        """
        if not self.backend or not checkpoint_id:
            return False

        return self.backend.restore_checkpoint(checkpoint_id)

    def is_checkpoint_valid(self, checkpoint_id: str) -> Tuple[bool, str]:
        """
        Check if a checkpoint is still valid (not stale).

        For git backend, checks if checkpoint is HEAD or HEAD~1.
        For file backend, checks if snapshot directory exists.

        Args:
            checkpoint_id: The checkpoint ID to validate

        Returns:
            Tuple of (is_valid: bool, reason: str)
        """
        if not self.backend:
            return False, "Checkpointing is disabled"

        if not checkpoint_id:
            return False, "No checkpoint ID provided"

        return self.backend.is_checkpoint_valid(checkpoint_id)

    def list_checkpoints(self) -> List[Tuple[str, str, str]]:
        """
        List available checkpoints.

        Returns:
            List of (id, description, timestamp) tuples
        """
        if not self.backend:
            return []

        return self.backend.list_checkpoints()

    def register_file(self, file_path: Path):
        """Register a file for checkpointing (file backend only)."""
        if isinstance(self.backend, FileCheckpointBackend):
            self.backend.register_file(file_path)

    def get_status_description(self) -> str:
        """Get a human-readable description of checkpoint status."""
        if not self.backend:
            return "Checkpoints: disabled"

        backend_name = self.get_backend_name()
        if backend_name == "git":
            return "Checkpoints: git (atomic)"
        elif backend_name == "file":
            return f"Checkpoints: file (~/.ppxai/checkpoints/{self.session_id})"
        else:
            return "Checkpoints: unknown"
