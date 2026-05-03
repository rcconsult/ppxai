"""Regression tests for release.py --dry-run side-effect-freeness.

Acceptance criterion #2 of docs/TODO-release-tooling.md: a dry-run must
perform zero git mutations. The original v1.18.0 bug was that
`merge_to_master_if_needed` ignored `dry_run` and unconditionally ran
`git checkout master && git merge ...`, leaving the user on master with
a real merge commit before the dry-run summary even printed.
"""

import importlib.util
from pathlib import Path
from unittest.mock import patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RELEASE_PY = PROJECT_ROOT / "scripts" / "release.py"


@pytest.fixture(scope="module")
def release_module():
    """Load scripts/release.py as a module without executing main()."""
    spec = importlib.util.spec_from_file_location("release_script", RELEASE_PY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_merge_to_master_dry_run_invokes_no_subprocess(release_module):
    """dry_run=True must not call run_command at all."""
    with patch.object(release_module, "run_command") as mock_run:
        result = release_module.merge_to_master_if_needed(
            "feature/some-branch", dry_run=True
        )

    assert result is True
    assert mock_run.call_count == 0, (
        "Dry-run leaked side effects: run_command called "
        f"{mock_run.call_count} time(s) with {mock_run.call_args_list!r}"
    )


def test_merge_to_master_dry_run_on_master_is_noop(release_module):
    """Already on master → no-op even outside dry-run."""
    with patch.object(release_module, "run_command") as mock_run:
        result = release_module.merge_to_master_if_needed("master", dry_run=True)
        assert result is True
        assert mock_run.call_count == 0

    with patch.object(release_module, "run_command") as mock_run:
        result = release_module.merge_to_master_if_needed("master", dry_run=False)
        assert result is True
        assert mock_run.call_count == 0


def test_merge_to_master_real_run_invokes_subprocess(release_module):
    """Sanity: dry_run=False on a feature branch DOES invoke run_command.

    Without this, a buggy "always skip side effects" rewrite would pass the
    dry-run test silently. The real path must still execute git commands.
    """
    class _OK:
        returncode = 0
        stderr = ""

    with patch.object(release_module, "run_command", return_value=_OK()) as mock_run:
        result = release_module.merge_to_master_if_needed(
            "feature/some-branch", dry_run=False
        )

    assert result is True
    assert mock_run.call_count >= 1, (
        "Real merge path made zero subprocess calls — refactor regression?"
    )
    invoked_cmds = " ".join(call.args[0] for call in mock_run.call_args_list)
    assert "git checkout master" in invoked_cmds
    assert "git merge feature/some-branch" in invoked_cmds
