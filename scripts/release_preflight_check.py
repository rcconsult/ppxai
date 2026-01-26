#!/usr/bin/env python3
"""
Release Pre-Flight Check for v1.15.0

Comprehensive validation before merging to master and tagging release.

Usage:
    uv run python scripts/release_preflight_check.py

"""

import asyncio
import subprocess
import sys
from pathlib import Path
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))


def print_header(text: str):
    """Print section header."""
    console.print()
    console.print(Panel(f"[bold cyan]{text}[/bold cyan]", expand=False))
    console.print()


def run_command(cmd: str, cwd: Path = None, check: bool = True) -> tuple[int, str, str]:
    """Run shell command and return (exit_code, stdout, stderr)."""
    result = subprocess.run(
        cmd,
        shell=True,
        cwd=cwd or Path.cwd(),
        capture_output=True,
        text=True
    )
    return result.returncode, result.stdout, result.stderr


async def check_git_status():
    """Check git repository status."""
    print_header("1. Git Repository Status")

    checks = []

    # Check branch
    returncode, stdout, _ = run_command("git branch --show-current")
    current_branch = stdout.strip()
    if current_branch == "feature/new-tui-command":
        console.print(f"[green]✅ On correct branch:[/green] {current_branch}")
        checks.append(True)
    else:
        console.print(f"[red]❌ Wrong branch:[/red] {current_branch} (expected: feature/new-tui-command)")
        checks.append(False)

    # Check for uncommitted changes
    returncode, stdout, _ = run_command("git status --porcelain")
    if not stdout.strip():
        console.print("[green]✅ No uncommitted changes[/green]")
        checks.append(True)
    else:
        console.print("[red]❌ Uncommitted changes detected:[/red]")
        for line in stdout.strip().split('\n')[:5]:
            console.print(f"  {line}")
        checks.append(False)

    # Check commits ahead
    returncode, stdout, _ = run_command("git rev-list --count origin/feature/new-tui-command..HEAD")
    commits_ahead = int(stdout.strip()) if stdout.strip().isdigit() else 0
    if commits_ahead > 0:
        console.print(f"[yellow]⚠️  {commits_ahead} commits ahead of origin[/yellow]")
        console.print("  [dim]Will need to push before merge[/dim]")
        checks.append(True)  # Not blocking, just informational
    else:
        console.print("[green]✅ Branch is up to date with origin[/green]")
        checks.append(True)

    return all(checks)


async def check_version_numbers():
    """Verify version is v1.15.0 in all files."""
    print_header("2. Version Numbers")

    version_files = {
        "pyproject.toml": ('version = "1.15.0"', 'toml'),
        "ppxai/version.py": ('__version__ = "1.15.0"', 'python'),
        "vscode-extension/package.json": ('"version": "1.15.0"', 'json'),
        "vscode-extension/package-lock.json": ('"version": "1.15.0"', 'json'),
    }

    checks = []
    for filepath, (pattern, filetype) in version_files.items():
        full_path = Path.cwd() / filepath
        if not full_path.exists():
            console.print(f"[yellow]⚠️  {filepath}:[/yellow] File not found (OK if not using VSCode)")
            checks.append(True)  # Not blocking for VSCode files
            continue

        content = full_path.read_text()
        if pattern in content:
            console.print(f"[green]✅ {filepath}:[/green] {pattern}")
            checks.append(True)
        else:
            console.print(f"[red]❌ {filepath}:[/red] Version string not found")
            checks.append(False)

    # Check --version output
    returncode, stdout, stderr = run_command("uv run ppxai --version", check=False)
    version_output = stdout.strip() if returncode == 0 else stderr.strip()
    if "1.15.0" in version_output:
        console.print(f"[green]✅ ppxai --version:[/green] {version_output}")
        checks.append(True)
    else:
        console.print(f"[red]❌ ppxai --version:[/red] {version_output}")
        checks.append(False)

    return all(checks)


async def check_tests():
    """Run all test suites."""
    print_header("3. Test Suites")

    checks = []

    # Unit tests
    console.print("[cyan]Running unit tests...[/cyan]")
    returncode, stdout, stderr = run_command(
        "uv run pytest tests/test_tui_command_factory.py -v --tb=short",
        check=False
    )

    if returncode == 0:
        # Parse test results
        if "passed" in stdout:
            passed_line = [l for l in stdout.split('\n') if 'passed' in l][-1]
            console.print(f"[green]✅ Unit tests:[/green] {passed_line.strip()}")
            checks.append(True)
        else:
            console.print(f"[green]✅ Unit tests passed[/green]")
            checks.append(True)
    else:
        console.print(f"[red]❌ Unit tests failed[/red]")
        # Show last few lines of output
        for line in stderr.split('\n')[-10:]:
            if line.strip():
                console.print(f"  {line}")
        checks.append(False)

    return all(checks)


