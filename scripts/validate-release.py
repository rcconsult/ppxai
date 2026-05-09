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

    # Check version files.
    #
    # Slimmed in 2026-05 ("Reduce version-string drift" pass) — most
    # markdown / source files no longer carry hardcoded version strings.
    # `tests/test_version_consistency.py` is the day-to-day enforcer
    # (runs on every commit); this list is the pre-tag fail-safe.
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
            "file": "vscode-extension/package-lock.json",
            "pattern": r'"version":\s*"{version}"',
            "critical": True,
        },
        # CHANGELOG must have an entry for this version. Accept either
        # the dated form ``## [X.Y.Z] - 2026-05-02`` (post-release) or
        # the in-development placeholder ``## [X.Y.Z] - unreleased``.
        # ``release.py`` substitutes the placeholder with today's date
        # as a release-time step, so by the time the tag is pushed only
        # the dated form survives.
        {
            "file": "CHANGELOG.md",
            "pattern": r"##\s+\[{version}\]\s+-\s+(?:\d{{4}}-\d{{2}}-\d{{2}}|unreleased)",
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

    # Release notes existence check.
    #
    # Added 2026-05-10 after a v1.18.4 pre-flight near-miss: every
    # release since v1.15.x has shipped a `docs/RELEASE-NOTES-vX.Y.Z.md`
    # narrative companion to the CHANGELOG entry, but the validator
    # never enforced it. The file is named in the CLAUDE.md
    # "Pre-release checklist" item 2 as required, but humans (and AI
    # assistants) drifted into running validate-release.py and treating
    # green as "ready to tag" — without noticing the notes file was
    # never created.
    notes_file = project_root / f"docs/RELEASE-NOTES-{version}.md"
    if not notes_file.exists():
        errors.append(
            f"docs/RELEASE-NOTES-{version}.md: missing — every release "
            "ships a narrative release-notes file alongside the "
            "CHANGELOG entry (see prior RELEASE-NOTES-v1.18.{1,2,3}.md "
            "for the convention)"
        )

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
