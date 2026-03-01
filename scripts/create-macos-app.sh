#!/bin/bash
#
# Create macOS .app bundle and DMG installer for ppxai Desktop or ppxaide TUI
#
# Usage:
#   ./scripts/create-macos-app.sh                          # Build ppxai-desktop (default)
#   ./scripts/create-macos-app.sh --app ppxaide            # Build ppxaide TUI
#   ./scripts/create-macos-app.sh --app ppxaide v1.15.2   # Build and upload to release
#
# Requirements:
#   - macOS (uses hdiutil for DMG creation)
#   - dist/ppxai-desktop or dist/ppxaide binary must exist
#   - dist/ppxai-server binary must exist (for desktop app)
#
# Output:
#   - dist/ppxai.app/ or dist/ppxaide.app/    - macOS application bundle
#   - dist/ppxai-VERSION-macos-ARCH.dmg       - DMG installer
#

set -e

# Parse arguments
APP_TYPE="ppxai-desktop"
VERSION=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --app)
            APP_TYPE="$2"
            shift 2
            ;;
        v*.*.*)
            VERSION="$1"
            shift
            ;;
        *)
            VERSION="$1"
            shift
            ;;
    esac
done

# Validate app type
if [[ "$APP_TYPE" != "ppxai-desktop" && "$APP_TYPE" != "ppxaide" ]]; then
    echo "Error: Invalid app type: $APP_TYPE"
    echo "Valid options: ppxai-desktop, ppxaide"
    exit 1
fi

ARCH=$(uname -m)
if [ "$ARCH" = "x86_64" ]; then
    ARCH_NAME="intel"
else
    ARCH_NAME="arm64"
fi

# Get version from pyproject.toml if not specified
if [ -z "$VERSION" ]; then
    VERSION=$(grep 'version = ' pyproject.toml | head -1 | sed 's/.*"\(.*\)".*/\1/')
fi

# Strip leading 'v' so DMG filename is ppxai-1.16.1-macos-intel.dmg (not ppxai-v1.16.1-...)
VERSION="${VERSION#v}"

echo "========================================"
echo "Creating macOS App Bundle"
echo "========================================"
echo "App Type: $APP_TYPE"
echo "Version: $VERSION"
echo "Architecture: $ARCH_NAME"
echo ""

# Check prerequisites based on app type
if [ "$APP_TYPE" = "ppxai-desktop" ]; then
    if [ ! -f "dist/ppxai-desktop" ]; then
        echo "Error: dist/ppxai-desktop not found"
        echo "Run ./scripts/build-intel.sh first"
        exit 1
    fi

    if [ ! -f "dist/ppxai-server" ]; then
        echo "Error: dist/ppxai-server not found"
        echo "Run ./scripts/build-intel.sh first"
        exit 1
    fi
elif [ "$APP_TYPE" = "ppxaide" ]; then
    if [ ! -f "dist/ppxaide" ]; then
        echo "Error: dist/ppxaide not found"
        echo "Run pyinstaller ppxaide.spec first"
        exit 1
    fi
fi

# Set app-specific variables
if [ "$APP_TYPE" = "ppxai-desktop" ]; then
    APP_NAME="ppxai"
    APP_DIR="dist/ppxai.app"
    DISPLAY_NAME="ppxai Desktop"
    BUNDLE_ID="com.ppxai.desktop"
    EXECUTABLE="ppxai-desktop"
    ICON_FILE="ppxai.icns"
    INCLUDE_WEB=true
    INCLUDE_SERVER=true
elif [ "$APP_TYPE" = "ppxaide" ]; then
    APP_NAME="ppxaide"
    APP_DIR="dist/ppxaide.app"
    DISPLAY_NAME="ppxaide TUI"
    BUNDLE_ID="com.ppxai.aide"
    EXECUTABLE="ppxaide"
    ICON_FILE="ppxaide.icns"
    INCLUDE_WEB=false
    INCLUDE_SERVER=false
fi

# Clean previous builds
rm -rf "$APP_DIR"
rm -f "dist/${APP_NAME}-*.dmg"

# Create .app bundle structure
CONTENTS_DIR="$APP_DIR/Contents"
MACOS_DIR="$CONTENTS_DIR/MacOS"
RESOURCES_DIR="$CONTENTS_DIR/Resources"

mkdir -p "$MACOS_DIR"
mkdir -p "$RESOURCES_DIR"

echo "Creating app bundle structure..."