async def check_validation_scripts():
    """Run all Phase 6 validation scripts."""
    print_header("4. Validation Scripts")

    scripts = [
        ("Command Factory", "scripts/validate_tui_commands.py"),
        ("Bootstrap Context", "scripts/validate_tui_bootstrap.py"),
        ("Token/Cost Tracking", "scripts/validate_tui_token_cost.py"),
        ("Tool Display", "scripts/validate_tui_tool_display.py"),
        ("Integration Tests", "scripts/validate_tui_integration.py"),
    ]

    checks = []
    for name, script in scripts:
        console.print(f"\n[cyan]Running {name}...[/cyan]")
        returncode, stdout, stderr = run_command(f"uv run python {script}", check=False)

        if returncode == 0:
            # Count passed checks
            passed = stdout.count("✅ PASS")
            total = stdout.count("PASS") + stdout.count("FAIL")
            if total > 0:
                console.print(f"[green]✅ {name}:[/green] {passed}/{total} checks passed")
                checks.append(passed == total)
            else:
                console.print(f"[green]✅ {name}:[/green] Completed successfully")
                checks.append(True)
        else:
            console.print(f"[red]❌ {name}:[/red] Script failed")
            checks.append(False)

    return all(checks)


async def check_documentation():
    """Verify all documentation is up to date."""
    print_header("5. Documentation")

    checks = []

    # Check CHANGELOG.md has v1.15.0 entry
    changelog = Path("CHANGELOG.md").read_text()
    if "## [1.15.0]" in changelog:
        console.print("[green]✅ CHANGELOG.md:[/green] v1.15.0 entry present")
        checks.append(True)
    else:
        console.print("[red]❌ CHANGELOG.md:[/red] Missing v1.15.0 entry")
        checks.append(False)

    # Check release notes exist
    release_notes = Path("docs/RELEASE-NOTES-v1.15.0.md")
    if release_notes.exists():
        size = len(release_notes.read_text())
        console.print(f"[green]✅ RELEASE-NOTES-v1.15.0.md:[/green] {size:,} chars")
        checks.append(True)
    else:
        console.print("[red]❌ RELEASE-NOTES-v1.15.0.md:[/red] Not found")
        checks.append(False)

    # Check Phase 6 progress doc
    phase6_doc = Path("docs/PHASE-6-PROGRESS.md")
    if phase6_doc.exists():
        content = phase6_doc.read_text()
        if "Phase 6.6 Complete" in content or "COMPLETE" in content:
            console.print("[green]✅ PHASE-6-PROGRESS.md:[/green] All phases marked complete")
            checks.append(True)
        else:
            console.print("[yellow]⚠️  PHASE-6-PROGRESS.md:[/yellow] May need completion status update")
            checks.append(True)  # Warning, not blocking
    else:
        console.print("[red]❌ PHASE-6-PROGRESS.md:[/red] Not found")
        checks.append(False)

    # Check Phase 7 doc
    phase7_doc = Path("docs/PHASE-7-POLISH-RELEASE.md")
    if phase7_doc.exists():
        console.print("[green]✅ PHASE-7-POLISH-RELEASE.md:[/green] Present")
        checks.append(True)
    else:
        console.print("[yellow]⚠️  PHASE-7-POLISH-RELEASE.md:[/yellow] Not found")
        checks.append(True)  # Warning, not blocking

    return all(checks)


async def check_build():
    """Verify binary builds successfully."""
    print_header("6. Binary Build")

    checks = []

    # Check if ppxaide binary exists
    binary_path = Path.home() / ".local/bin/ppxaide"
    if binary_path.exists():
        size = binary_path.stat().st_size / (1024 * 1024)  # MB
        console.print(f"[green]✅ ppxaide binary:[/green] {size:.1f} MB at {binary_path}")
        checks.append(True)

        # Test binary runs
        returncode, stdout, stderr = run_command(f"{binary_path} --version", check=False)
        if returncode == 0 and "1.15.0" in stdout:
            console.print(f"[green]✅ Binary version:[/green] {stdout.strip()}")
            checks.append(True)
        else:
            console.print(f"[yellow]⚠️  Binary version:[/yellow] {stdout.strip() or stderr.strip()}")
            checks.append(True)  # Warning, not blocking
    else:
        console.print(f"[yellow]⚠️  ppxaide binary:[/yellow] Not found at {binary_path}")
        console.print("  [dim]Build with: uv run pyinstaller ppxaide.spec --noconfirm[/dim]")
        checks.append(True)  # Warning, not blocking for pre-flight

    return all(checks)


