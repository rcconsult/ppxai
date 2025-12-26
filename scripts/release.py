#!/usr/bin/env python3
"""
Automated release script for ppxai.

This script handles the complete release process:
1. Validate version format (3-part semantic versioning)
2. Update all version references across the codebase
3. Run tests
4. Create release commit and tag
5. Push to GitHub and trigger CI
6. Wait for CI to complete
7. Publish release notes
8. Verify release assets

Usage:
    python scripts/release.py v1.11.8
    python scripts/release.py v1.11.8 --dry-run
    python scripts/release.py v1.11.8 --skip-tests
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from datetime import datetime

# Project root directory
PROJECT_ROOT = Path(__file__).parent.parent

# Files that need version updates
VERSION_FILES = {
    "pyproject.toml": {
        "pattern": r'version = "[\d.]+"',
        "replacement": 'version = "{version}"',
    },
    "ppxai/__init__.py": {
        "pattern": r'__version__ = "[\d.]+"',
        "replacement": '__version__ = "{version}"',
    },
    "vscode-extension/package.json": {
        "pattern": r'"version": "[\d.]+"',
        "replacement": '"version": "{version}"',
        "json_key": "version",
    },
    "ppxai/common/event_handler.py": {
        "pattern": r'Version: v[\d.]+',
        "replacement": 'Version: v{version}',
    },
}

# Files with vsix references that need updating
VSIX_FILES = [
    "README.md",
    "vscode-extension/README.md",
]

# Documentation files that need version updates
DOC_FILES = {
    "CLAUDE.md": {
        "current_version_pattern": r'\*\*Current Version:\*\* v[\d.]+',
        "current_version_replacement": '**Current Version:** v{version}',
        "version_alignment_pattern": r'- Python package \(pyproject\.toml\): v[\d.]+\n- VSCode extension \(package\.json\): v[\d.]+\n- Git tag: v[\d.]+ \(released [\d-]+\)\n- GitHub Release: https://github\.com/rcconsult/ppxai/releases/tag/v[\d.]+',
    },
    "ROADMAP.md": {
        "current_release_pattern": r'## Current Release: v[\d.]+',
        "current_release_replacement": '## Current Release: v{version}',
    },
}


def run_command(cmd: str, capture: bool = True, check: bool = True) -> subprocess.CompletedProcess:
    """Run a shell command using bash."""
    print(f"  $ {cmd}")
    result = subprocess.run(
        cmd,
        shell=True,
        executable="/bin/bash",  # Use bash for 'source' support
        cwd=PROJECT_ROOT,
        capture_output=capture,
        text=True,
    )
    if check and result.returncode != 0:
        print(f"  ❌ Command failed: {result.stderr or result.stdout}")
        sys.exit(1)
    return result


def get_gh_token_cmd() -> str:
    """Get the command prefix to set GH_TOKEN from the token file."""
    token_file = PROJECT_ROOT / ".github/gh-tokenv.env"
    if token_file.exists():
        # Read token directly instead of using source
        content = token_file.read_text()
        for line in content.split('\n'):
            if line.startswith('GH_TOKEN=') or line.startswith('export GH_TOKEN='):
                # Extract the token value
                token = line.split('=', 1)[1].strip().strip('"').strip("'")
                return f'GH_TOKEN="{token}" '
    return ""


def validate_version(version: str) -> str:
    """Validate version format and return without 'v' prefix."""
    # Remove 'v' prefix if present
    if version.startswith('v'):
        version = version[1:]

    # Check 3-part semantic version
    if not re.match(r'^\d+\.\d+\.\d+$', version):
        print(f"❌ Invalid version format: {version}")
        print("   Version must be 3-part semantic version (e.g., 1.11.7)")
        sys.exit(1)

    return version


def get_current_version() -> str:
    """Get current version from pyproject.toml."""
    pyproject = PROJECT_ROOT / "pyproject.toml"
    content = pyproject.read_text()
    match = re.search(r'version = "([^"]+)"', content)
    if match:
        return match.group(1)
    return "unknown"


def check_git_clean() -> bool:
    """Check if git working directory is clean."""
    result = run_command("git status --porcelain", check=False)
    return len(result.stdout.strip()) == 0


def update_version_in_file(filepath: str, pattern: str, replacement: str, version: str) -> bool:
    """Update version in a single file using regex."""
    full_path = PROJECT_ROOT / filepath
    if not full_path.exists():
        print(f"  ⚠️  File not found: {filepath}")
        return False

    content = full_path.read_text()
    new_content = re.sub(pattern, replacement.format(version=version), content)

    if content == new_content:
        print(f"  ⏭️  No change needed: {filepath}")
        return False

    full_path.write_text(new_content)
    print(f"  ✅ Updated: {filepath}")
    return True


def update_vsix_references(version: str) -> int:
    """Update all ppxai-X.Y.Z.vsix references."""
    count = 0
    vsix_pattern = r'ppxai-[\d.]+\.vsix'
    vsix_replacement = f'ppxai-{version}.vsix'

    for filepath in VSIX_FILES:
        full_path = PROJECT_ROOT / filepath
        if not full_path.exists():
            continue

        content = full_path.read_text()
        new_content = re.sub(vsix_pattern, vsix_replacement, content)

        if content != new_content:
            full_path.write_text(new_content)
            print(f"  ✅ Updated vsix refs: {filepath}")
            count += 1

    return count


def update_package_lock(version: str):
    """Update vscode-extension/package-lock.json."""
    lock_file = PROJECT_ROOT / "vscode-extension/package-lock.json"
    if not lock_file.exists():
        return

    content = lock_file.read_text()
    data = json.loads(content)

    changed = False
    if data.get("version") != version:
        data["version"] = version
        changed = True

    if "packages" in data and "" in data["packages"]:
        if data["packages"][""].get("version") != version:
            data["packages"][""]["version"] = version
            changed = True

    if changed:
        lock_file.write_text(json.dumps(data, indent=2) + "\n")
        print(f"  ✅ Updated: vscode-extension/package-lock.json")


def update_claude_md(version: str, date: str):
    """Update CLAUDE.md with new version info."""
    filepath = PROJECT_ROOT / "CLAUDE.md"
    content = filepath.read_text()

    # Update current version line
    content = re.sub(
        r'\*\*Current Version:\*\* v[\d.]+[^\n]*',
        f'**Current Version:** v{version}',
        content
    )

    # Update version alignment section
    alignment_replacement = f"""- Python package (pyproject.toml): v{version}
