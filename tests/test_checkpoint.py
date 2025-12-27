"""
Tests for checkpoint system (v1.12.0).

Tests both git and file checkpoint backends for atomic multi-file rollback.
"""

import pytest
import tempfile
import subprocess
from pathlib import Path
from unittest.mock import Mock, patch, call

from ppxai.checkpoint import (
    CheckpointManager,
    GitCheckpointBackend,
    FileCheckpointBackend,
)


class TestGitCheckpointBackend:
    """Test git-based checkpoint backend."""

    @pytest.fixture
    def git_repo(self):
        """Create a temporary git repository for testing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir)

            # Initialize git repo
            subprocess.run(["git", "init"], cwd=repo_path, check=True, capture_output=True)
            subprocess.run(
                ["git", "config", "user.email", "test@example.com"],
                cwd=repo_path,
                check=True,
                capture_output=True
            )
            subprocess.run(
                ["git", "config", "user.name", "Test User"],
                cwd=repo_path,
                check=True,
                capture_output=True
            )

            # Create initial commit
            (repo_path / "README.md").write_text("# Test Repo\n")
            subprocess.run(["git", "add", "."], cwd=repo_path, check=True, capture_output=True)
            subprocess.run(
                ["git", "commit", "-m", "Initial commit"],
                cwd=repo_path,
                check=True,
                capture_output=True
            )

            yield repo_path

    def test_is_available_with_git_repo(self, git_repo):
        """Test that backend detects git repository."""
        backend = GitCheckpointBackend(git_repo)
        assert backend.is_available() is True

    def test_is_available_without_git_repo(self):
        """Test that backend detects absence of git repository."""
        with tempfile.TemporaryDirectory() as tmpdir:
            backend = GitCheckpointBackend(Path(tmpdir))
            assert backend.is_available() is False

    def test_create_checkpoint_with_changes(self, git_repo):
        """Test creating a checkpoint when there are uncommitted changes."""
        backend = GitCheckpointBackend(git_repo)

        # Make some changes
        (git_repo / "test.txt").write_text("Test content\n")

        # Create checkpoint
        checkpoint_id = backend.create_checkpoint("Test checkpoint")

        # Should return a commit hash
        assert checkpoint_id is not None
        assert len(checkpoint_id) == 40  # Full git hash

        # Verify commit message
        result = subprocess.run(
            ["git", "log", "-1", "--format=%s"],
            cwd=git_repo,
            capture_output=True,
            text=True,
            check=True
        )
        assert result.stdout.strip().startswith("ppxai checkpoint: Test checkpoint")

    def test_create_checkpoint_without_changes(self, git_repo):
        """Test that checkpoint returns empty string when no changes to commit."""
        backend = GitCheckpointBackend(git_repo)

        # No changes
        checkpoint_id = backend.create_checkpoint("No changes")

        # Should return empty string
        assert checkpoint_id == ""

    def test_restore_checkpoint(self, git_repo):
        """Test restoring/reverting a checkpoint commit."""
        backend = GitCheckpointBackend(git_repo)

        # Create a checkpoint with file changes
        (git_repo / "test.txt").write_text("Checkpoint content\n")
        checkpoint_id = backend.create_checkpoint("Add test file")

        # Revert the checkpoint (undo those changes)
        success = backend.restore_checkpoint(checkpoint_id)
        assert success is True

        # Verify revert commit was created
        result = subprocess.run(
            ["git", "log", "-1", "--format=%s"],
            cwd=git_repo,
            capture_output=True,
            text=True,
            check=True
        )
        assert "Revert" in result.stdout

        # File should be gone after revert
        assert not (git_repo / "test.txt").exists()

    def test_restore_nonexistent_checkpoint(self, git_repo):
        """Test that restoring invalid checkpoint fails."""
        backend = GitCheckpointBackend(git_repo)

        success = backend.restore_checkpoint("invalid-hash-1234567890abcdef")
        assert success is False

    def test_list_checkpoints(self, git_repo):
        """Test listing checkpoint commits."""
        backend = GitCheckpointBackend(git_repo)

        # Create multiple checkpoints
        (git_repo / "file1.txt").write_text("Content 1\n")
        checkpoint1 = backend.create_checkpoint("Checkpoint 1")

        (git_repo / "file2.txt").write_text("Content 2\n")
        checkpoint2 = backend.create_checkpoint("Checkpoint 2")

        # List checkpoints
        checkpoints = backend.list_checkpoints()

        # Should return at least the 2 we created
        assert len(checkpoints) >= 2
        assert any("Checkpoint 2" in desc for _, desc, _ in checkpoints)
        assert any("Checkpoint 1" in desc for _, desc, _ in checkpoints)

    def test_get_backend_name(self, git_repo):
        """Test backend name is 'git'."""
        backend = GitCheckpointBackend(git_repo)
        assert backend.get_backend_name() == "git"


class TestFileCheckpointBackend:
    """Test file-based checkpoint backend."""

    @pytest.fixture
    def temp_dirs(self):
        """Create temporary directories for testing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            working_dir = Path(tmpdir) / "project"
            working_dir.mkdir()
            session_id = "test-session"

            yield working_dir, session_id

    def test_is_available(self, temp_dirs):
        """Test that file backend is always available."""
        working_dir, session_id = temp_dirs
        backend = FileCheckpointBackend(working_dir, session_id)
        assert backend.is_available() is True

    def test_create_checkpoint(self, temp_dirs):
        """Test creating a file snapshot checkpoint."""
        working_dir, session_id = temp_dirs
        backend = FileCheckpointBackend(working_dir, session_id)

        # Create some files
        test_file = working_dir / "test.txt"
        test_file.write_text("Test content\n")

        # Register file for checkpointing
        backend.register_file(test_file)

        # Create checkpoint
        checkpoint_id = backend.create_checkpoint("Test snapshot")

        # Should return a checkpoint ID
        assert checkpoint_id is not None
        assert checkpoint_id.startswith("cp-")

        # Verify snapshot directory was created
        checkpoint_dir = backend.checkpoint_dir / checkpoint_id
        assert checkpoint_dir.exists()
        assert (checkpoint_dir / "metadata.txt").exists()

        # Verify file was copied
        assert (checkpoint_dir / "test.txt").exists()
        assert (checkpoint_dir / "test.txt").read_text() == "Test content\n"

    def test_create_checkpoint_without_files(self, temp_dirs):
        """Test that checkpoint returns empty string when no files registered."""
        working_dir, session_id = temp_dirs
        backend = FileCheckpointBackend(working_dir, session_id)

        # No files registered
        checkpoint_id = backend.create_checkpoint("Empty checkpoint")

        # Should return empty string
        assert checkpoint_id == ""

    def test_restore_checkpoint(self, temp_dirs):
        """Test restoring files from snapshot."""
        working_dir, session_id = temp_dirs
        backend = FileCheckpointBackend(working_dir, session_id)

        # Create a file and checkpoint it
        test_file = working_dir / "test.txt"
        test_file.write_text("Original content\n")
        backend.register_file(test_file)
        checkpoint_id = backend.create_checkpoint("Save original")

        # Modify the file
        test_file.write_text("Modified content\n")

        # Restore checkpoint
        success = backend.restore_checkpoint(checkpoint_id)
        assert success is True

        # Verify file was restored
        assert test_file.read_text() == "Original content\n"

    def test_restore_nonexistent_checkpoint(self, temp_dirs):
        """Test that restoring invalid checkpoint fails."""
        working_dir, session_id = temp_dirs
        backend = FileCheckpointBackend(working_dir, session_id)

        success = backend.restore_checkpoint("cp-nonexistent-123")
        assert success is False

    def test_list_checkpoints(self, temp_dirs):
        """Test listing file-based checkpoints."""
        working_dir, session_id = temp_dirs
        backend = FileCheckpointBackend(working_dir, session_id)

        # Create multiple checkpoints with slight delays to ensure different IDs
        import time
        test_file = working_dir / "test.txt"

        test_file.write_text("Version 1\n")
        backend.register_file(test_file)
        checkpoint1 = backend.create_checkpoint("Checkpoint 1")

        time.sleep(1.1)  # Ensure different timestamp (format is YYYYMMDD-HHMMSS)

        test_file.write_text("Version 2\n")
        backend.modified_files = [test_file]  # Re-register
        checkpoint2 = backend.create_checkpoint("Checkpoint 2")

        # List checkpoints
        checkpoints = backend.list_checkpoints()

        # Should return the 2 we created
        assert len(checkpoints) >= 2
        assert checkpoint1 != checkpoint2

    def test_cleanup_old_checkpoints(self, temp_dirs):
        """Test that old checkpoints are cleaned up."""
        import time
        import shutil
        working_dir, session_id = temp_dirs
        # Use unique session ID to avoid interference from other tests
        unique_session_id = session_id + "-cleanup-test"
        backend = FileCheckpointBackend(working_dir, unique_session_id)

        # Clean checkpoint directory to ensure test isolation
        if backend.checkpoint_dir.exists():
            shutil.rmtree(backend.checkpoint_dir)
            backend.checkpoint_dir.mkdir(parents=True, exist_ok=True)

        # Create 7 checkpoints with unique timestamps
        test_file = working_dir / "test.txt"
        for i in range(7):
            test_file.write_text(f"Version {i}\n")
            backend.modified_files = [test_file]  # Re-register
            backend.create_checkpoint(f"Checkpoint {i}")
            if i < 6:  # Don't sleep after last one
                time.sleep(1.1)  # Ensure different timestamps

        # Verify we have 7 checkpoints
        checkpoints_before = backend.list_checkpoints()
        assert len(checkpoints_before) == 7, f"Expected 7 checkpoints, got {len(checkpoints_before)}"

        # Cleanup old checkpoints, keep last 3
        backend.cleanup_old_checkpoints(keep_last=3)

        # Should have only 3 checkpoints left
        checkpoints_after = backend.list_checkpoints()
        assert len(checkpoints_after) == 3, f"Expected 3 checkpoints after cleanup, got {len(checkpoints_after)}"

    def test_get_backend_name(self, temp_dirs):
        """Test backend name is 'file'."""
        working_dir, session_id = temp_dirs
        backend = FileCheckpointBackend(working_dir, session_id)
        assert backend.get_backend_name() == "file"

    def test_preserve_directory_structure(self, temp_dirs):
        """Test that snapshots preserve directory structure."""
        working_dir, session_id = temp_dirs
        backend = FileCheckpointBackend(working_dir, session_id)

        # Create nested file
        subdir = working_dir / "subdir" / "nested"
        subdir.mkdir(parents=True)
        test_file = subdir / "test.txt"
        test_file.write_text("Nested content\n")

        # Register and checkpoint
        backend.register_file(test_file)
        checkpoint_id = backend.create_checkpoint("Nested structure")

        # Verify structure is preserved in snapshot
        checkpoint_dir = backend.checkpoint_dir / checkpoint_id
        snapshot_file = checkpoint_dir / "subdir" / "nested" / "test.txt"
        assert snapshot_file.exists()
        assert snapshot_file.read_text() == "Nested content\n"


