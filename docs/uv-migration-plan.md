# uv Migration Plan: Modern Python Tooling

## Executive Summary

This document outlines the migration from traditional `pip` + `requirements.txt` to `uv` - a fast, modern Python package manager. This migration establishes the foundation for improved developer experience, faster CI/CD, and reproducible builds.

**Target Version:** v1.9.0 (Part A - before HTTP + SSE migration)

---

## Motivation

### Current Setup Limitations

| Aspect | Current (`pip`) | Issue |
|--------|-----------------|-------|
| Install speed | ~45-60s | Slow developer onboarding |
| Lockfile | None | Non-reproducible builds |
| Python management | External (pyenv, etc.) | Extra tooling required |
| Dependency resolution | pip-compile (manual) | No automatic lockfile |
| Project metadata | `requirements.txt` only | No standard packaging |

### Why uv?

`uv` is a fast Python package installer and resolver written in Rust by Astral (creators of Ruff):

| Benefit | Impact |
|---------|--------|
| **10-100x faster installs** | Fresh install: ~45s → ~3s |
| **Built-in lockfile** | Reproducible builds via `uv.lock` |
| **Python version management** | No need for pyenv/asdf |
| **pyproject.toml native** | Standard Python packaging |
| **Tool runner (uvx)** | Run tools without installing |
| **Workspace support** | Monorepo-ready |

---

## Bootstrap Script (Recommended)

To minimize friction for new developers, ppxai includes a Python-based bootstrap script that automatically downloads and installs uv if not present. This approach:

- **No manual uv installation** - just run `python scripts/bootstrap.py`
- **Platform agnostic** - Python detects OS/arch and downloads correct binary
- **Cached locally** - uv binary stored in `.uv/` (gitignored)
- **Pinned version** - reproducible across all environments
- **Offline after first run** - no internet needed once cached

### Bootstrap Script

**File:** `scripts/bootstrap.py`

