#!/usr/bin/env python3
"""
Automated release script for ppxai.

This script handles the complete release process:
1. Check git status (clean working directory)
2. Check branch (must be on master)
3. Update all version references across the codebase
4. Validate version references with validate-release.py
5. Check/create release notes template
6. Run TypeScript lint (VSCode extension)
7. Run tests
8. Create release commit
9. Push to GitHub and trigger CI
10. Wait for CI to complete
11. Publish release notes to GitHub
12. Deploy documentation site (GitHub Pages)
13. Build Intel Mac assets (auto-detects platform)
14. Verify release assets

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

# Fix Windows console encoding for Unicode output
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')

# Project root directory
PROJECT_ROOT = Path(__file__).parent.parent

# Files that need version updates.
#
# Slimmed from 13 → 3 in 2026-05 ("Reduce version-string drift" pass):
# * `ppxai/__init__.py` re-exports `__version__` from `ppxai.version`, so
#   the only Python source-of-truth is `version.py`.
# * `ppxai/rich/event_handler.py` and `ppxai/common/logger.py` had a
#   docstring `Version: vX.Y.Z` line — replaced with a pointer to
#   `ppxai.__version__` so they no longer need patching.
# * `package-lock.json` is patched separately (typed JSON edit, not
#   regex) by `update_package_lock`.
# * READMEs / CLAUDE.md / ROADMAP.md / AGENTS.md / docs/README.md no
#   longer carry hardcoded version strings — they link to
#   https://github.com/rcconsult/ppxai/releases/latest instead.
# * The `tests/test_version_consistency.py` sentinel test enforces
#   that all surviving version strings stay in sync with `pyproject.toml`
#   on every commit, so drift between releases is impossible.
VERSION_FILES = {
    "pyproject.toml": {
        "pattern": r'version = "[\d.]+(?:\.\w+)*"',
        "replacement": 'version = "{version}"',
    },
    "ppxai/version.py": {
        "pattern": r'__version__ = "[\d.]+(?:\.\w+)*"',
        "replacement": '__version__ = "{version}"',
    },
    "vscode-extension/package.json": {
        "pattern": r'"version": "[\d.]+"',
        "replacement": '"version": "{version}"',
        "json_key": "version",
    },
}

# verify_release() body-length floor. The auto-generated `**Full Changelog**:
# https://...` link that softprops/action-gh-release emits when notes-file
# publishing fails is ~80 chars. Any real `docs/RELEASE-NOTES-v*.md` file is
# multi-paragraph and well over 500 chars. v1.18.2's second-failure mode
# (notes-file publish timed out, release body shipped with only the 80-char
# link) went undetected for ~1 hour because verify_release didn't check.
MIN_RELEASE_BODY_CHARS = 500


def run_command(cmd: str, capture: bool = True, check: bool = True) -> subprocess.CompletedProcess:
    """Run a shell command (cross-platform)."""
    print(f"  $ {cmd}")
    # Use bash on Unix, default shell on Windows
    executable = None if sys.platform == "win32" else "/bin/bash"
    result = subprocess.run(
        cmd,
        shell=True,
        executable=executable,
        cwd=PROJECT_ROOT,
        capture_output=capture,
        text=True,
        encoding='utf-8',
        errors='replace',  # Replace undecodable chars instead of failing
    )
    if check and result.returncode != 0:
        print(f"  ❌ Command failed: {result.stderr or result.stdout}")
        sys.exit(1)
    return result


def get_gh_token() -> str | None:
    """Get GH_TOKEN from the token file. Returns the token string or None."""
    token_file = PROJECT_ROOT / ".github/gh-tokenv.env"
    if token_file.exists():
        # Read token directly instead of using source
        content = token_file.read_text(encoding='utf-8')
        for line in content.split('\n'):
            if line.startswith('GH_TOKEN=') or line.startswith('export GH_TOKEN='):
                # Extract the token value
                token = line.split('=', 1)[1].strip().strip('"').strip("'")
                return token
    return None


def run_gh_command(args: str, check: bool = True) -> subprocess.CompletedProcess:
    """Run a gh CLI command with proper GH_TOKEN environment handling.

    This works cross-platform by setting the environment variable in Python
    rather than using shell-specific syntax.
    """
    # Build environment with GH_TOKEN if available
    env = os.environ.copy()
    token = get_gh_token()
    if token:
        env['GH_TOKEN'] = token

    cmd = f"gh {args}"
    print(f"  $ {cmd}")

    result = subprocess.run(
        cmd,
        shell=True,
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
        env=env,
    )

    if check and result.returncode != 0:
        print(f"  ❌ Command failed: {result.stderr or result.stdout}")
        sys.exit(1)

    return result


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
    content = pyproject.read_text(encoding='utf-8')
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

    content = full_path.read_text(encoding='utf-8')
    new_content = re.sub(pattern, replacement.format(version=version), content)

    if content == new_content:
        print(f"  ⏭️  No change needed: {filepath}")
        return False

    full_path.write_text(new_content, encoding='utf-8')
    print(f"  ✅ Updated: {filepath}")
    return True


def update_changelog_date(version: str, date: str) -> bool:
    """Substitute ``## [X.Y.Z] - unreleased`` → ``## [X.Y.Z] - <date>``.

    The "unreleased" placeholder is the canonical in-development state
    (sentinel test and ``validate-release.py`` both accept it). At
    release time, this helper rewrites it to the actual release date so
    the tagged artifact's CHANGELOG entry reflects when it shipped.

    Returns True if a substitution was performed, False if the entry was
    already dated (idempotent re-runs are safe) or missing.
    """
    changelog = PROJECT_ROOT / "CHANGELOG.md"
    if not changelog.exists():
        return False

    content = changelog.read_text(encoding='utf-8')
    pattern = rf"##\s+\[{re.escape(version)}\]\s+-\s+unreleased"
    if not re.search(pattern, content):
        # Either already dated (probable, on re-runs) or no entry at all
        # (validate-release.py will catch the latter).
        return False

    new_content = re.sub(pattern, f"## [{version}] - {date}", content)
    changelog.write_text(new_content, encoding='utf-8')
    print(f"  ✅ Updated: CHANGELOG.md ([{version}] - unreleased → {date})")
    return True


def update_package_lock(version: str):
    """Update vscode-extension/package-lock.json."""
    lock_file = PROJECT_ROOT / "vscode-extension/package-lock.json"
    if not lock_file.exists():
        return

    content = lock_file.read_text(encoding='utf-8')
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
        lock_file.write_text(json.dumps(data, indent=2) + "\n", encoding='utf-8')
        print(f"  ✅ Updated: vscode-extension/package-lock.json")


def update_readme_badges(version: str, test_count: int | None = None):
    """Update README.md version badge, test count badge, and project tree count."""
    filepath = PROJECT_ROOT / "README.md"
    if not filepath.exists():
        return

    content = filepath.read_text(encoding='utf-8')

    # Update version badge: badge/version-X.Y.Z-blue
    content = re.sub(
        r'badge/version-[\d.]+-blue',
        f'badge/version-{version}-blue',
        content
    )

    # Update test count badge if provided: badge/tests-NNNN%20passing-green
    if test_count is not None:
        content = re.sub(
            r'badge/tests-\d+%20passing-green',
            f'badge/tests-{test_count}%20passing-green',
            content
        )

    filepath.write_text(content, encoding='utf-8')
    print(f"  ✅ Updated: README.md (badges)")


def create_release_notes(version: str, date: str):
    """Create release notes file if it doesn't exist."""
    notes_file = PROJECT_ROOT / f"docs/RELEASE-NOTES-v{version}.md"

    if notes_file.exists():
        print(f"  ⏭️  Release notes already exist: {notes_file.name}")
        return

    template = f"""# Release Notes — v{version}

## Scope

[1-3 sentence summary: what kind of release (bugfix / feature / multi-theme),
the headline change, and any stability commitments. This replaces the
older `> **Scope:**` blockquote convention that became visually subtle
under GitHub's 2026-04 release-page CSS update — keep it as a top-level
heading so it remains obvious in any styling.]

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

    notes_file.write_text(template, encoding='utf-8')
    print(f"  ✅ Created: {notes_file.name}")
    print(f"  ⚠️  Please edit the release notes before continuing!")


def check_release_notes_not_template(version: str) -> bool:
    """Check if release notes exist and are not just the template."""
    notes_file = PROJECT_ROOT / f"docs/RELEASE-NOTES-v{version}.md"

    if not notes_file.exists():
        return True  # Will be created later, that's OK

    content = notes_file.read_text(encoding='utf-8')

    # Check for template placeholders
    template_markers = [
        "[Brief description of this release]",
        "[Major change 1]",
        "[Feature 1]",
        "[Fix 1]",
        "[Doc update 1]",
    ]

    for marker in template_markers:
        if marker in content:
            return False

    return True


def get_uv_command() -> str:
    """Detect the correct uv command based on local installation."""
    # Local .uv/ — Windows ships uv.exe, Unix ships uv (no extension).
    # Without the .exe check, Windows users with only .uv/uv.exe fall
    # through to `which uv` and end up returning None when only the
    # local copy is installed (defect surfaced during v1.18.1 release).
    for candidate in (".uv/uv.exe", ".uv/uv"):
        local_uv = PROJECT_ROOT / candidate
        if local_uv.exists():
            return str(local_uv)
    # Try system uv. `which` is Unix-style; on Windows we use `where`.
    cmd = "where uv" if sys.platform == "win32" else "which uv"
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if result.returncode == 0:
        return "uv"
    return None


def check_branch() -> tuple[bool, str]:
    """Check if on master branch. Returns (is_master, current_branch)."""
    result = run_command("git branch --show-current", check=False)
    branch = result.stdout.strip()
    return branch == "master", branch


def run_typescript_lint() -> bool:
    """Run TypeScript linting for VSCode extension."""
    print("\n📋 Running TypeScript lint...")

    vscode_dir = PROJECT_ROOT / "vscode-extension"
    if not vscode_dir.exists():
        print("  ⏭️  vscode-extension directory not found, skipping lint")
        return True

    # Check if npm is available
    result = subprocess.run("which npm", shell=True, capture_output=True, text=True)
    if result.returncode != 0:
        print("  ⚠️  npm not found, skipping TypeScript lint")
        return True

    # Run lint
    result = run_command(f"cd {vscode_dir} && npm run lint", check=False)
    if result.returncode == 0:
        print("  ✅ TypeScript lint passed")
        return True
    else:
        print(f"  ❌ TypeScript lint failed!")
        print(result.stdout[-1000:] if len(result.stdout) > 1000 else result.stdout)
        print(result.stderr[-500:] if len(result.stderr) > 500 else result.stderr)
        return False


def run_tests() -> tuple[bool, int]:
    """Run pytest and return (success, test_count) tuple."""
    print("\n📋 Running tests...")

    # Detect uv command
    uv_cmd = get_uv_command()

    # Build command list based on available tools.
    # --all-extras matches the CI build (.github/workflows/build.yml) and the
    # shipped binaries: without it `uv run` syncs to DEFAULT deps only and
    # strips the [data] extras (pypdfium2/python-pptx/openpyxl), so the office
    # + upload suites importorskip and the reported count is ~150 short. That
    # under-count then gets written into the README tests-NNNN badge.
    commands = []
    if uv_cmd:
        commands.append(f"{uv_cmd} run --all-extras pytest tests/ -v --tb=short")
    commands.append("python3 -m pytest tests/ -v --tb=short")
    commands.append("python -m pytest tests/ -v --tb=short")

    for cmd in commands:
        result = run_command(cmd, check=False)
        if result.returncode == 0:
            # Extract test count from output
            test_count = 0
            match = re.search(r'(\d+) passed', result.stdout)
            if match:
                test_count = int(match.group(1))
                print(f"  ✅ {test_count} tests passed")
            return True, test_count
        elif "command not found" not in result.stderr and "No module named" not in result.stderr:
            print(f"  ❌ Tests failed!")
            print(result.stdout[-2000:] if len(result.stdout) > 2000 else result.stdout)
            return False, 0

    print("  ⚠️  Could not find pytest runner")
    return False, 0


def run_validation(version: str) -> bool:
    """Run validate-release.py to ensure all files are correctly updated."""
    print("\n🔍 Validating version references...")

    # Import and run validation inline (avoid subprocess for better error messages)
    validate_script = PROJECT_ROOT / "scripts/validate-release.py"
    if not validate_script.exists():
        print("  ⚠️  validate-release.py not found, skipping validation")
        return True

    # Run validation script. Pass --allow-dirty because we're calling
    # this *after* the version-bump step but *before* the commit step,
    # so a clean working tree is structurally impossible at this point.
    # The previous heuristic ("suppress if git-dirty is the *only*
    # error") fell over when any other error was also present —
    # produced misleading "validation failed" output even when the
    # only real failure was an expected dirty tree.
    result = run_command(
        f"python3 {validate_script} v{version} --allow-dirty",
        check=False,
    )

    if result.returncode == 0:
        print("  ✅ All version references validated")
        return True

    print("  ❌ Validation failed!")
    print(result.stdout)
    return False


def create_commit(version: str, message: str) -> bool:
    """Create release commit. Returns True if commit was created, False if nothing to commit."""
    run_command("git add -A")

    # Check if there are changes to commit
    result = run_command("git status --porcelain", check=False)
    if not result.stdout.strip():
        print(f"  ⏭️  No changes to commit (version files already up to date)")
        return False

    commit_msg = message

    # Write commit message to temp file to handle multiline
    msg_file = PROJECT_ROOT / ".git/RELEASE_COMMIT_MSG"
    msg_file.write_text(commit_msg, encoding='utf-8')

    run_command(f'git commit -F "{msg_file}"')
    msg_file.unlink()

    print(f"  ✅ Created commit: {message[:50]}...")
    return True


def delete_existing_release(version: str) -> bool:
    """Delete existing GitHub release and tags for redo."""
    tag = f"v{version}"

    print(f"\n🗑️  Deleting existing release v{version}...")

    # Delete GitHub release
    result = run_gh_command(f"release delete {tag} --yes", check=False)
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


def merge_to_master_if_needed(current_branch: str, dry_run: bool = False) -> bool:
    """Merge current branch to master if not already on master.

    Returns True if successful, False if merge failed.

    `dry_run` skips every git command that has side effects — checkout,
    pull, merge — and just prints what the real run would do. The
    previous version performed all three before the dry-run summary
    block, leaving the user unexpectedly on master with a real merge
    commit. That's exactly the kind of bug a `--dry-run` flag should
    prevent.
    """
    if current_branch == "master":
        return True

    if dry_run:
        print(f"  [dry-run] Would merge {current_branch} to master")
        print(f"  [dry-run] Steps that would run:")
        print(f"    git fetch origin master")
        print(f"    git checkout master")
        print(f"    git pull origin master")
        print(f"    git merge {current_branch} --no-edit")
        return True

    print(f"  🔀 Merging {current_branch} to master...")

    # Fetch latest master
    run_command("git fetch origin master", check=False)

    # Switch to master
    result = run_command("git checkout master", check=False)
    if result.returncode != 0:
        print(f"  ❌ Failed to checkout master: {result.stderr}")
        return False

    # Pull latest master
    run_command("git pull origin master", check=False)

    # Merge feature branch into master
    result = run_command(f"git merge {current_branch} --no-edit", check=False)
    if result.returncode != 0:
        print(f"  ❌ Merge failed: {result.stderr}")
        print(f"     Resolve conflicts and try again")
        # Switch back to original branch
        run_command(f"git checkout {current_branch}", check=False)
        return False

    print(f"  ✅ Merged {current_branch} into master")
    return True


def create_and_push_tag(version: str):
    """Create tag and push to origin."""
    tag = f"v{version}"

    # Delete existing local tag if present
    run_command(f"git tag -d {tag}", check=False)

    # Create new tag
    run_command(f'git tag -a {tag} -m "{tag} release"')
    print(f"  ✅ Created tag: {tag}")

    # Push master and tag (we are guaranteed to be on master at this point)
    run_command("git push origin master")
    run_command(f"git push origin {tag} --force")
    print(f"  ✅ Pushed to origin")


def wait_for_ci(version: str, timeout_minutes: int = 10) -> bool:
    """Wait for GitHub Actions CI to complete for the specific version tag.

    v1.18.4 fix for false-negative on a stale failed run from a prior
    tag-cycle: when a `--redo` deletes the tag and re-pushes, GitHub
    needs a few seconds to register the new run. During that window
    `gh run list` still returns the OLD failed run as the most recent.
    The previous logic accepted that as authoritative whenever the
    conclusion was non-success, returning False before the new run
    even started.

    The contract now: NEVER trust a "completed" status until we have
    observed the run go through "queued" or "in_progress". Treat a
    completed run we never saw running as stale and keep polling.
    This is correct as long as the workflow takes longer than the
    poll interval (15s) — Build Executables takes minutes, so the
    new run is guaranteed to be caught in the queued/in_progress
    state before it completes.
    """
    tag = f"v{version}"
    print(f"  Waiting for CI run on tag {tag} (timeout: {timeout_minutes}min)...")

    start_time = time.time()
    timeout_seconds = timeout_minutes * 60
    seen_in_progress = False  # Track if we've seen this run actually start

    while time.time() - start_time < timeout_seconds:
        # Filter to the workflow that builds + uploads release assets.
        # Other workflows (Deploy Documentation, etc.) can complete much
        # faster and would otherwise get picked up first, causing the
        # script to declare success while binaries are still building or
        # already failing. See docs/TODO-release-tooling.md defect #1.
        result = run_gh_command(
            'run list --workflow="Build Executables" --limit 5 '
            '--json status,conclusion,name,headBranch,createdAt',
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

            # Track if we've seen this run in progress (not just completed from old run)
            if status in ("queued", "in_progress"):
                seen_in_progress = True

            if status == "completed":
                # CRITICAL: only trust a completed run if we observed it
                # in progress. Otherwise it's a stale completion from a
                # previous tag-cycle (e.g. after --redo) — the new run
                # hasn't been scheduled yet on GitHub's side. Treating
                # such a stale failure as authoritative was the v1.18.3
                # release bug; v1.18.4 makes the policy uniform: stale
                # success AND stale failure both keep us polling.
                if not seen_in_progress:
                    elapsed = int(time.time() - start_time)
                    print(
                        f"  ⏳ Stale completed run (conclusion={conclusion}); "
                        f"waiting for new CI run to start for {tag} "
                        f"({elapsed}s elapsed)"
                    )
                    time.sleep(5)
                    continue
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


def publish_release_notes(version: str, max_retries: int = 12):
    """Publish release notes to GitHub release and mark as latest."""
    notes_file = PROJECT_ROOT / f"docs/RELEASE-NOTES-v{version}.md"
    tag = f"v{version}"

    if not notes_file.exists():
        print(f"  ⚠️  Release notes not found: {notes_file}")
        return

    # Try to publish, retrying if release doesn't exist yet (CI may still be creating it)
    for attempt in range(max_retries):
        # Update release notes AND mark as latest release
        result = run_gh_command(
            f'release edit {tag} --notes-file "{notes_file}" --latest',
            check=False
        )
        if result.returncode == 0:
            print(f"  ✅ Published release notes to {tag}")
            print(f"  ✅ Marked {tag} as latest release")
            return

        if "release not found" in result.stderr.lower():
            if attempt < max_retries - 1:
                wait_time = 5 + (attempt * 5)  # 5s, 10s, 15s, 20s... up to 60s
                print(f"  ⏳ Release not found yet, retrying in {wait_time}s (attempt {attempt + 1}/{max_retries})...")
                time.sleep(wait_time)
            else:
                print(f"  ❌ Release {tag} not found after {max_retries} attempts")
                print(f"     You can manually publish notes with:")
                print(f"     gh release edit {tag} --notes-file docs/RELEASE-NOTES-{tag}.md --latest")
        else:
            print(f"  ❌ Failed to publish release notes: {result.stderr}")
            return


def deploy_docs(version: str) -> bool:
    """Trigger docs deployment for the release version.

    Uses workflow_dispatch to trigger the docs workflow with the version.
    This is needed because the docs workflow has a paths filter that may
    prevent it from running on tag pushes without doc changes.
    """
    print(f"  Triggering docs deployment for v{version}...")

    result = run_gh_command(
        f'workflow run docs.yml -f version={version}',
        check=False
    )

    if result.returncode != 0:
        print(f"  ⚠️  Failed to trigger docs deployment: {result.stderr}")
        print(f"     You can manually trigger with:")
        print(f"     gh workflow run docs.yml -f version={version}")
        return False

    print(f"  ✅ Docs deployment triggered")
    print(f"     View at: https://rcconsult.github.io/ppxai/{version}/")
    return True


def is_macos_intel() -> bool:
    """Check if running on macOS Intel (x86_64)."""
    import platform
    return platform.system() == "Darwin" and platform.machine() == "x86_64"


def build_intel_assets(version: str) -> bool:
    """Build and upload Intel Mac assets if on Intel Mac platform.

    Returns True if build was successful or skipped (non-Intel platform).
    Returns False if build failed.
    """
    build_script = PROJECT_ROOT / "scripts/build-intel.sh"

    if not build_script.exists():
        print(f"  ⚠️  build-intel.sh not found, skipping Intel build")
        return True

    # The script auto-detects platform and exits gracefully if not Intel Mac
    result = run_command(f'bash "{build_script}" v{version}', check=False)

    if result.returncode == 0:
        # Check if it actually built (vs graceful skip)
        if "Skipping macOS Intel build" in result.stdout:
            print(f"  ⏭️  Not on macOS Intel - Intel build skipped")
        else:
            print(f"  ✅ Intel Mac assets built and uploaded")
        return True
    else:
        print(f"  ❌ Intel build failed: {result.stderr or result.stdout}")
        return False


def verify_release(version: str) -> bool:
    """Verify release has all expected assets AND a non-empty release body.

    Hard-exits (sys.exit(1)) on critical failures:
      * `gh release view` fails (release was never created — CI job skipped)
      * required assets missing (a build matrix job silently skipped/failed)
      * body length below MIN_RELEASE_BODY_CHARS (notes-file publish failed,
        body shipped with only the ~80-char auto-generated changelog link)

    Warns but does not exit when:
      * body doesn't contain the first 200 chars of RELEASE-NOTES-v*.md
        (editorial drift between on-disk and published is allowed)
      * optional Intel Mac assets are missing (local build skipped)

    History:
      * v1.18.1 — 4 retag cycles; release.py reported success while the
        actual release was incomplete or absent (memory/release-lessons.md).
      * v1.18.2 first failure (2026-04-29) — build-dmg `hdiutil: Resource
        busy` flake skipped the release job; verify said "could not fetch"
        then printed "✅ Release complete" anyway.
      * v1.18.2 second failure (2026-04-29) — `gh release edit --notes-file`
        timed out; release existed with all 15 assets but body was only the
        80-char `**Full Changelog**: ...` link. verify saw 15 assets and
        "✅"-ed it; user noticed ~1 hour later.
    """
    result = run_gh_command(f"release view v{version} --json assets,body", check=False)

    if result.returncode != 0:
        print(f"  ❌ FATAL: `gh release view v{version}` failed — release was NOT created.")
        print(f"     Most common cause: a CI job failed and the `release` job was skipped.")
        print(f"     Check failed runs:   gh run list --workflow='Build Executables' --limit 3")
        print(f"     Re-run failed jobs:  gh run rerun <RUN_ID> --failed")
        sys.exit(1)

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        print(f"  ❌ FATAL: could not parse `gh release view` output as JSON.")
        sys.exit(1)

    assets = [a["name"] for a in data.get("assets", [])]
    body = data.get("body", "")

    # Required assets — every CI build job in build.yml produces one. Missing
    # any means a matrix job silently skipped or failed. v1.18.2 first-failure
    # mode (build-dmg flake) skipped the DMG; original verify_release didn't
    # check the DMG OR ppxaide binaries, so it would have ✅-ed those too.
    expected_required = [
        # VSCode extension (build-vscode job)
        f"ppxai-{version}.vsix",
        # Rich TUI binaries (build-tui job)
        "ppxai-linux-amd64",
        "ppxai-macos-arm64",
        "ppxai-windows.exe",
        # Textual TUI binaries (build-tui-textual job)
        "ppxaide-linux-amd64",
        "ppxaide-macos-arm64",
        "ppxaide-windows.exe",
        # Server binaries (build-server job)
        "ppxai-server-linux-amd64",
        "ppxai-server-macos-arm64",
        "ppxai-server-windows.exe",
        # Desktop binaries (build-desktop job, v1.13.1+)
        "ppxai-desktop-linux-amd64",
        "ppxai-desktop-macos-arm64",
        "ppxai-desktop-windows.exe",
        # macOS DMG (build-dmg job)
        f"ppxai-{version}-macos-arm64.dmg",
        # Web UI zip (build-web-ui job, v1.13.1+)
        f"ppxai-web-ui-{version}.zip",
    ]

    # Optional Intel Mac builds (built locally, not by CI)
    optional = [
        "ppxai-macos-intel",
        "ppxai-server-macos-intel",
        "ppxai-desktop-macos-intel",
    ]

    missing_required = [e for e in expected_required if e not in assets]
    missing_optional = [o for o in optional if o not in assets]

    print(f"  📦 Assets: {len(assets)} found")
    for asset in assets:
        print(f"      ✅ {asset}")

    if missing_required:
        print(f"  ❌ FATAL: {len(missing_required)} required asset(s) missing:")
        for m in missing_required:
            print(f"      ❌ {m}")
        print(f"     A build matrix job likely failed or was skipped.")
        print(f"     Check:   gh run list --workflow='Build Executables' --limit 3")
        sys.exit(1)

    if missing_optional:
        print(f"  ⏭️  Optional assets not present (Intel Mac builds — OK if local build skipped):")
        for m in missing_optional:
            print(f"      ⏭️  {m}")

    if len(body) < MIN_RELEASE_BODY_CHARS:
        print(f"  ❌ FATAL: release body is only {len(body)} chars "
              f"(threshold: {MIN_RELEASE_BODY_CHARS}).")
        print(f"     Release-notes publishing failed silently. Recover with:")
        print(f"     gh release edit v{version} \\")
        print(f"       --notes-file docs/RELEASE-NOTES-v{version}.md")
        sys.exit(1)

    notes_path = PROJECT_ROOT / f"docs/RELEASE-NOTES-v{version}.md"
    if notes_path.exists():
        expected_prefix = notes_path.read_text(encoding="utf-8").strip()[:200]
        if expected_prefix and expected_prefix not in body:
            print(f"  ⚠️  WARNING: release body does not contain the first 200 chars")
            print(f"     of docs/RELEASE-NOTES-v{version}.md — manual review recommended.")

    print(f"  ✅ {len(assets)} assets verified, body {len(body)} chars.")
    return True


def print_step(step: int, total: int, title: str, step_times: list = None):
    """Print a prominent step header. Optionally record previous step time."""
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

    # Check branch early to calculate steps correctly
    is_master_early, current_branch_early = check_branch()

    # Calculate total steps based on flags
    # Base steps: Git check, Branch check, Update versions, Validate, Release notes, TS Lint, Tests, Commit, Push, CI wait, Publish notes, Deploy docs, Intel build, Verify = 14
    total_steps = 14
    if args.redo:
        total_steps += 1  # Add "Delete existing release" step
    if args.skip_tests:
        total_steps -= 1  # Remove "Run tests" step
    if args.skip_ci_wait:
        total_steps -= 1  # Remove "Wait for CI" step
    if not is_master_early and args.force:
        total_steps += 1  # Add "Merge to Master" step

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
    step_times = []  # Track (step_name, duration) tuples
    step_start = time.time()
    total_start = time.time()

    def record_step(name: str):
        """Record the time for the current step."""
        nonlocal step_start
        duration = time.time() - step_start
        step_times.append((name, duration))
        step_start = time.time()

    # Step 1: Check git status
    step += 1
    print_step(step, total_steps, "Checking Git Status")
    if not check_git_clean() and not args.force:
        print(f"  ❌ Git working directory is not clean")
        print(f"     Commit or stash changes first, or use --force")
        sys.exit(1)
    print(f"  ✅ Git working directory is clean")
    record_step("Git Status")

    # Step 2: Check branch
    step += 1
    print_step(step, total_steps, "Checking Branch")
    is_master, current_branch = check_branch()
    if not is_master and not args.force:
        print(f"  ❌ Not on master branch (current: {current_branch})")
        print(f"     Switch to master first: git checkout master")
        print(f"     Or use --force to release from {current_branch} (will merge to master)")
        sys.exit(1)
    if is_master:
        print(f"  ✅ On master branch")
    else:
        print(f"  ⚠️  On {current_branch} branch (--force used, will merge to master)")
    record_step("Branch Check")

    # Step 2b: Merge to master if on feature branch
    if not is_master:
        step += 1
        print_step(step, total_steps, "Merging to Master")
        if not merge_to_master_if_needed(current_branch, dry_run=args.dry_run):
            print(f"\n❌ Failed to merge {current_branch} to master")
            print(f"   Resolve any conflicts and try again")
            sys.exit(1)
        record_step("Merge to Master")

    # Pre-flight check: Warn if release notes are still template
    if not check_release_notes_not_template(version):
        notes_file = f"docs/RELEASE-NOTES-v{version}.md"
        print(f"\n  ⚠️  WARNING: Release notes appear to be template!")
        print(f"     File: {notes_file}")
        print(f"     Please edit the release notes with actual content before proceeding.")
        print(f"     The release will continue, but GitHub release notes will be incomplete.")
        print(f"")
        if not args.force:
            response = input("     Continue anyway? [y/N]: ").strip().lower()
            if response != 'y':
                print(f"\n  ❌ Aborted. Edit {notes_file} and try again.")
                sys.exit(1)

    # Optional: Handle --redo: delete existing release first
    if args.redo:
        step += 1
        print_step(step, total_steps, "Deleting Existing Release")
        delete_existing_release(version)
        record_step("Delete Release")

    if args.dry_run:
        print(f"\n📋 DRY RUN - Would execute the following steps:\n")

        dry_step = 0

        # Show merge step if on feature branch
        if not is_master_early:
            dry_step += 1
            print(f"  {dry_step}. 🔀 Merge {current_branch_early} to master")

        # Version updates
        dry_step += 1
        print(f"  {dry_step}. 📝 Update version files:")
        for filepath in VERSION_FILES:
            print(f"       - {filepath}")
        print(f"       - vscode-extension/package-lock.json (typed JSON edit)")
        print(f"       - README.md (version + test-count badges)")
        print(f"       - CHANGELOG.md (substitute `unreleased` → today's date)")

        # Validation
        dry_step += 1
        print(f"  {dry_step}. 🔍 Validate version references")

        # Release notes
        dry_step += 1
        notes_file = f"docs/RELEASE-NOTES-v{version}.md"
        notes_exist = (PROJECT_ROOT / notes_file).exists()
        if notes_exist:
            print(f"  {dry_step}. 📄 Check release notes (exists: {notes_file})")
        else:
            print(f"  {dry_step}. 📄 Create release notes template: {notes_file}")

        # TypeScript lint
        dry_step += 1
        print(f"  {dry_step}. 📋 Run TypeScript lint")

        # Tests
        if not args.skip_tests:
            dry_step += 1
            print(f"  {dry_step}. 🧪 Run tests")

        # Commit
        dry_step += 1
        print(f"  {dry_step}. 💾 Create commit: feat: v{version} release")

        # Push
        dry_step += 1
        print(f"  {dry_step}. 🚀 Push to GitHub (master + tag v{version})")

        # CI wait
        if not args.skip_ci_wait:
            dry_step += 1
            print(f"  {dry_step}. ⏳ Wait for CI to complete")

        # Publish notes
        dry_step += 1
        print(f"  {dry_step}. 📢 Publish release notes to GitHub")

        # Intel build
        dry_step += 1
        print(f"  {dry_step}. 🖥️  Build Intel Mac assets (if on Intel Mac)")

        # Verify
        dry_step += 1
        print(f"  {dry_step}. ✅ Verify release assets")

        print(f"\n{'━' * 50}")
        print(f"  Total steps: {dry_step}")
        print(f"{'━' * 50}")
        print(f"\n✅ Dry run complete. Use without --dry-run to execute.")
        return

    # Step 3: Update version files
    step += 1
    print_step(step, total_steps, "Updating Version References")
    for filepath, config in VERSION_FILES.items():
        update_version_in_file(filepath, config["pattern"], config["replacement"], version)

    # Update package-lock.json (typed JSON edit — not a regex; lock file
    # is a derived artifact but kept in tree, so we edit it directly to
    # avoid making npm a release-tooling dependency).
    update_package_lock(version)

    # Update README.md badges (version only, test count updated after tests pass)
    update_readme_badges(version)

    # Update docs/index.md version badge (shields.io image URL)
    index_path = PROJECT_ROOT / "docs/index.md"
    if index_path.exists():
        content = index_path.read_text(encoding='utf-8')
        new_content = re.sub(
            r'(img\.shields\.io/badge/version-)[\d.]+(-blue)',
            rf'\g<1>{version}\2',
            content
        )
        if new_content != content:
            index_path.write_text(new_content, encoding='utf-8')
            print(f"  ✅ Updated: docs/index.md")

    # Substitute ``## [X.Y.Z] - unreleased`` → ``## [X.Y.Z] - <today>`` in
    # CHANGELOG.md. The placeholder is the canonical state during
    # development (sentinel + validate-release.py both accept it). The
    # dated form is what ships in the released artifact.
    update_changelog_date(version, date)

    record_step("Update Versions")

    # Step 4: Validate all version references
    step += 1
    print_step(step, total_steps, "Validating Version References")
    if not run_validation(version):
        print(f"\n❌ Validation failed. Some files may not have been updated correctly.")
        print(f"   Run: python scripts/validate-release.py v{version}")
        sys.exit(1)
    record_step("Validation")

    # Step 5: Check/create release notes
    step += 1
    print_step(step, total_steps, "Checking Release Notes")
    create_release_notes(version, date)
    record_step("Release Notes")

    # Step 6: Run TypeScript lint
    step += 1
    print_step(step, total_steps, "Running TypeScript Lint")
    if not run_typescript_lint():
        print(f"\n❌ TypeScript lint failed. Fix issues and try again.")
        sys.exit(1)
    record_step("TS Lint")

    # Step 7: Run tests
    if not args.skip_tests:
        step += 1
        print_step(step, total_steps, "Running Tests")
        tests_passed, test_count = run_tests()
        if not tests_passed:
            print(f"\n❌ Tests failed. Fix issues and try again.")
            sys.exit(1)
        # Update README badges with actual test count
        if test_count > 0:
            update_readme_badges(version, test_count)
        record_step("Tests")

    # Step 8: Create commit
    step += 1
    print_step(step, total_steps, "Creating Release Commit")
    create_commit(version, f"feat: v{version} release")
    record_step("Commit")

    # Step 9: Create and push tag
    step += 1
    print_step(step, total_steps, "Pushing to GitHub")
    create_and_push_tag(version)
    record_step("Push")

    # Step 10: Wait for CI
    if not args.skip_ci_wait:
        step += 1
        print_step(step, total_steps, "Waiting for CI")
        if not wait_for_ci(version):
            print(f"\n⚠️  CI did not complete successfully")
            print(f"    Check: https://github.com/rcconsult/ppxai/actions")
        record_step("CI Wait")

    # Step 11: Publish release notes
    step += 1
    print_step(step, total_steps, "Publishing Release Notes")
    publish_release_notes(version)
    record_step("Publish Notes")

    # Step 12: Deploy documentation site
    step += 1
    print_step(step, total_steps, "Deploying Documentation")
    if not deploy_docs(version):
        print(f"\n⚠️  Docs deployment failed, but release continues")
    record_step("Deploy Docs")

    # Step 13: Build Intel Mac assets (auto-detects platform)
    step += 1
    print_step(step, total_steps, "Building Intel Mac Assets")
    if not build_intel_assets(version):
        print(f"\n⚠️  Intel build failed, but release continues")
    record_step("Intel Build")

    # Step 14: Verify release
    step += 1
    print_step(step, total_steps, "Verifying Release")
    verify_release(version)
    record_step("Verify")

    # Done - print timing summary
    total_time = time.time() - total_start
    print(f"\n{'━' * 50}")
    print(f"  ✅ Release v{version} complete!")
    print(f"{'━' * 50}")
    print(f"  https://github.com/rcconsult/ppxai/releases/tag/v{version}")
    print(f"\n  ⏱️  Timing Summary:")
    for step_name, duration in step_times:
        print(f"      {step_name:.<20} {duration:>6.1f}s")
    print(f"      {'─' * 27}")
    print(f"      {'Total':.<20} {total_time:>6.1f}s")


if __name__ == "__main__":
    main()
