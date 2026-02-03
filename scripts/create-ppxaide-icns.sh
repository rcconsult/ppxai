#!/bin/bash
#
# Create ppxaide.icns from ppxaide-nobg.png for macOS app bundles
#
# Usage:
#   ./scripts/create-ppxaide-icns.sh
#
# Requirements:
#   - macOS (uses sips and iconutil)
#   - resources/ppxaide-nobg.png (source image)
#
# Output:
#   - resources/ppxaide.icns
#

set -e

SOURCE="resources/ppxaide-nobg.png"
ICONSET="resources/ppxaide.iconset"
OUTPUT="resources/ppxaide.icns"

echo "========================================"
echo "Creating ppxaide.icns for macOS"
echo "========================================"

# Check if source exists
if [ ! -f "$SOURCE" ]; then
    echo "Error: Source image not found: $SOURCE"
    exit 1
fi

# Clean up previous iconset
rm -rf "$ICONSET"
mkdir -p "$ICONSET"

echo "Converting PNG to iconset..."

# Generate all required sizes for macOS icons
# Standard sizes: 16, 32, 64, 128, 256, 512, 1024
# Retina sizes: @2x versions

sips -z 16 16     "$SOURCE" --out "${ICONSET}/icon_16x16.png"
sips -z 32 32     "$SOURCE" --out "${ICONSET}/icon_16x16@2x.png"
sips -z 32 32     "$SOURCE" --out "${ICONSET}/icon_32x32.png"
sips -z 64 64     "$SOURCE" --out "${ICONSET}/icon_32x32@2x.png"
sips -z 128 128   "$SOURCE" --out "${ICONSET}/icon_128x128.png"
sips -z 256 256   "$SOURCE" --out "${ICONSET}/icon_128x128@2x.png"
sips -z 256 256   "$SOURCE" --out "${ICONSET}/icon_256x256.png"
sips -z 512 512   "$SOURCE" --out "${ICONSET}/icon_256x256@2x.png"
sips -z 512 512   "$SOURCE" --out "${ICONSET}/icon_512x512.png"
sips -z 1024 1024 "$SOURCE" --out "${ICONSET}/icon_512x512@2x.png"

echo "Generated $(ls -1 ${ICONSET} | wc -l) icon sizes"

echo "Creating .icns file..."
iconutil -c icns "$ICONSET" -o "$OUTPUT"

# Clean up iconset
rm -rf "$ICONSET"

echo ""
echo "✅ Success!"
echo "Created: $OUTPUT"
ls -lh "$OUTPUT"