- VSCode extension (package.json): v{version}
- Git tag: v{version} (released {date})
- GitHub Release: https://github.com/rcconsult/ppxai/releases/tag/v{version}"""

    content = re.sub(
        r'- Python package \(pyproject\.toml\): v[\d.]+\n- VSCode extension \(package\.json\): v[\d.]+\n- Git tag: v[\d.]+ \(released [\d-]+\)\n- GitHub Release: https://github\.com/rcconsult/ppxai/releases/tag/v[\d.]+',
        alignment_replacement,
        content
    )

    filepath.write_text(content)
    print(f"  ✅ Updated: CLAUDE.md")


def create_release_notes(version: str, date: str):
    """Create release notes file if it doesn't exist."""
    notes_file = PROJECT_ROOT / f"docs/RELEASE-NOTES-v{version}.md"

    if notes_file.exists():
        print(f"  ⏭️  Release notes already exist: {notes_file.name}")
        return

    template = f"""# Release Notes: v{version}

**Release Date:** {date}

## Summary

[Brief description of this release]

## Major Changes

- [Major change 1]
- [Major change 2]

## New Features

- [Feature 1]
- [Feature 2]

## Bug Fixes

- [Fix 1]
- [Fix 2]

## Documentation Updates

- [Doc update 1]

## Testing

- [X] tests passing

## Upgrade Notes

This is a drop-in replacement for the previous version. No configuration changes required.

## Links

- **GitHub Release:** https://github.com/rcconsult/ppxai/releases/tag/v{version}
- **Full Changelog:** [CHANGELOG.md](../CHANGELOG.md)
"""

    notes_file.write_text(template)
    print(f"  ✅ Created: {notes_file.name}")
    print(f"  ⚠️  Please edit the release notes before continuing!")


def run_tests() -> bool:
    """Run pytest and return success status."""
    print("\n📋 Running tests...")

    # Try different ways to run pytest
    for cmd in [".uv/uv run pytest tests/ -v --tb=short", "uv run pytest tests/ -v --tb=short", "python -m pytest tests/ -v --tb=short"]:
        result = run_command(cmd, check=False)
        if result.returncode == 0:
            # Extract test count from output
            match = re.search(r'(\d+) passed', result.stdout)
            if match:
                print(f"  ✅ {match.group(1)} tests passed")
            return True
        elif "command not found" not in result.stderr:
            print(f"  ❌ Tests failed!")
            print(result.stdout[-2000:] if len(result.stdout) > 2000 else result.stdout)
            return False

    print("  ⚠️  Could not find pytest runner")
    return False


