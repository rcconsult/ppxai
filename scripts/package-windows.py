"""Package ppxai desktop + server into a self-contained Windows deployment ZIP.

Usage:
    .uv/uv run python scripts/package-windows.py

Creates:
    dist/ppxai-{version}-windows.zip

The ZIP contains binaries, web UI, config templates, and an install script
that deploys everything to ~/.ppxai/ on the target machine.
"""

import os
import sys
import zipfile
from pathlib import Path

# Project root
ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
WEB_DIR = ROOT / "ppxai" / "web"


def get_version() -> str:
    """Read version from ppxai/version.py."""
    version_file = ROOT / "ppxai" / "version.py"
    for line in version_file.read_text(encoding="utf-8").splitlines():
        if line.startswith("__version__"):
            return line.split('"')[1]
    raise RuntimeError("Could not read version from ppxai/version.py")


INSTALL_PS1 = r'''# ppxai Offline Installation Script
# Deploys ppxai from a local ZIP package (no internet required)
#
# Usage:
#   .\install.ps1              # Install (preserves existing config)
#   .\install.ps1 -Force       # Overwrite existing config files
#
# Installation locations:
#   Binaries: %USERPROFILE%\.ppxai\bin\
#   Web UI:   %USERPROFILE%\.ppxai\web\
#   Config:   %USERPROFILE%\.ppxai\ppxai-config.json
#   Env:      %USERPROFILE%\.ppxai\.env

param(
    [switch]$Force
)

$ErrorActionPreference = "Stop"

$INSTALL_DIR = Join-Path $env:USERPROFILE ".ppxai"
$BIN_DIR = Join-Path $INSTALL_DIR "bin"
$WEB_DIR = Join-Path $INSTALL_DIR "web"
$SCRIPT_DIR = Split-Path -Parent $MyInvocation.MyCommand.Path

function Write-Header {
    param([string]$Text)
    Write-Host ""
    Write-Host "=== $Text ===" -ForegroundColor Cyan
    Write-Host ""
}

function Write-Success {
    param([string]$Text)
    Write-Host "[OK] $Text" -ForegroundColor Green
}

function Write-Warn {
    param([string]$Text)
    Write-Host "[WARN] $Text" -ForegroundColor Yellow
}

# =============================================================================
# Create directory structure
# =============================================================================

Write-Host ""
Write-Host "ppxai Windows Installer (offline)" -ForegroundColor Cyan
Write-Host "==================================" -ForegroundColor Cyan

Write-Header "Creating directories"

$dirs = @(
    $INSTALL_DIR,
    $BIN_DIR,
    $WEB_DIR,
    (Join-Path $INSTALL_DIR "sessions"),
    (Join-Path $INSTALL_DIR "exports"),
    (Join-Path $INSTALL_DIR "checkpoints"),
    (Join-Path $INSTALL_DIR "logs"),
    (Join-Path $INSTALL_DIR "usage")
)

foreach ($dir in $dirs) {
    if (-not (Test-Path $dir)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
        Write-Success "Created $dir"
    }
}

# =============================================================================
# Copy binaries
# =============================================================================

Write-Header "Installing binaries"

$binSrc = Join-Path $SCRIPT_DIR "bin"
if (-not (Test-Path $binSrc)) {
    Write-Host "[ERROR] bin/ directory not found in package" -ForegroundColor Red
    exit 1
}

Get-ChildItem -Path $binSrc -Filter "*.exe" | ForEach-Object {
    $dest = Join-Path $BIN_DIR $_.Name
    Copy-Item $_.FullName $dest -Force
    Write-Success "Installed $($_.Name)"
}

# =============================================================================
# Copy web UI
# =============================================================================

Write-Header "Installing web UI"

$webSrc = Join-Path $SCRIPT_DIR "web"
if (Test-Path $webSrc) {
    # Remove old web files and copy fresh
    if (Test-Path $WEB_DIR) {
        Remove-Item -Path $WEB_DIR -Recurse -Force
    }
    Copy-Item -Path $webSrc -Destination $WEB_DIR -Recurse -Force
    $fileCount = (Get-ChildItem -Path $WEB_DIR -Recurse -File).Count
    Write-Success "Installed $fileCount web UI files"
} else {
    Write-Warn "web/ directory not found in package, skipping"
}

# =============================================================================
# Config files (preserve existing)
# =============================================================================

Write-Header "Configuration"

# ppxai-config.json
$configDest = Join-Path $INSTALL_DIR "ppxai-config.json"
$configSrc = Join-Path $SCRIPT_DIR "ppxai-config.json"
if ((Test-Path $configDest) -and -not $Force) {
    Write-Warn "ppxai-config.json already exists (use -Force to overwrite)"
} elseif (Test-Path $configSrc) {
    $content = [System.IO.File]::ReadAllText($configSrc)
    [System.IO.File]::WriteAllText($configDest, $content, [System.Text.UTF8Encoding]::new($false))
    Write-Success "Created ppxai-config.json"
}

# .env
$envDest = Join-Path $INSTALL_DIR ".env"
$envSrc = Join-Path $SCRIPT_DIR ".env"
if ((Test-Path $envDest) -and -not $Force) {
    Write-Warn ".env already exists (use -Force to overwrite)"
} elseif (Test-Path $envSrc) {
    $content = [System.IO.File]::ReadAllText($envSrc)
    [System.IO.File]::WriteAllText($envDest, $content, [System.Text.UTF8Encoding]::new($false))
    Write-Success "Created .env"
}

# =============================================================================
# Update PATH
# =============================================================================

Write-Header "Updating PATH"

$currentPath = [Environment]::GetEnvironmentVariable("PATH", "User")
if ($currentPath -notlike "*$BIN_DIR*") {
    $newPath = "$BIN_DIR;$currentPath"
    [Environment]::SetEnvironmentVariable("PATH", $newPath, "User")
    Write-Success "Added $BIN_DIR to user PATH"
    Write-Host ""
    Write-Host "NOTE: Restart your terminal or run:" -ForegroundColor Yellow
    Write-Host '  $env:PATH = [Environment]::GetEnvironmentVariable("PATH", "User")' -ForegroundColor Yellow
} else {
    Write-Success "$BIN_DIR is already in PATH"
}

# =============================================================================
# Done
# =============================================================================

Write-Header "Installation Complete"

Write-Host "ppxai has been installed to: $INSTALL_DIR" -ForegroundColor Green
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Cyan
Write-Host "  1. Edit your API keys:"
Write-Host "     notepad $INSTALL_DIR\.env" -ForegroundColor Yellow
Write-Host ""
Write-Host "  2. Run ppxai:"
Write-Host "     ppxai-desktop          # Desktop web app" -ForegroundColor Yellow
Write-Host "     ppxai-server           # HTTP server for VSCode" -ForegroundColor Yellow
Write-Host ""
Write-Host "  3. For VSCode extension:"
Write-Host "     - Start ppxai-server"
Write-Host "     - Install ppxai extension from VSIX"
Write-Host ""
'''


