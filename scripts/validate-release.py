#!/usr/bin/env python3
"""
Validate that all files have been updated for a release.

Usage:
    python scripts/validate-release.py v1.11.4
"""
import re
import sys
from pathlib import Path


def check_version_in_file(file_path: Path, version: str, pattern: str) -> bool:
    """Check if version appears in file matching pattern."""
    if not file_path.exists():
        return False

    content = file_path.read_text()
    match = re.search(pattern.format(version=re.escape(version)), content)
    return match is not None


def validate_release(version: str) -> bool:
    """Validate all files have been updated for the release."""
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
            "file": "ppxai/common/event_handler.py",
            "pattern": r"Version:\s+v{version}",
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

    # Check that git is clean
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
    if len(sys.argv) != 2:
        print("Usage: python scripts/validate-release.py v1.11.4")
        sys.exit(1)

    version = sys.argv[1]
    if not version.startswith('v'):
        version = f'v{version}'

    success = validate_release(version)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
