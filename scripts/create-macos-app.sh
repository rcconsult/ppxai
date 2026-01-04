#!/bin/bash
#
# Create macOS .app bundle and DMG installer for ppxai Desktop
#
# Usage:
#   ./scripts/create-macos-app.sh              # Build .app and DMG
#   ./scripts/create-macos-app.sh v1.13.1      # Build and upload to release
#
# Requirements:
#   - macOS (uses hdiutil for DMG creation)
#   - dist/ppxai-desktop binary must exist (run build-intel.sh first)
#   - dist/ppxai-server binary must exist
#
# Output:
#   - dist/ppxai.app/           - macOS application bundle
#   - dist/ppxai-VERSION-macos-ARCH.dmg  - DMG installer
#

set -e

VERSION="$1"
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

echo "========================================"
echo "Creating ppxai macOS App Bundle"
echo "========================================"
echo "Version: $VERSION"
echo "Architecture: $ARCH_NAME"
echo ""

# Check prerequisites
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

# Clean previous builds
rm -rf dist/ppxai.app
rm -f dist/ppxai-*.dmg

# Create .app bundle structure
APP_DIR="dist/ppxai.app"
CONTENTS_DIR="$APP_DIR/Contents"
MACOS_DIR="$CONTENTS_DIR/MacOS"
RESOURCES_DIR="$CONTENTS_DIR/Resources"

mkdir -p "$MACOS_DIR"
mkdir -p "$RESOURCES_DIR"

echo "Creating app bundle structure..."

# Copy binaries
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

# Create Info.plist
cat > "$CONTENTS_DIR/Info.plist" << 'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key>
    <string>ppxai</string>
    <key>CFBundleDisplayName</key>
    <string>ppxai Desktop</string>
    <key>CFBundleIdentifier</key>
    <string>com.ppxai.desktop</string>
    <key>CFBundleVersion</key>
    <string>VERSION_PLACEHOLDER</string>
    <key>CFBundleShortVersionString</key>
    <string>VERSION_PLACEHOLDER</string>
    <key>CFBundleExecutable</key>
    <string>ppxai-desktop</string>
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

# Replace version placeholder
sed -i '' "s/VERSION_PLACEHOLDER/$VERSION/g" "$CONTENTS_DIR/Info.plist"

# Create a simple icon (placeholder - can be replaced with real icon)
# For now, we'll skip the icon since we don't have one
echo "Note: No custom icon - using default macOS app icon"

echo "App bundle created: $APP_DIR"
ls -la "$MACOS_DIR/"

# Create DMG
DMG_NAME="ppxai-$VERSION-macos-$ARCH_NAME.dmg"
DMG_PATH="dist/$DMG_NAME"
TEMP_DMG="dist/ppxai-temp.dmg"

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
hdiutil create -volname "ppxai Desktop" \
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
