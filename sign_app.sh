#!/bin/bash
# Inside-out code-sign the PyInstaller .app with a stable self-signed cert so
# macOS TCC anchors the Accessibility grant to the certificate (survives
# rebuilds) instead of the per-build cdhash. Same recipe as ScreenCapture.
#
# Prereq (one-time, GUI): a self-signed Code Signing certificate named
# $CERT (default "LocalAppDev") in the keychain, trusted for code signing.
#
# Usage:  ./sign_app.sh [path/to/ClipboardHistory.app]
set -uo pipefail

CERT="${CERT:-LocalAppDev}"
APP_PATH="${1:-dist/ClipboardHistory.app}"
ENTITLEMENTS="$(cd "$(dirname "$0")" && pwd)/entitlements.plist"
MAIN_EXE="$APP_PATH/Contents/MacOS/ClipboardHistory"

if ! security find-identity -v -p codesigning | grep -q "$CERT"; then
  echo "ERROR: code-signing identity '$CERT' not found / not trusted in the keychain."
  exit 1
fi
if [ ! -d "$APP_PATH" ]; then
  echo "ERROR: app bundle not found at $APP_PATH (build it first)."
  exit 1
fi

echo "Signing $APP_PATH with identity '$CERT' (inside-out, no --deep)..."
find "$APP_PATH" -type f -print0 | xargs -0 codesign --remove-signature 2>/dev/null || true

warns=0
while IFS= read -r -d '' f; do
  [ "$f" = "$MAIN_EXE" ] && continue
  if file -b "$f" | grep -q "Mach-O"; then
    codesign --force --timestamp=none --sign "$CERT" --options runtime "$f" 2>/dev/null \
      || { echo "  warn: could not sign ${f#$APP_PATH/}"; warns=$((warns+1)); }
  fi
done < <(find "$APP_PATH" -type f -print0)
[ "$warns" -gt 0 ] && echo "  ($warns inner files could not be signed)"

codesign --force --timestamp=none --sign "$CERT" \
  --entitlements "$ENTITLEMENTS" --options runtime "$APP_PATH"

echo "--- verification ---"
codesign --verify --deep --strict --verbose=2 "$APP_PATH" && echo "signature OK"
codesign -dvv "$APP_PATH" 2>&1 | grep -E "Identifier|Authority" || true