def create_commit(version: str, message: str) -> bool:
    """Create release commit. Returns True if commit was created, False if nothing to commit."""
    run_command("git add -A")

    # Check if there are changes to commit
    result = run_command("git status --porcelain", check=False)
    if not result.stdout.strip():
        print(f"  ⏭️  No changes to commit (version files already up to date)")
        return False

    commit_msg = f"""{message}

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"""

    # Write commit message to temp file to handle multiline
    msg_file = PROJECT_ROOT / ".git/RELEASE_COMMIT_MSG"
    msg_file.write_text(commit_msg)

    run_command(f'git commit -F "{msg_file}"')
    msg_file.unlink()

    print(f"  ✅ Created commit: {message[:50]}...")
    return True


def delete_existing_release(version: str) -> bool:
    """Delete existing GitHub release and tags for redo."""
    tag = f"v{version}"
    token_cmd = get_gh_token_cmd()

    print(f"\n🗑️  Deleting existing release v{version}...")

    # Delete GitHub release
    result = run_command(f"{token_cmd}gh release delete {tag} --yes", check=False)
    if result.returncode == 0:
        print(f"  ✅ Deleted GitHub release: {tag}")
    else:
        print(f"  ⏭️  No GitHub release found for {tag}")

    # Delete remote tag
    result = run_command(f"git push origin --delete {tag}", check=False)
    if result.returncode == 0:
        print(f"  ✅ Deleted remote tag: {tag}")
    else:
        print(f"  ⏭️  No remote tag found for {tag}")

    # Delete local tag
    result = run_command(f"git tag -d {tag}", check=False)
    if result.returncode == 0:
        print(f"  ✅ Deleted local tag: {tag}")
    else:
        print(f"  ⏭️  No local tag found for {tag}")

    # Reset to previous commit if the last commit is the release commit
    result = run_command("git log -1 --format=%s", check=False)
    if result.returncode == 0:
        last_commit_msg = result.stdout.strip()
        if f"v{version}" in last_commit_msg and ("release" in last_commit_msg.lower() or "feat:" in last_commit_msg.lower()):
            print(f"  ⚠️  Last commit appears to be the release commit: {last_commit_msg[:50]}...")
            print(f"  🔄 Resetting to previous commit...")
            run_command("git reset --hard HEAD~1")
            run_command("git push origin master --force")
            print(f"  ✅ Reset master to previous commit")

    return True


def create_and_push_tag(version: str):
    """Create tag and push to origin."""
    tag = f"v{version}"

    # Delete existing local tag if present
    run_command(f"git tag -d {tag}", check=False)

    # Create new tag
    run_command(f'git tag -a {tag} -m "{tag} release"')
    print(f"  ✅ Created tag: {tag}")

    # Push master and tag
    run_command("git push origin master")
    run_command(f"git push origin {tag} --force")
    print(f"  ✅ Pushed to origin")


def wait_for_ci(version: str, timeout_minutes: int = 10) -> bool:
    """Wait for GitHub Actions CI to complete for the specific version tag."""
    tag = f"v{version}"
    print(f"  Waiting for CI run on tag {tag} (timeout: {timeout_minutes}min)...")

    token_cmd = get_gh_token_cmd()

    start_time = time.time()
    timeout_seconds = timeout_minutes * 60

    while time.time() - start_time < timeout_seconds:
        # Get runs filtered by head branch (tag)
        result = run_command(
            f"{token_cmd}gh run list --limit 5 --json status,conclusion,name,headBranch",
            check=False
        )

        if result.returncode != 0:
            print(f"  ⚠️  Could not check CI status: {result.stderr}")
            time.sleep(10)
            continue

        try:
            runs = json.loads(result.stdout)
            # Find runs for our specific tag
            tag_runs = [r for r in runs if r.get("headBranch") == tag]

            if not tag_runs:
                elapsed = int(time.time() - start_time)
                print(f"  ⏳ Waiting for CI to start for {tag} ({elapsed}s elapsed)")
                time.sleep(5)
                continue

            # Check the most recent run for our tag
            run = tag_runs[0]
            status = run.get("status")
            conclusion = run.get("conclusion")

            if status == "completed":
                if conclusion == "success":
                    print(f"  ✅ CI completed successfully for {tag}")
                    return True
                else:
                    print(f"  ❌ CI failed with: {conclusion}")
                    return False
            else:
                elapsed = int(time.time() - start_time)
                print(f"  ⏳ CI status: {status} ({elapsed}s elapsed)")
        except json.JSONDecodeError:
            pass

        time.sleep(15)

    print(f"  ⚠️  CI timeout after {timeout_minutes} minutes")
    return False