def build_zip() -> Path:
    version = get_version()
    zip_name = f"ppxai-{version}-windows.zip"
    zip_path = DIST / zip_name

    # Verify required binaries
    required = ["ppxai-desktop.exe", "ppxai-server.exe"]
    missing = [b for b in required if not (DIST / b).exists()]
    if missing:
        print(f"ERROR: Missing binaries in dist/: {', '.join(missing)}")
        print("Build them first with PyInstaller.")
        sys.exit(1)

    # Verify web directory
    if not WEB_DIR.exists():
        print(f"ERROR: Web UI directory not found: {WEB_DIR}")
        sys.exit(1)

    # Config files: prefer user's live config from ~/.ppxai/, fall back to examples
    user_config_dir = Path.home() / ".ppxai"
    user_config = user_config_dir / "ppxai-config.json"
    user_env = user_config_dir / ".env"
    config_example = ROOT / "ppxai-config.example.json"
    env_example = ROOT / ".env.example"

    config_src = user_config if user_config.exists() else config_example
    env_src = user_env if user_env.exists() else env_example

    if not config_src.exists():
        print(f"ERROR: No config found (checked {user_config} and {config_example})")
        sys.exit(1)
    if not env_src.exists():
        print(f"ERROR: No .env found (checked {user_env} and {env_example})")
        sys.exit(1)

    print(f"Packaging ppxai v{version} for Windows...")
    print()

    DIST.mkdir(exist_ok=True)
    file_count = 0

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        # Install script
        zf.writestr("install.ps1", INSTALL_PS1)
        file_count += 1
        print("  + install.ps1")

        # Binaries
        for binary in required:
            src = DIST / binary
            zf.write(src, f"bin/{binary}")
            size_mb = src.stat().st_size / (1024 * 1024)
            file_count += 1
            print(f"  + bin/{binary} ({size_mb:.1f} MB)")

        # Web UI
        for path in sorted(WEB_DIR.rglob("*")):
            if path.is_file():
                arcname = f"web/{path.relative_to(WEB_DIR).as_posix()}"
                zf.write(path, arcname)
                file_count += 1
        web_count = sum(1 for _ in WEB_DIR.rglob("*") if _.is_file())
        print(f"  + web/ ({web_count} files)")

        # Config files (user's live config or example templates)
        zf.write(config_src, "ppxai-config.json")
        file_count += 1
        label = "user" if config_src == user_config else "example"
        print(f"  + ppxai-config.json ({label})")

        zf.write(env_src, ".env")
        file_count += 1
        label = "user" if env_src == user_env else "example"
        print(f"  + .env ({label})")

    zip_size = zip_path.stat().st_size / (1024 * 1024)
    print()
    print(f"Created: {zip_path}")
    print(f"Size:    {zip_size:.1f} MB ({file_count} files)")
    return zip_path


if __name__ == "__main__":
    build_zip()
