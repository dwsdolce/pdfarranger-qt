#!/bin/bash
#
# Build build/pdfarranger-qt.icns from the hicolor icon set.
#
#   packaging/make_icns.sh
#
# macOS only: uses sips and iconutil, which ship with the system. Called by
# packaging/build_mac; the result is generated rather than committed so there is
# no second copy of the artwork to keep in step.
#
# The scalable SVG would be the better source, but rendering it needs
# rsvg-convert or Inkscape, neither of which is on a stock macOS. The 256px PNG
# is upscaled for the 512 and 1024 slots instead, which the Finder only shows at
# large icon sizes.

set -e

cd "$(dirname "$0")/.."

SRC_DIR=data/icons/hicolor
OUT_DIR=build
ICONSET="$OUT_DIR/pdfarranger-qt.iconset"
LARGEST="$SRC_DIR/256x256/apps/com.github.jeromerobert.pdfarranger.png"

if [ ! -f "$LARGEST" ]; then
    echo "make_icns: $LARGEST is missing"
    exit 1
fi

rm -rf "$ICONSET"
mkdir -p "$ICONSET"

# Sizes macOS wants, and where each comes from. Anything at or below 256 uses
# the hand-drawn PNG of that size where one exists; the rest are scaled.
copy_or_scale() {
    local size="$1" name="$2"
    local exact="$SRC_DIR/${size}x${size}/apps/com.github.jeromerobert.pdfarranger.png"
    if [ -f "$exact" ]; then
        cp "$exact" "$ICONSET/$name"
    else
        sips -z "$size" "$size" "$LARGEST" --out "$ICONSET/$name" >/dev/null
    fi
}

copy_or_scale 16   icon_16x16.png
copy_or_scale 32   icon_16x16@2x.png
copy_or_scale 32   icon_32x32.png
copy_or_scale 64   icon_32x32@2x.png
copy_or_scale 128  icon_128x128.png
copy_or_scale 256  icon_128x128@2x.png
copy_or_scale 256  icon_256x256.png
copy_or_scale 512  icon_256x256@2x.png
copy_or_scale 512  icon_512x512.png
copy_or_scale 1024 icon_512x512@2x.png

iconutil -c icns "$ICONSET" -o "$OUT_DIR/pdfarranger-qt.icns"
rm -rf "$ICONSET"

echo "make_icns: wrote $OUT_DIR/pdfarranger-qt.icns"