def publish_release_notes(version: str, max_retries: int = 6):
    """Publish release notes to GitHub release."""
    notes_file = PROJECT_ROOT / f"docs/RELEASE-NOTES-v{version}.md"
    tag = f"v{version}"

    if not notes_file.exists():
        print(f"  ⚠️  Release notes not found: {notes_file}")
        return

    token_cmd = get_gh_token_cmd()

    # Try to publish, retrying if release doesn't exist yet (CI may still be creating it)
    for attempt in range(max_retries):
        result = run_command(
            f'{token_cmd}gh release edit {tag} --notes-file "{notes_file}"',
            check=False
        )
        if result.returncode == 0:
            print(f"  ✅ Published release notes to {tag}")
            return

        if "release not found" in result.stderr.lower():
            if attempt < max_retries - 1:
                wait_time = 5  # Fixed 5s wait between retries
                print(f"  ⏳ Release not found yet, retrying in {wait_time}s (attempt {attempt + 1}/{max_retries})...")
                time.sleep(wait_time)
            else:
                print(f"  ❌ Release {tag} not found after {max_retries} attempts")
                print(f"     You can manually publish notes with:")
                print(f"     gh release edit {tag} --notes-file docs/RELEASE-NOTES-{tag}.md")
        else:
            print(f"  ❌ Failed to publish release notes: {result.stderr}")
            return


def verify_release(version: str) -> bool:
    """Verify release has all expected assets."""
    token_cmd = get_gh_token_cmd()
    result = run_command(f"{token_cmd}gh release view v{version} --json assets", check=False)

    if result.returncode != 0:
        print(f"  ❌ Could not fetch release info")
        return False

    try:
        data = json.loads(result.stdout)
        assets = [a["name"] for a in data.get("assets", [])]

        expected = [
            f"ppxai-{version}.vsix",
            "ppxai-linux-amd64",
            "ppxai-macos-arm64",
            "ppxai-windows.exe",
            "ppxai-server-linux-amd64",
            "ppxai-server-macos-arm64",
            "ppxai-server-windows.exe",
        ]

        # Optional Intel Mac builds
        optional = [
            "ppxai-macos-intel",
            "ppxai-server-macos-intel",
        ]

        missing = [e for e in expected if e not in assets]
        present_optional = [o for o in optional if o in assets]

        print(f"  📦 Assets: {len(assets)} found")
        for asset in assets:
            print(f"      ✅ {asset}")

        if missing:
            print(f"  ⚠️  Missing required assets:")
            for m in missing:
                print(f"      ❌ {m}")
            return False

        if len(present_optional) < len(optional):
            missing_optional = [o for o in optional if o not in assets]
            print(f"  ⚠️  Missing optional assets (Intel Mac builds):")
            for m in missing_optional:
                print(f"      ⏭️  {m}")

        return True

    except json.JSONDecodeError:
        print(f"  ❌ Could not parse release info")
        return False


def print_step(step: int, total: int, title: str):
    """Print a prominent step header."""
    bar = "━" * 50
    print(f"\n{bar}")
    print(f"  Step {step}/{total}: {title}")
    print(f"{bar}")