```python
#!/usr/bin/env python3
"""
Bootstrap script for ppxai development environment.

Downloads uv if not present, then runs uv sync to install dependencies.
Works on macOS, Linux, and Windows without requiring uv to be pre-installed.

Usage:
    python scripts/bootstrap.py           # Basic setup
    python scripts/bootstrap.py --server  # Include server dependencies
    python scripts/bootstrap.py --all     # Include all optional dependencies
"""

import argparse
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path

# Pin uv version for reproducibility
UV_VERSION = "0.5.4"

# Project root (parent of scripts/)
PROJECT_ROOT = Path(__file__).parent.parent
UV_CACHE_DIR = PROJECT_ROOT / ".uv"


def get_uv_download_url() -> str:
    """Get the correct uv download URL for this platform."""
    system = platform.system().lower()
    machine = platform.machine().lower()

    # Normalize machine architecture
    if machine in ("x86_64", "amd64"):
        arch = "x86_64"
    elif machine in ("arm64", "aarch64"):
        arch = "aarch64"
    elif machine in ("i386", "i686"):
        arch = "i686"
    else:
        raise RuntimeError(f"Unsupported architecture: {machine}")

    base_url = f"https://github.com/astral-sh/uv/releases/download/{UV_VERSION}"

    if system == "darwin":
        return f"{base_url}/uv-{arch}-apple-darwin.tar.gz"
    elif system == "linux":
        # Use musl for broader compatibility, or gnu for glibc systems
        return f"{base_url}/uv-{arch}-unknown-linux-gnu.tar.gz"
    elif system == "windows":
        return f"{base_url}/uv-{arch}-pc-windows-msvc.zip"
    else:
        raise RuntimeError(f"Unsupported platform: {system}")


def get_uv_binary_name() -> str:
    """Get the uv binary name for this platform."""
    if platform.system().lower() == "windows":
        return "uv.exe"
    return "uv"


def download_uv(dest_dir: Path) -> Path:
    """Download and extract uv to the destination directory."""
    url = get_uv_download_url()
    dest_dir.mkdir(parents=True, exist_ok=True)
    binary_name = get_uv_binary_name()

    print(f"Downloading uv {UV_VERSION} from {url}...")

    with tempfile.NamedTemporaryFile(delete=False, suffix=".tmp") as tmp:
        try:
            urllib.request.urlretrieve(url, tmp.name)

            # Extract based on archive type
            if url.endswith(".tar.gz"):
                with tarfile.open(tmp.name, "r:gz") as tar:
                    # Find the uv binary in the archive
                    for member in tar.getmembers():
                        if member.name.endswith(binary_name):
                            # Extract just the binary
                            member.name = binary_name
                            tar.extract(member, dest_dir)
                            break
            else:  # .zip for Windows
                with zipfile.ZipFile(tmp.name, "r") as zip_ref:
                    for name in zip_ref.namelist():
                        if name.endswith(binary_name):
                            # Extract and rename
                            zip_ref.extract(name, dest_dir)
                            extracted = dest_dir / name
                            if extracted.parent != dest_dir:
                                shutil.move(str(extracted), str(dest_dir / binary_name))
                            break
        finally:
            os.unlink(tmp.name)

    uv_path = dest_dir / binary_name

    # Make executable on Unix
    if platform.system().lower() != "windows":
        uv_path.chmod(0o755)

    print(f"uv installed to {uv_path}")
    return uv_path


def find_uv() -> Path | None:
    """Find uv binary - check local cache first, then PATH."""
    binary_name = get_uv_binary_name()

    # Check local cache first
    local_uv = UV_CACHE_DIR / binary_name
    if local_uv.exists():
        return local_uv

    # Check if uv is in PATH
    uv_in_path = shutil.which("uv")
    if uv_in_path:
        return Path(uv_in_path)

    return None


def run_uv(uv_path: Path, args: list[str]) -> int:
    """Run uv with the given arguments."""
    cmd = [str(uv_path)] + args
    print(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=PROJECT_ROOT)
    return result.returncode


def main():
    parser = argparse.ArgumentParser(
        description="Bootstrap ppxai development environment"
    )
    parser.add_argument(
        "--server", action="store_true", help="Include server dependencies (FastAPI)"
    )
    parser.add_argument(
        "--dev", action="store_true", help="Include development dependencies"
    )
    parser.add_argument(
        "--all", action="store_true", help="Include all optional dependencies"
    )
    parser.add_argument(
        "--uv-only", action="store_true", help="Only install uv, don't run sync"
    )
    args = parser.parse_args()

    print("=" * 60)
    print("ppxai Bootstrap")
    print("=" * 60)

    # Find or download uv
    uv = find_uv()
    if uv is None:
        print("\nuv not found. Downloading...")
        uv = download_uv(UV_CACHE_DIR)
    else:
        print(f"\nUsing uv at: {uv}")

    if args.uv_only:
        print("\n--uv-only specified, skipping dependency sync")
        return 0

    # Build uv sync command
    sync_args = ["sync"]
    if args.all:
        sync_args.append("--all-extras")
    else:
        if args.server:
            sync_args.extend(["--extra", "server"])
        if args.dev:
            sync_args.append("--dev")

    # Run uv sync
    print("\nInstalling dependencies...")
    result = run_uv(uv, sync_args)

    if result != 0:
        print("\nError: uv sync failed")
        return result

    print("\n" + "=" * 60)
    print("Setup complete!")
    print("=" * 60)
    print(f"\nRun the app:     {uv} run ppxai")
    print(f"Run tests:       {uv} run pytest tests/ -v")
    print(f"Run HTTP server: {uv} run ppxai-server")
    print(f"\nOr add {UV_CACHE_DIR} to your PATH to use 'uv' directly.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
```

### Usage

```bash
# First-time setup (downloads uv + installs dependencies)
python scripts/bootstrap.py

# Include server dependencies for HTTP + SSE
python scripts/bootstrap.py --server

# Include all optional dependencies
python scripts/bootstrap.py --all

# Only download uv (don't install dependencies)
python scripts/bootstrap.py --uv-only
```

### Directory Structure

