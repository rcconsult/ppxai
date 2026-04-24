#!/usr/bin/env python3
"""
ppxai Desktop Launcher

Launches ppxai-server in background and opens web UI in default browser.
Provides a double-click desktop app experience.
"""

import argparse
import os
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

# Version — loaded directly from ppxai/version.py by file path to avoid
# triggering ppxai/__init__.py, which imports config + engine modules
# that pull in packages (pydantic, openai, rich, prompt_toolkit, fastapi,
# uvicorn) intentionally excluded from this PyInstaller build. The old
# `from ppxai.version import __version__` raised ImportError in the
# frozen binary and silently fell through to a hardcoded fallback string
# — the cause of v1.17.4 → v1.17.5 "ppxai-desktop --version" reporting
# the wrong version. Direct module loading bypasses the parent package
# and works in both dev and PyInstaller (sys._MEIPASS) modes.
def _load_frozen_version() -> str:
    import importlib.util
    from pathlib import Path as _Path

    if getattr(sys, "frozen", False):
        base = _Path(sys._MEIPASS)
    else:
        base = _Path(__file__).resolve().parent

    version_path = base / "ppxai" / "version.py"
    if not version_path.exists():
        return "unknown"

    spec = importlib.util.spec_from_file_location("_ppxai_version", version_path)
    if spec is None or spec.loader is None:
        return "unknown"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return getattr(module, "__version__", "unknown")


__version__ = _load_frozen_version()


def get_resource_path(relative_path: str) -> Path:
    """Get absolute path to resource, works for dev, PyInstaller, and .app bundle."""
    if getattr(sys, 'frozen', False):
        # Running as compiled executable
        exe_path = Path(sys.executable)

        # Check if we're inside a macOS .app bundle
        # Structure: ppxai.app/Contents/MacOS/ppxai-desktop
        if exe_path.parent.name == 'MacOS' and exe_path.parent.parent.name == 'Contents':
            resources_dir = exe_path.parent.parent / 'Resources'
            # Map 'ppxai/web' -> 'web' for app bundle
            if relative_path == 'ppxai/web':
                return resources_dir / 'web'
            elif relative_path == 'ppxai-server':
                # Server binary is in MacOS dir alongside us
                return exe_path.parent / 'ppxai-server'
            return resources_dir / relative_path

        # Standard PyInstaller path
        base_path = Path(sys._MEIPASS)
    else:
        # Running as script
        base_path = Path(__file__).parent
    return base_path / relative_path