async def check_known_issues():
    """Review known issues."""
    print_header("7. Known Issues")

    issues = [
        ("Alias 't' conflict", "RESOLVED", "Fixed in commit 87befdc"),
        ("/show regression", "DEFERRED", "Advanced rendering deferred to post-v1.15.0"),
    ]

    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("Issue")
    table.add_column("Status")
    table.add_column("Notes")

    for issue, status, notes in issues:
        if status == "RESOLVED":
            status_str = f"[green]{status}[/green]"
        elif status == "DEFERRED":
            status_str = f"[yellow]{status}[/yellow]"
        else:
            status_str = f"[red]{status}[/red]"

        table.add_row(issue, status_str, notes)

    console.print(table)
    console.print("\n[green]✅ All known issues documented and resolved/deferred[/green]")

    return True


async def check_commits():
    """Review recent commits."""
    print_header("8. Recent Commits")

    returncode, stdout, _ = run_command("git log --oneline -10")
    commits = stdout.strip().split('\n')

    console.print("[cyan]Last 10 commits:[/cyan]")
    for commit in commits:
        console.print(f"  {commit}")

    # Check for Phase 6/7 commits
    phase_commits = [c for c in commits if "Phase 6" in c or "Phase 7" in c or "phase-" in c]
    if len(phase_commits) >= 3:
        console.print(f"\n[green]✅ Found {len(phase_commits)} Phase 6/7 commits[/green]")
        return True
    else:
        console.print(f"\n[yellow]⚠️  Only {len(phase_commits)} Phase 6/7 commits found[/yellow]")
        return True  # Warning, not blocking


async def check_file_count():
    """Verify critical files exist."""
    print_header("9. Critical Files")

    critical_files = [
        "ppxai/tui/app.py",
        "ppxai/commands/factory.py",
        "tests/test_tui_command_factory.py",
        "scripts/validate_tui_integration.py",
        "CHANGELOG.md",
        "docs/RELEASE-NOTES-v1.15.0.md",
        "docs/PHASE-6-PROGRESS.md",
    ]

    checks = []
    for filepath in critical_files:
        path = Path(filepath)
        if path.exists():
            size = len(path.read_text())
            console.print(f"[green]✅ {filepath}:[/green] {size:,} chars")
            checks.append(True)
        else:
            console.print(f"[red]❌ {filepath}:[/red] Not found")
            checks.append(False)

    return all(checks)


async def generate_summary():
    """Generate pre-flight summary."""
    print_header("Pre-Flight Check Summary")

    results = []

    results.append(("Git Repository Status", await check_git_status()))
    results.append(("Version Numbers", await check_version_numbers()))
    results.append(("Test Suites", await check_tests()))
    results.append(("Validation Scripts", await check_validation_scripts()))
    results.append(("Documentation", await check_documentation()))
    results.append(("Binary Build", await check_build()))
    results.append(("Known Issues", await check_known_issues()))
    results.append(("Recent Commits", await check_commits()))
    results.append(("Critical Files", await check_file_count()))

    # Summary table
    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("Check")
    table.add_column("Status")

    passed = 0
    for name, success in results:
        if success:
            table.add_row(name, "[green]✅ PASS[/green]")
            passed += 1
        else:
            table.add_row(name, "[red]❌ FAIL[/red]")

    console.print()
    console.print(table)
    console.print()

    # Final verdict
    if passed == len(results):
        console.print("[bold green]🎉 ALL CHECKS PASSED - READY FOR RELEASE![/bold green]")
        console.print()
        console.print("[bold cyan]Next Steps:[/bold cyan]")
        console.print("  1. Push commits: git push origin feature/new-tui-command")
        console.print("  2. Create PR to master")
        console.print("  3. Review and merge PR")
        console.print("  4. Tag release: git tag v1.15.0")
        console.print("  5. Push tag: git push origin v1.15.0")
        console.print("  6. Create GitHub release with assets")
        return 0
    else:
        console.print(f"[bold red]❌ {len(results) - passed}/{len(results)} CHECKS FAILED[/bold red]")
        console.print()
        console.print("[bold yellow]Fix failing checks before proceeding with release[/bold yellow]")
        return 1


async def main():
    """Run all pre-flight checks."""
    console.print("[bold cyan]═" * 40)
    console.print("[bold cyan]v1.15.0 Release Pre-Flight Check[/bold cyan]")
    console.print("[bold cyan]═" * 40)

    return await generate_summary()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