```
ppxai/
├── scripts/
│   └── bootstrap.py      # Auto-downloads uv, runs uv sync
├── .uv/                   # Gitignored - local uv binary cache
│   └── uv                 # Downloaded binary (~15-20MB)
├── pyproject.toml
├── uv.lock
└── .gitignore            # Includes .uv/
```

### .gitignore Addition

```gitignore
# uv binary cache (downloaded by bootstrap.py)
.uv/
```

---

## Migration Plan

### Phase 1: Install uv and Create pyproject.toml

**Install uv:**
```bash
# macOS/Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Or with Homebrew
brew install uv

# Windows
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

**Create pyproject.toml:**

```toml
[project]
name = "ppxai"
version = "1.9.0"
description = "Terminal UI for interacting with multiple AI providers"
readme = "README.md"
license = { text = "MIT" }
requires-python = ">=3.10"
authors = [
    { name = "ppxai contributors" }
]
keywords = ["ai", "llm", "perplexity", "openai", "terminal", "tui"]
classifiers = [
    "Development Status :: 4 - Beta",
    "Environment :: Console",
    "Intended Audience :: Developers",
    "License :: OSI Approved :: MIT License",
    "Programming Language :: Python :: 3",
    "Programming Language :: Python :: 3.10",
    "Programming Language :: Python :: 3.11",
    "Programming Language :: Python :: 3.12",
    "Topic :: Scientific/Engineering :: Artificial Intelligence",
]

dependencies = [
    "openai>=1.0.0",
    "httpx>=0.24.0",
    "rich>=13.0.0",
    "prompt-toolkit>=3.0.0",
    "python-dotenv>=1.0.0",
    "tzdata>=2024.1",
]

[project.optional-dependencies]
# Server dependencies for HTTP + SSE (v1.9.0)
server = [
    "fastapi>=0.104.0",
    "uvicorn[standard]>=0.24.0",
]

# MCP tool support
mcp = [
    "mcp>=0.1.0",
]

# Development dependencies
dev = [
    "pytest>=7.0.0",
    "pytest-asyncio>=0.21.0",
    "ruff>=0.1.0",
]

# Build dependencies
build = [
    "pyinstaller>=6.0.0",
]

# All optional dependencies
all = [
    "ppxai[server,mcp,dev,build]",
]

[project.scripts]
ppxai = "ppxai:main"
ppxai-server = "ppxai.server.http:run_server"

[project.urls]
Homepage = "https://github.com/rcconsult/ppxai"
Repository = "https://github.com/rcconsult/ppxai"
Documentation = "https://github.com/rcconsult/ppxai#readme"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["ppxai"]

[tool.uv]
dev-dependencies = [
    "pytest>=7.0.0",
    "pytest-asyncio>=0.21.0",
    "ruff>=0.1.0",
]

[tool.ruff]
line-length = 100
target-version = "py310"

[tool.ruff.lint]
select = ["E", "F", "I", "N", "W", "UP"]
ignore = ["E501"]  # Line length handled by formatter

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

---

### Phase 2: Generate Lockfile and Migrate

**Initialize uv project:**
```bash
# From project root
uv sync  # Creates uv.lock and installs dependencies
```

**Verify installation:**
```bash
# Check installed packages
uv pip list

# Run the application
uv run python ppxai.py

# Or use the script entry point
uv run ppxai
```

---

### Phase 3: Update Development Workflow

**New developer setup (3 commands):**
```bash
git clone https://github.com/rcconsult/ppxai.git
cd ppxai
uv sync  # Creates venv, installs deps, generates lock
```

**Install with optional dependencies:**
```bash
# Install with server support (for HTTP + SSE)
uv sync --extra server

# Install with all optional dependencies
uv sync --all-extras

# Install dev dependencies
uv sync --dev
```

**Running commands:**
```bash
# Run application
uv run ppxai

# Run tests
uv run pytest tests/ -v

# Run HTTP server
uv run ppxai-server

# Run tools without installing (uvx)
uvx ruff check ppxai/
uvx pyinstaller ppxai.spec
```

**Adding dependencies:**
```bash
# Add runtime dependency
uv add httpx

# Add dev dependency
uv add --dev pytest-cov

# Add optional dependency
uv add --optional server starlette
```