def is_port_in_use(port: int) -> bool:
    """Check if a port is already in use."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('127.0.0.1', port)) == 0


def find_server_binary() -> Path | None:
    """Find ppxai-server binary in common locations (v1.13.2: config-based paths)."""
    binary_name = 'ppxai-server.exe' if sys.platform == 'win32' else 'ppxai-server'

    # Try to read paths from config file first
    config_paths = []
    for config_loc in [Path.home() / '.ppxai' / 'ppxai-config.json', Path('ppxai-config.json')]:
        if config_loc.exists():
            try:
                import json
                config = json.loads(config_loc.read_text(encoding="utf-8"))
                if 'paths' in config and 'bin_search_paths' in config['paths']:
                    for p in config['paths']['bin_search_paths']:
                        expanded = p.replace('{home}', str(Path.home()))
                        config_paths.append(Path(expanded) / binary_name)
                    break
            except Exception:
                pass

    # Default locations (fallback if no config) - platform-aware (v1.15.3)
    all_default_locations = [
        # Primary: ~/.ppxai/bin/ (v1.13.2)
        Path.home() / '.ppxai' / 'bin' / binary_name,
        # Same directory as this script/binary
        get_resource_path('ppxai-server' if sys.platform != 'win32' else 'ppxai-server.exe'),
        # User's local bin
        Path.home() / '.local' / 'bin' / binary_name,
        # User bin
        Path.home() / 'bin' / binary_name,
        # System paths (Unix only)
        Path('/usr/local/bin') / binary_name,
        Path('/usr/bin') / binary_name,
        # Windows AppData (Windows only)
        Path.home() / 'AppData' / 'Local' / 'ppxai' / binary_name,
    ]

    # Filter platform-specific paths for efficiency
    if sys.platform == 'win32':
        # Windows: Skip Unix system paths
        default_locations = [p for p in all_default_locations if not str(p).startswith('/usr')]
    else:
        # Unix/macOS/Linux: Skip Windows AppData
        default_locations = [p for p in all_default_locations if 'AppData' not in str(p)]

    # Check config paths first, then filtered defaults
    for loc in config_paths + default_locations:
        if loc.exists():
            return loc

    return None


def install_web_ui():
    """Install web UI files to ~/.ppxai/web/ if not present or outdated."""
    web_dir = Path.home() / '.ppxai' / 'web'
    source_dir = get_resource_path('ppxai/web')

    needs_update = False

    if not web_dir.exists():
        needs_update = True
    else:
        # Check if any source files are missing or different in destination
        # Compare both file names AND sizes to detect content changes
        for item in source_dir.iterdir():
            dest = web_dir / item.name
            if item.is_dir():
                if not dest.exists():
                    needs_update = True
                    break
                # Compare files by name AND size
                source_files = {f.name: f.stat().st_size for f in item.rglob('*') if f.is_file()}
                dest_files = {f.name: f.stat().st_size for f in dest.rglob('*') if f.is_file()}
                if source_files != dest_files:
                    needs_update = True
                    break
            else:
                if not dest.exists():
                    needs_update = True
                    break
                if item.stat().st_size != dest.stat().st_size:
                    needs_update = True
                    break

    if not needs_update:
        return web_dir

    # Copy web UI files
    web_dir.mkdir(parents=True, exist_ok=True)

    import shutil
    for item in source_dir.iterdir():
        dest = web_dir / item.name
        if item.is_dir():
            if dest.exists():
                shutil.rmtree(dest)
            shutil.copytree(item, dest)
        else:
            shutil.copy2(item, dest)

    print(f"Installed web UI to {web_dir}")
    return web_dir


def wait_for_server(port: int, timeout: float = 30.0) -> bool:
    """Wait for server to become available."""
    import urllib.request
    import urllib.error

    url = f'http://127.0.0.1:{port}/health'
    start = time.time()

    while time.time() - start < timeout:
        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                if response.status == 200:
                    return True
        except (urllib.error.URLError, ConnectionRefusedError, TimeoutError):
            pass
        time.sleep(0.2)

    return False


def start_server(server_path: Path) -> subprocess.Popen | None:
    """Start ppxai-server as a background process."""
    try:
        # Start server with output suppressed
        if sys.platform == 'win32':
            # Windows: use CREATE_NO_WINDOW
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            process = subprocess.Popen(
                [str(server_path)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                startupinfo=startupinfo
            )
        else:
            # Unix: detach from terminal
            process = subprocess.Popen(
                [str(server_path)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True
            )
        return process
    except Exception as e:
        print(f"Failed to start server: {e}")
        return None


def main():
    # Handle --version before anything else
    parser = argparse.ArgumentParser(
        description="ppxai Desktop - Web UI launcher",
        add_help=True
    )
    parser.add_argument(
        '--version', '-V',
        action='version',
        version=f'ppxai-desktop {__version__}'
    )
    parser.parse_args()

    port = 54320
    url = f'http://127.0.0.1:{port}'

    print("ppxai Desktop")
    print("=" * 40)

    # Check if server is already running
    if is_port_in_use(port):
        print(f"Server already running on port {port}")
    else:
        # Find server binary
        server_path = find_server_binary()
        if not server_path:
            print("ERROR: Could not find ppxai-server")
            print("\nPlease install ppxai-server:")
            print("  curl -sSL https://raw.githubusercontent.com/rcconsult/ppxai/master/install.sh | bash")
            sys.exit(1)

        print(f"Starting server: {server_path}")
        process = start_server(server_path)

        if process is None:
            print("ERROR: Failed to start server")
            sys.exit(1)

        # Wait for server to be ready
        print("Waiting for server...")
        if not wait_for_server(port):
            print("ERROR: Server failed to start (timeout)")
            process.terminate()
            sys.exit(1)

        print("Server started successfully")

    # Install/update web UI
    try:
        install_web_ui()
    except Exception as e:
        print(f"Warning: Could not install web UI: {e}")
        # Continue anyway - server might serve built-in UI

    # Open browser
    print(f"\nOpening {url}")
    webbrowser.open(url)

    print("\nppxai is running in your browser.")
    print("The server will continue running in the background.")
    print("To stop: pkill ppxai-server")


if __name__ == '__main__':
    main()
