#!/bin/bash
#
# Build and upload macOS Intel executable to GitHub release
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

# Ensure dependencies are installed
echo ""
echo "Installing dependencies..."
uv sync --extra build

# Build executable
echo ""
echo "Building executable with PyInstaller..."
uv run pyinstaller ppxai.spec

# Verify build
if [ ! -f "dist/ppxai" ]; then
    echo "Error: Build failed - dist/ppxai not found"
    exit 1
fi

echo ""
echo "Build successful!"
ls -lh dist/ppxai
file dist/ppxai

# Rename for release
ASSET_NAME="ppxai-macos-intel"
cp dist/ppxai "dist/$ASSET_NAME"
echo ""
echo "Created: dist/$ASSET_NAME"

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

    # Upload asset
    gh release upload "$VERSION" "dist/$ASSET_NAME" --clobber

    echo ""
    echo "Upload complete!"
    echo "View release: gh release view $VERSION"
else
    echo ""
    echo "To upload to a release, run:"
    echo "  gh release upload <version> dist/$ASSET_NAME"
    echo ""
    echo "Example:"
    echo "  gh release upload v1.9.0 dist/$ASSET_NAME"
fi