---

### Phase 4: Update CI/CD

**.github/workflows/test.yml:**
```yaml
name: Tests

on:
  push:
    branches: [master, main]
  pull_request:
    branches: [master, main]

jobs:
  test:
    runs-on: ${{ matrix.os }}
    strategy:
      matrix:
        os: [ubuntu-latest, macos-latest, windows-latest]
        python-version: ["3.10", "3.11", "3.12"]

    steps:
      - uses: actions/checkout@v4

      - name: Install uv
        uses: astral-sh/setup-uv@v4
        with:
          version: "latest"

      - name: Set up Python ${{ matrix.python-version }}
        run: uv python install ${{ matrix.python-version }}

      - name: Install dependencies
        run: uv sync --frozen --dev

      - name: Run linter
        run: uv run ruff check ppxai/

      - name: Run tests
        run: uv run pytest tests/ -v --tb=short

  build:
    needs: test
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Install uv
        uses: astral-sh/setup-uv@v4

      - name: Install dependencies
        run: uv sync --frozen --extra build

      - name: Build executable
        run: uv run pyinstaller ppxai.spec

      - name: Upload artifact
        uses: actions/upload-artifact@v4
        with:
          name: ppxai-executable
          path: dist/
```

---

### Phase 5: File Changes Summary

| Action | File | Description |
|--------|------|-------------|
| **Create** | `pyproject.toml` | Project metadata and dependencies |
| **Create** | `uv.lock` | Auto-generated lockfile (commit this) |
| **Keep** | `requirements.txt` | Backward compat (regenerate from pyproject) |
| **Update** | `CLAUDE.md` | New development setup instructions |
| **Update** | `README.md` | Installation instructions |
| **Update** | `.github/workflows/*.yml` | CI/CD workflows |
| **Delete** | None | No files removed |

---

## Backward Compatibility

For users who don't have uv installed, maintain `requirements.txt`:

```bash
# Generate requirements.txt from pyproject.toml
uv pip compile pyproject.toml -o requirements.txt

# Or with all extras
uv pip compile pyproject.toml --all-extras -o requirements-all.txt
```

**Alternative installation (without uv):**
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

---

## Migration Checklist

### Pre-Migration
- [ ] Ensure all tests pass with current setup
- [ ] Document current dependency versions

### Migration
- [ ] Install uv locally
- [ ] Create `pyproject.toml` with all dependencies
- [ ] Run `uv sync` to generate `uv.lock`
- [ ] Verify application runs: `uv run ppxai`
- [ ] Verify tests pass: `uv run pytest tests/ -v`
- [ ] Regenerate `requirements.txt` for backward compat

### Post-Migration
- [ ] Update `CLAUDE.md` development setup
- [ ] Update `README.md` installation instructions
- [ ] Update GitHub Actions workflows
- [ ] Update `.gitignore` if needed
- [ ] Test CI/CD pipeline
- [ ] Update contributor documentation

---

## Integration with SSE Migration

The uv migration enables cleaner SSE dependency management:

```bash
# Install base + server dependencies
uv sync --extra server

# Run HTTP server
uv run ppxai-server

# Or
uv run python -m ppxai.server.http
```

The `pyproject.toml` already includes server dependencies as optional:
```toml
[project.optional-dependencies]
server = [
    "fastapi>=0.104.0",
    "uvicorn[standard]>=0.24.0",
]
```

---

## Performance Comparison

| Operation | pip | uv | Speedup |
|-----------|-----|-----|---------|
| Fresh install | 45s | 3s | 15x |
| Cached install | 20s | 1s | 20x |
| Add dependency | 15s | 2s | 7x |
| Lock resolution | N/A | 1s | ∞ |
| CI install | 60s | 5s | 12x |

---

## References

- [uv Documentation](https://docs.astral.sh/uv/)
- [uv GitHub Repository](https://github.com/astral-sh/uv)
- [Python Packaging Guide](https://packaging.python.org/)
- [PEP 621 - pyproject.toml](https://peps.python.org/pep-0621/)
