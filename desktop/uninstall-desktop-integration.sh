#!/bin/bash
# Uninstall desktop integration files for ppxai applications
# Usage: ./uninstall-desktop-integration.sh

set -e

# Directories
APPLICATIONS_DIR="$HOME/.local/share/applications"
ICONS_DIR="$HOME/.local/share/icons"

echo "Uninstalling ppxai desktop integration..."
echo

# Remove .desktop files
echo "Removing desktop files..."
rm -f "$APPLICATIONS_DIR/ppxai.desktop"
rm -f "$APPLICATIONS_DIR/ppxaide.desktop"
rm -f "$APPLICATIONS_DIR/ppxai-desktop.desktop"
echo "  ✓ Desktop files removed"

# Remove icons
echo
echo "Removing icons..."
rm -f "$ICONS_DIR/ppxai.png"
rm -f "$ICONS_DIR/ppxaide.png"
rm -f "$ICONS_DIR/ppxai-desktop.png"
echo "  ✓ Icons removed"

# Update desktop database (if update-desktop-database is available)
if command -v update-desktop-database &> /dev/null; then
    echo
    echo "Updating desktop database..."
    update-desktop-database "$APPLICATIONS_DIR"
    echo "  ✓ Desktop database updated"
fi

echo
echo "✅ Desktop integration uninstalled successfully!"