# Copy main binary
if [ "$APP_TYPE" = "ppxai-desktop" ]; then
    cp dist/ppxai-desktop "$MACOS_DIR/ppxai-desktop"
    cp dist/ppxai-server "$MACOS_DIR/ppxai-server"
    chmod +x "$MACOS_DIR/ppxai-desktop"
    chmod +x "$MACOS_DIR/ppxai-server"

    # Copy web UI files
    if [ -d "ppxai/web" ]; then
        mkdir -p "$RESOURCES_DIR/web"
        cp -r ppxai/web/* "$RESOURCES_DIR/web/"
        echo "Copied web UI files"
    fi
elif [ "$APP_TYPE" = "ppxaide" ]; then
    # Copy ppxaide binary
    cp dist/ppxaide "$MACOS_DIR/ppxaide-bin"
    chmod +x "$MACOS_DIR/ppxaide-bin"

    # Create launcher script that opens in terminal
    cat > "$MACOS_DIR/$EXECUTABLE" << 'LAUNCHER'
#!/bin/bash
# ppxaide launcher - opens in iTerm2 or Terminal.app when double-clicked

# Get the directory where the binary is located
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PPXAIDE="$DIR/ppxaide-bin"

# Check if running in a terminal (has stdin)
if [ -t 0 ]; then
    # Running in terminal - execute directly
    exec "$PPXAIDE" "$@"
else
    # Not in terminal (double-clicked from Finder) - open Terminal
    if [ -d "/Applications/iTerm.app" ]; then
        # Use iTerm2 if available
        osascript <<EOF
tell application "iTerm"
    activate
    create window with default profile
    tell current session of current window
        write text "$PPXAIDE"
    end tell
end tell
EOF
    else
        # Fall back to Terminal.app
        osascript <<EOF
tell application "Terminal"
    activate
    do script "$PPXAIDE"
end tell
EOF
    fi
fi
LAUNCHER

    chmod +x "$MACOS_DIR/$EXECUTABLE"
fi

# Create Info.plist with app-specific values
cat > "$CONTENTS_DIR/Info.plist" << PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key>
    <string>${APP_NAME}</string>
    <key>CFBundleDisplayName</key>
    <string>${DISPLAY_NAME}</string>
    <key>CFBundleIdentifier</key>
    <string>${BUNDLE_ID}</string>
    <key>CFBundleVersion</key>
    <string>${VERSION}</string>
    <key>CFBundleShortVersionString</key>
    <string>${VERSION}</string>
    <key>CFBundleExecutable</key>
    <string>${EXECUTABLE}</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleSignature</key>
    <string>????</string>
    <key>CFBundleIconFile</key>
    <string>AppIcon</string>
    <key>LSMinimumSystemVersion</key>
    <string>10.13</string>
    <key>NSHighResolutionCapable</key>
    <true/>
    <key>LSUIElement</key>
    <false/>
    <key>NSHumanReadableCopyright</key>
    <string>Copyright 2024-2026 ppxai contributors</string>
</dict>
</plist>
PLIST

# Copy app icon
if [ -f "resources/$ICON_FILE" ]; then
    cp "resources/$ICON_FILE" "$RESOURCES_DIR/AppIcon.icns"
    echo "Copied app icon: $ICON_FILE"
else
    echo "Warning: No icon found at resources/$ICON_FILE"
fi

echo "App bundle created: $APP_DIR"
ls -la "$MACOS_DIR/"

# Create DMG
DMG_NAME="${APP_NAME}-$VERSION-macos-$ARCH_NAME.dmg"
DMG_PATH="dist/$DMG_NAME"

echo ""
echo "Creating DMG installer..."

# Create a temporary directory for DMG contents
DMG_CONTENTS="dist/dmg-contents"
rm -rf "$DMG_CONTENTS"
mkdir -p "$DMG_CONTENTS"

# Copy app to DMG contents
cp -r "$APP_DIR" "$DMG_CONTENTS/"

# Create symlink to Applications folder
ln -s /Applications "$DMG_CONTENTS/Applications"

# Create DMG
hdiutil create -volname "$DISPLAY_NAME" \
    -srcfolder "$DMG_CONTENTS" \
    -ov -format UDZO \
    "$DMG_PATH"

# Clean up
rm -rf "$DMG_CONTENTS"

echo ""
echo "DMG created: $DMG_PATH"
ls -lh "$DMG_PATH"

# Upload if version argument was passed as a release tag (starts with v)
if [[ "$1" == v* ]]; then
    echo ""
    echo "========================================"
    echo "Uploading DMG to release $1"
    echo "========================================"

    # Source GitHub token
    if [ -f ".github/gh-tokenv.env" ]; then
        unset GITHUB_TOKEN
        source .github/gh-tokenv.env
        export GH_TOKEN
    fi

    # Check authentication
    if ! gh auth status &> /dev/null; then
        echo "Error: Not authenticated. Run: gh auth login"
        exit 1
    fi

    gh release upload "$1" "$DMG_PATH" --clobber

    echo ""
    echo "Upload complete!"
    echo "View release: gh release view $1"
else
    echo ""
    echo "To upload to a release, run:"
    echo "  gh release upload <version> $DMG_PATH"
    echo ""
    echo "Example:"
    echo "  gh release upload v1.13.1 $DMG_PATH"
fi