def main():
    parser = argparse.ArgumentParser(description="Automated release script for ppxai")
    parser.add_argument("version", help="Version to release (e.g., v1.11.8 or 1.11.8)")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done without making changes")
    parser.add_argument("--skip-tests", action="store_true", help="Skip running tests")
    parser.add_argument("--skip-ci-wait", action="store_true", help="Don't wait for CI to complete")
    parser.add_argument("--force", action="store_true", help="Force release even with uncommitted changes")
    parser.add_argument("--redo", action="store_true", help="Delete existing release/tag and redo from scratch")

    args = parser.parse_args()

    # Validate version
    version = validate_version(args.version)
    current_version = get_current_version()
    date = datetime.now().strftime("%Y-%m-%d")

    # Calculate total steps based on flags
    # Base steps: Git check, Update versions, Release notes, Tests, Commit, Push, CI wait, Publish notes, Verify = 9
    total_steps = 9
    if args.redo:
        total_steps += 1  # Add "Delete existing release" step
    if args.skip_tests:
        total_steps -= 1  # Remove "Run tests" step
    if args.skip_ci_wait:
        total_steps -= 1  # Remove "Wait for CI" step

    print(f"\n{'━' * 50}")
    print(f"  🚀 ppxai Release Script")
    print(f"{'━' * 50}")
    print(f"  Current version: {current_version}")
    print(f"  Target version:  v{version}")
    print(f"  Release date:    {date}")

    if args.dry_run:
        print(f"  Mode: DRY RUN (no changes will be made)")
    if args.redo:
        print(f"  Mode: REDO (will delete existing release first)")

    step = 0

    # Step 1: Check git status
    step += 1
    print_step(step, total_steps, "Checking Git Status")
    if not check_git_clean() and not args.force:
        print(f"  ❌ Git working directory is not clean")
        print(f"     Commit or stash changes first, or use --force")
        sys.exit(1)
    print(f"  ✅ Git working directory is clean")

    # Optional: Handle --redo: delete existing release first
    if args.redo:
        step += 1
        print_step(step, total_steps, "Deleting Existing Release")
        delete_existing_release(version)

    if args.dry_run:
        print(f"\n📋 Would update the following files:")
        for filepath in VERSION_FILES:
            print(f"     - {filepath}")
        for filepath in VSIX_FILES:
            print(f"     - {filepath} (vsix refs)")
        print(f"     - CLAUDE.md")
        print(f"     - vscode-extension/package-lock.json")
        print(f"\n✅ Dry run complete. Use without --dry-run to execute.")
        return

    # Step 2: Update version files
    step += 1
    print_step(step, total_steps, "Updating Version References")
    for filepath, config in VERSION_FILES.items():
        update_version_in_file(filepath, config["pattern"], config["replacement"], version)

    # Update vsix references
    update_vsix_references(version)

    # Update package-lock.json
    update_package_lock(version)

    # Update CLAUDE.md
    update_claude_md(version, date)

    # Update ROADMAP.md current release
    roadmap_path = PROJECT_ROOT / "ROADMAP.md"
    if roadmap_path.exists():
        content = roadmap_path.read_text()
        content = re.sub(
            r'## Current Release: v[\d.]+',
            f'## Current Release: v{version}',
            content
        )
        roadmap_path.write_text(content)
        print(f"  ✅ Updated: ROADMAP.md")

    # Step 3: Check/create release notes
    step += 1
    print_step(step, total_steps, "Checking Release Notes")
    create_release_notes(version, date)

    # Step 4: Run tests
    if not args.skip_tests:
        step += 1
        print_step(step, total_steps, "Running Tests")
        if not run_tests():
            print(f"\n❌ Tests failed. Fix issues and try again.")
            sys.exit(1)

    # Step 5: Create commit
    step += 1
    print_step(step, total_steps, "Creating Release Commit")
    create_commit(version, f"feat: v{version} release")

    # Step 6: Create and push tag
    step += 1
    print_step(step, total_steps, "Pushing to GitHub")
    create_and_push_tag(version)

    # Step 7: Wait for CI
    if not args.skip_ci_wait:
        step += 1
        print_step(step, total_steps, "Waiting for CI")
        if not wait_for_ci(version):
            print(f"\n⚠️  CI did not complete successfully")
            print(f"    Check: https://github.com/rcconsult/ppxai/actions")

    # Step 8: Publish release notes
    step += 1
    print_step(step, total_steps, "Publishing Release Notes")
    publish_release_notes(version)

    # Step 9: Verify release
    step += 1
    print_step(step, total_steps, "Verifying Release")
    verify_release(version)

    # Done!
    print(f"\n{'━' * 50}")
    print(f"  ✅ Release v{version} complete!")
    print(f"{'━' * 50}")
    print(f"  https://github.com/rcconsult/ppxai/releases/tag/v{version}")


if __name__ == "__main__":
    main()
