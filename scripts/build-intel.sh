#!/bin/bash
#
# Build and upload macOS Intel executables to GitHub release
#
# Builds:
#   - ppxai (TUI application)
#   - ppxai-server (HTTP server for VSCode extension)
#   - ppxai-desktop (Desktop launcher for web UI)
#   - ppxai-VERSION-macos-intel.dmg (DMG installer with app bundle)
#
# Usage:
#   ./scripts/build-intel.sh v1.9.0    # Build and upload to specific release
#   ./scripts/build-intel.sh           # Build only (no upload)
#

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT"

# Load GitHub token if available
if [ -f ".github/gh-tokenv.env" ]; then
    source .github/gh-tokenv.env
    export GH_TOKEN
fi

VERSION="$1"

# Check if running on macOS Intel
OS=$(uname -s)
ARCH=$(uname -m)

if [ "$OS" != "Darwin" ]; then
    echo "========================================"
    echo "NOTICE: Skipping macOS Intel build"
    echo "========================================"
    echo "Current OS: $OS"
    echo "macOS Intel build requires macOS (Darwin)"
    echo ""
    echo "The release will proceed without macOS Intel asset."
    exit 0
fi

if [ "$ARCH" != "x86_64" ]; then
    echo "========================================"
    echo "NOTICE: Skipping macOS Intel build"
    echo "========================================"
    echo "Current architecture: $ARCH"
    echo "macOS Intel build requires x86_64 architecture"
    echo ""
    echo "The release will proceed without macOS Intel asset."
    exit 0
fi

echo "========================================"
echo "Building ppxai for macOS Intel (x86_64)"
echo "========================================"

# Ensure dependencies are installed (including server deps for ppxai-server)
echo ""
echo "Installing dependencies..."
uv sync --extra build --extra server

# Build TUI executable
echo ""
echo "Building TUI executable with PyInstaller..."
uv run pyinstaller ppxai.spec

# Verify TUI build
if [ ! -f "dist/ppxai" ]; then
    echo "Error: TUI build failed - dist/ppxai not found"
    exit 1
fi

echo ""
echo "TUI build successful!"
ls -lh dist/ppxai
file dist/ppxai

# Build server executable
echo ""
echo "Building server executable with PyInstaller..."
uv run pyinstaller ppxai-server.spec

# Verify server build
if [ ! -f "dist/ppxai-server" ]; then
    echo "Error: Server build failed - dist/ppxai-server not found"
    exit 1
fi

echo ""
echo "Server build successful!"
ls -lh dist/ppxai-server
file dist/ppxai-server

# Build desktop executable
echo ""
echo "Building desktop executable with PyInstaller..."
uv run pyinstaller ppxai-desktop.spec

# Verify desktop build
if [ ! -f "dist/ppxai-desktop" ]; then
    echo "Error: Desktop build failed - dist/ppxai-desktop not found"
    exit 1
fi

echo ""
echo "Desktop build successful!"
ls -lh dist/ppxai-desktop
file dist/ppxai-desktop

# Rename for release
TUI_ASSET="ppxai-macos-intel"
SERVER_ASSET="ppxai-server-macos-intel"
DESKTOP_ASSET="ppxai-desktop-macos-intel"
cp dist/ppxai "dist/$TUI_ASSET"
cp dist/ppxai-server "dist/$SERVER_ASSET"
cp dist/ppxai-desktop "dist/$DESKTOP_ASSET"
echo ""
echo "Created: dist/$TUI_ASSET"
echo "Created: dist/$SERVER_ASSET"
echo "Created: dist/$DESKTOP_ASSET"

# Upload to release if version specified
if [ -n "$VERSION" ]; then
    echo ""
    echo "========================================"
    echo "Uploading to release $VERSION"
    echo "========================================"

    # Check if gh is available
    if ! command -v gh &> /dev/null; then
        echo "Error: gh CLI not found. Install with: brew install gh"
        exit 1
    fi

    # Check authentication
    if ! gh auth status &> /dev/null; then
        echo "Error: Not authenticated. Run: gh auth login"
        exit 1
    fi

    # Upload all three assets
    gh release upload "$VERSION" "dist/$TUI_ASSET" "dist/$SERVER_ASSET" "dist/$DESKTOP_ASSET" --clobber

    echo ""
    echo "Binaries uploaded!"

    # Create and upload DMG installer
    echo ""
    echo "========================================"
    echo "Creating macOS Intel DMG installer"
    echo "========================================"
    bash "$SCRIPT_DIR/create-macos-app.sh" "$VERSION"

    echo ""
    echo "Upload complete!"
    echo "View release: gh release view $VERSION"
else
    echo ""
    echo "To upload to a release, run:"
    echo "  gh release upload <version> dist/$TUI_ASSET dist/$SERVER_ASSET dist/$DESKTOP_ASSET"
    echo ""
    echo "Example:"
    echo "  gh release upload v1.9.0 dist/$TUI_ASSET dist/$SERVER_ASSET dist/$DESKTOP_ASSET"
fi
