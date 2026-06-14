#!/bin/bash
# ============================================================
#  Build a STANDALONE macOS app (.app + .dmg) for YouTube Niche Parser.
#
#  *** RUN THIS ON A MAC (not Windows). ***
#  The end user will NOT need Python - it is bundled inside the .app.
#
#  Usage in Terminal:
#     cd /path/to/YouTube-Niche-Parser
#     chmod +x build_mac.sh
#     ./build_mac.sh
#
#  Output:
#     dist/YouTube Niche Parser.app   (double-click to run)
#     YouTube Niche Parser.dmg        (share this file with others)
# ============================================================
set -e
cd "$(dirname "$0")"

APP_NAME="YouTube Niche Parser"
BUNDLE_ID="com.ytniche.parser"

# 1) Python 3 is required to BUILD (not to run the result)
if ! command -v python3 >/dev/null 2>&1; then
  echo "ERROR: Python 3 is needed to build."
  echo "Install it: https://www.python.org/downloads/  or:  brew install python"
  exit 1
fi

# 2) isolated build environment + PyInstaller
echo "==> Preparing build environment (PyInstaller)..."
python3 -m venv .buildenv
# shellcheck disable=SC1091
source .buildenv/bin/activate
python -m pip install --quiet --upgrade pip
python -m pip install --quiet pyinstaller certifi

# 3) build the .app (Python interpreter bundled inside)
echo "==> Building \"$APP_NAME.app\" ..."
rm -rf build dist "$APP_NAME.spec"
pyinstaller --noconfirm --clean --windowed \
  --name "$APP_NAME" \
  --osx-bundle-identifier "$BUNDLE_ID" \
  --add-data "ui.html:." \
  --add-data "scraper.py:." \
  --hidden-import scraper \
  --hidden-import certifi \
  --collect-data certifi \
  app.py

deactivate

if [ ! -d "dist/$APP_NAME.app" ]; then
  echo "ERROR: build failed (no .app produced)."
  exit 1
fi

# 4) wrap the .app into a shareable .dmg
echo "==> Creating \"$APP_NAME.dmg\" ..."
rm -f "$APP_NAME.dmg"
hdiutil create -volname "$APP_NAME" \
  -srcfolder "dist/$APP_NAME.app" \
  -ov -format UDZO "$APP_NAME.dmg"

echo ""
echo "============================================================"
echo "  DONE."
echo "    App:  dist/$APP_NAME.app   (double-click to run)"
echo "    DMG:  $APP_NAME.dmg        (send this to friends)"
echo ""
echo "  NOTE (first launch on any Mac): the app is unsigned, so"
echo "  macOS Gatekeeper will block the first open. Fix once:"
echo "    right-click the app -> Open -> Open."
echo "  The app opens its window via Chrome or Edge (install one"
echo "  for the native-window look; Safari opens it as a tab)."
echo "============================================================"
