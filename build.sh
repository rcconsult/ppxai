#!/bin/bash

# Build script for macOS and Linux
# This script creates a standalone executable using PyInstaller

set -e

echo "================================================"
echo "Building ppxai executable..."
echo "================================================"

# Check if uv is available
if command -v uv &> /dev/null; then
    echo "Using uv package manager..."
    # Sync dependencies (creates .venv if needed)
    uv sync --dev
    # Run pyinstaller through uv
    UV_MODE=true
else
    echo "uv not found, using pip..."
    # Check if virtual environment exists
    if [ ! -d ".venv" ]; then
        echo "Creating virtual environment..."
        python3 -m venv .venv
    fi
    # Activate virtual environment
    source .venv/bin/activate
    # Install/upgrade dependencies
    pip install --upgrade pip
    pip install -r requirements.txt
fi

# Clean previous builds
echo "Cleaning previous builds..."
rm -rf build dist

# Build with PyInstaller
echo "Building executable..."
if [ "$UV_MODE" = true ]; then
    uv run pyinstaller ppxai.spec
else
    pyinstaller ppxai.spec
fi

# Check if build was successful
if [ -f "dist/ppxai" ]; then
    echo ""
    echo "================================================"
    echo "Build successful!"
    echo "================================================"
    echo "Executable location: dist/ppxai"
    echo ""
    echo "To run:"
    echo "  ./dist/ppxai"
    echo ""
    echo "To install system-wide (optional):"
    echo "  sudo cp dist/ppxai /usr/local/bin/"
    echo "================================================"
else
    echo "Build failed!"
    exit 1
fi
