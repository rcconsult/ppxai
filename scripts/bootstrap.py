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