class TestCheckpointManager:
    """Test CheckpointManager with auto-detection."""

    @pytest.fixture
    def git_repo(self):
        """Create a temporary git repository for testing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir)

            # Initialize git repo
            subprocess.run(["git", "init"], cwd=repo_path, check=True, capture_output=True)
            subprocess.run(
                ["git", "config", "user.email", "test@example.com"],
                cwd=repo_path,
                check=True,
                capture_output=True
            )
            subprocess.run(
                ["git", "config", "user.name", "Test User"],
                cwd=repo_path,
                check=True,
                capture_output=True
            )

            # Create initial commit
            (repo_path / "README.md").write_text("# Test\n")
            subprocess.run(["git", "add", "."], cwd=repo_path, check=True, capture_output=True)
            subprocess.run(
                ["git", "commit", "-m", "Initial"],
                cwd=repo_path,
                check=True,
                capture_output=True
            )

            yield repo_path

    def test_auto_backend_selects_git(self, git_repo):
        """Test that auto mode selects git backend when available."""
        manager = CheckpointManager(str(git_repo), "test-session", backend="auto")

        assert manager.is_enabled() is True
        assert manager.get_backend_name() == "git"

    def test_auto_backend_falls_back_to_file(self):
        """Test that auto mode falls back to file backend when no git."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = CheckpointManager(tmpdir, "test-session", backend="auto")

            assert manager.is_enabled() is True
            assert manager.get_backend_name() == "file"

    def test_explicit_git_backend(self, git_repo):
        """Test explicitly selecting git backend."""
        manager = CheckpointManager(str(git_repo), "test-session", backend="git")

        assert manager.is_enabled() is True
        assert manager.get_backend_name() == "git"

    def test_explicit_git_backend_fails_without_git(self):
        """Test that git backend mode fails when no git repo."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = CheckpointManager(tmpdir, "test-session", backend="git")

            # Should be disabled
            assert manager.is_enabled() is False
            assert manager.get_backend_name() == "none"

    def test_explicit_file_backend(self, git_repo):
        """Test explicitly selecting file backend (even with git available)."""
        manager = CheckpointManager(str(git_repo), "test-session", backend="file")

        assert manager.is_enabled() is True
        assert manager.get_backend_name() == "file"

    def test_none_backend(self, git_repo):
        """Test that 'none' backend disables checkpoints."""
        manager = CheckpointManager(str(git_repo), "test-session", backend="none")

        assert manager.is_enabled() is False
        assert manager.get_backend_name() == "none"

    def test_create_checkpoint(self, git_repo):
        """Test creating checkpoint through manager."""
        manager = CheckpointManager(str(git_repo), "test-session")

        # Make changes
        (Path(git_repo) / "test.txt").write_text("Test\n")

        # Create checkpoint
        checkpoint_id = manager.create_checkpoint("Test task")

        # Should return checkpoint ID
        assert checkpoint_id is not None

    def test_undo_checkpoint(self, git_repo):
        """Test undo operation through manager."""
        manager = CheckpointManager(str(git_repo), "test-session")

        # Create a checkpoint with changes
        test_file = Path(git_repo) / "test.txt"
        test_file.write_text("Checkpoint changes\n")
        checkpoint_id = manager.create_checkpoint("Add test file")

        # Undo the checkpoint (revert it)
        success = manager.restore_checkpoint(checkpoint_id)
        assert success is True

        # File should be gone after revert
        assert not test_file.exists()

    def test_get_status_description_git(self, git_repo):
        """Test status description for git backend."""
        manager = CheckpointManager(str(git_repo), "test-session", backend="git")

        status_desc = manager.get_status_description()
        assert "git" in status_desc.lower()
        assert "atomic" in status_desc.lower()

    def test_get_status_description_file(self):
        """Test status description for file backend."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = CheckpointManager(tmpdir, "test-session", backend="file")

            status_desc = manager.get_status_description()
            assert "file" in status_desc.lower()
            assert "checkpoints" in status_desc.lower()

    def test_get_status_description_none(self):
        """Test status description when disabled."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = CheckpointManager(tmpdir, "test-session", backend="none")

            status_desc = manager.get_status_description()
            assert "disabled" in status_desc.lower()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
