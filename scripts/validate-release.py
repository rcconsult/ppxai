#!/usr/bin/env python3
"""
Validate that all files have been updated for a release.

Usage:
    python scripts/validate-release.py v1.11.4
"""
import re
import sys
from pathlib import Path

# Fix Windows console encoding for Unicode output
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')


def check_version_in_file(file_path: Path, version: str, pattern: str) -> bool:
    """Check if version appears in file matching pattern."""
    if not file_path.exists():
        return False

    content = file_path.read_text(encoding='utf-8')
    match = re.search(pattern.format(version=re.escape(version)), content)
    return match is not None


def validate_release(version: str, allow_dirty: bool = False) -> bool:
    """Validate all files have been updated for the release.

    `allow_dirty=True` skips the "git working directory is clean"
    check. Used by `scripts/release.py` which calls this validator
    *after* making version-bump edits but *before* committing them —
    a clean check at that point is structurally guaranteed to fail.
    Standalone runs (e.g. CI sanity-check) keep the strict default.
    """
    # Remove 'v' prefix if present
    version_number = version.lstrip('v')

    errors = []
    warnings = []

    # Check version files
    checks = [
        {
            "file": "pyproject.toml",
            "pattern": r'version\s*=\s*"{version}"',
            "critical": True,
        },
        {
            "file": "ppxai/version.py",
            "pattern": r'__version__\s*=\s*"{version}"',
            "critical": True,
        },
        {
            "file": "vscode-extension/package.json",
            "pattern": r'"version":\s*"{version}"',
            "critical": True,
        },
        {
            "file": "ROADMAP.md",
            # Pattern: > **Current Version**: v1.12.0 (December 2025)
            "pattern": r">\s+\*\*Current Version\*\*:\s+v{version}",
            "critical": True,
        },
        {
            "file": "CLAUDE.md",
            "pattern": r"\*\*Current Version:\*\*\s+v{version}",
            "critical": False,  # CLAUDE.md might be updated during development
        },
        # README VSIX version checks (repeatedly missed in v1.11.4, v1.11.5, v1.11.6)
        {
            "file": "README.md",
            "pattern": r"ppxai-{version}\.vsix",
            "critical": True,
        },
        # NOTE: "What's New" check removed - README.md is project overview, not changelog
        # Version-specific changes go in docs/RELEASE-NOTES-v{version}.md
        {
            "file": "vscode-extension/README.md",
            "pattern": r"ppxai-{version}\.vsix",
            "critical": True,
        },
        # CHANGELOG must have entry for this version
        {
            "file": "CHANGELOG.md",
            "pattern": r"##\s+\[{version}\]\s+-\s+\d{{4}}-\d{{2}}-\d{{2}}",
            "critical": True,
        },
        # event_handler.py has version in welcome message
        {
            "file": "ppxai/rich/event_handler.py",
            "pattern": r"Version:\s+v{version}",
            "critical": True,
        },
        # logger.py has version in banner
        {
            "file": "ppxai/common/logger.py",
            "pattern": r"Version:\s+v{version}",
            "critical": True,
        },
        # AGENTS.md current version
        {
            "file": "AGENTS.md",
            "pattern": r"### Current Version: v{version}",
            "critical": True,
        },
        # docs/README.md current version
        {
            "file": "docs/README.md",
            "pattern": r"\*\*Current Version\*\*:\s+v{version}",
            "critical": True,
        },
        # README.md version badge
        {
            "file": "README.md",
            "pattern": r"badge/version-{version}-blue",
            "critical": True,
        },
    ]

    project_root = Path(__file__).parent.parent

    for check in checks:
        file_path = project_root / check["file"]
        if not check_version_in_file(file_path, version_number, check["pattern"]):
            msg = f"{check['file']}: Version {version} not found"
            if check["critical"]:
                errors.append(msg)
            else:
                warnings.append(msg)

    # Check that git is clean (skip when called from release.py after
    # version-bump edits — that flow guarantees a dirty tree at this
    # validation point, by design).
    if not allow_dirty:
        import subprocess
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=project_root,
            capture_output=True,
            text=True
        )
        if result.stdout.strip():
            errors.append("Git working directory is not clean")

    # Print results
    print(f"Validating release {version}...")
    print()

    if errors:
        print("❌ VALIDATION FAILED")
        print()
        print("Errors:")
        for error in errors:
            print(f"  - {error}")
        print()

    if warnings:
        print("⚠️  Warnings:")
        for warning in warnings:
            print(f"  - {warning}")
        print()

    if not errors and not warnings:
        print("✅ All validation checks passed!")
        print()
        return True

    if errors:
        print("Please fix the errors above before releasing.")
        print()
        return False

    if warnings:
        print("⚠️  Warnings found but validation passed.")
        print("Consider updating the files mentioned above.")
        print()
        return True

    return False


def main():
    args = [a for a in sys.argv[1:] if a != "--allow-dirty"]
    allow_dirty = "--allow-dirty" in sys.argv[1:]

    if len(args) != 1:
        print("Usage: python scripts/validate-release.py v1.11.4 [--allow-dirty]")
        print()
        print("  --allow-dirty   Skip the 'git working directory is clean' check.")
        print("                  Used by release.py mid-flow (uncommitted version")
        print("                  bumps are expected and not a failure condition).")
        sys.exit(1)

    version = args[0]
    if not version.startswith('v'):
        version = f'v{version}'

    success = validate_release(version, allow_dirty=allow_dirty)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
