#!/bin/bash
# Install desktop integration files for ppxai applications
# Usage: ./install-desktop-integration.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Directories
APPLICATIONS_DIR="$HOME/.local/share/applications"
ICONS_DIR="$HOME/.local/share/icons"

echo "Installing ppxai desktop integration..."
echo

# Create directories if they don't exist
mkdir -p "$APPLICATIONS_DIR"
mkdir -p "$ICONS_DIR"

# Copy icons
echo "Installing icons..."
cp "$PROJECT_ROOT/resources/ppxai-tui-preview.png" "$ICONS_DIR/ppxai.png"
cp "$PROJECT_ROOT/resources/ppxaide-nobg.png" "$ICONS_DIR/ppxaide.png"
cp "$PROJECT_ROOT/resources/ppxai.png" "$ICONS_DIR/ppxai-desktop.png"
echo "  ✓ Icons installed to $ICONS_DIR"

# Generate .desktop files with correct paths
echo
echo "Generating .desktop files..."

# ppxai.desktop
cat > "$APPLICATIONS_DIR/ppxai.desktop" << EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=ppxai
Comment=Terminal-based AI chat interface (Rich CLI)
Exec=$HOME/.local/bin/ppxai
Icon=$ICONS_DIR/ppxai.png
Terminal=true
Categories=Development;Utility;
Keywords=ai;chat;terminal;cli;
StartupNotify=false
EOF

# ppxaide.desktop — detect best available terminal emulator
PPXAIDE_BIN="$HOME/.local/bin/ppxaide"
if command -v ghostty &> /dev/null; then
    PPXAIDE_EXEC="ghostty -e $PPXAIDE_BIN"
    PPXAIDE_TERMINAL=false
elif command -v gnome-terminal &> /dev/null; then
    PPXAIDE_EXEC="gnome-terminal -- $PPXAIDE_BIN"
    PPXAIDE_TERMINAL=false
elif command -v konsole &> /dev/null; then
    PPXAIDE_EXEC="konsole -e $PPXAIDE_BIN"
    PPXAIDE_TERMINAL=false
elif command -v xfce4-terminal &> /dev/null; then
    PPXAIDE_EXEC="xfce4-terminal -e $PPXAIDE_BIN"
    PPXAIDE_TERMINAL=false
elif command -v alacritty &> /dev/null; then
    PPXAIDE_EXEC="alacritty -e $PPXAIDE_BIN"
    PPXAIDE_TERMINAL=false
elif command -v kitty &> /dev/null; then
    PPXAIDE_EXEC="kitty $PPXAIDE_BIN"
    PPXAIDE_TERMINAL=false
else
    PPXAIDE_EXEC="$PPXAIDE_BIN"
    PPXAIDE_TERMINAL=true
fi

cat > "$APPLICATIONS_DIR/ppxaide.desktop" << EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=ppxaide
Comment=Textual TUI for ppxai with syntax highlighting
Exec=$PPXAIDE_EXEC
Icon=$ICONS_DIR/ppxaide.png
Terminal=$PPXAIDE_TERMINAL
Categories=Development;Utility;
Keywords=ai;chat;terminal;tui;textual;
StartupNotify=false
EOF

# ppxai-desktop.desktop
cat > "$APPLICATIONS_DIR/ppxai-desktop.desktop" << EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=ppxai Desktop
Comment=Web-based desktop interface for ppxai
Exec=$HOME/.local/bin/ppxai-desktop
Icon=$ICONS_DIR/ppxai-desktop.png
Terminal=false
Categories=Development;Utility;
Keywords=ai;chat;web;desktop;
StartupNotify=true
EOF

echo "  ✓ Desktop files installed to $APPLICATIONS_DIR"

# Update desktop database (if update-desktop-database is available)
if command -v update-desktop-database &> /dev/null; then
    echo
    echo "Updating desktop database..."
    update-desktop-database "$APPLICATIONS_DIR"
    echo "  ✓ Desktop database updated"
fi

echo
echo "✅ Desktop integration installed successfully!"
echo
echo "You can now:"
echo "  • Find ppxai/ppxaide/ppxai-desktop in your application launcher"
echo "  • Pin them to your dock/taskbar"
echo "  • Launch them with one click"
echo
echo "To uninstall, run: ./uninstall-desktop-integration.sh"
