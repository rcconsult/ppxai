#!/bin/bash

# Build script for macOS and Linux
# This script creates a standalone executable using PyInstaller

set -e

echo "================================================"
echo "Building ppxai executable..."
echo "================================================"

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

# Activate virtual environment
echo "Activating virtual environment..."
source venv/bin/activate

# Install/upgrade dependencies
echo "Installing dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

# Clean previous builds
echo "Cleaning previous builds..."
rm -rf build dist

# Build with PyInstaller
echo "Building executable..."
pyinstaller ppxai.spec

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
