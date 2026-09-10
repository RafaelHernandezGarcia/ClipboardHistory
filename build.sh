#!/bin/bash
# Optional: build a signed, double-clickable ClipboardHistory.app.
# icon.icns -> PyInstaller onedir -> sign_app.sh -> ~/Applications.
# Day to day the app runs straight from this folder through the LaunchAgent
# (see install_mac.sh); the .app is only needed if you want a Finder icon.
set -euo pipefail
cd "$(dirname "$0")"

PY="${PY:-.venv/bin/python}"
DEST="${DEST:-$HOME/Applications/ClipboardHistory.app}"

echo "==> 1/4  render icon.icns from assets/icon.png"
ICONSET="$(mktemp -d)/ch.iconset"; mkdir -p "$ICONSET"
for s in 16 32 128 256 512; do
  sips -z $s $s assets/icon.png --out "$ICONSET/icon_${s}x${s}.png" >/dev/null
  d=$((s*2)); sips -z $d $d assets/icon.png --out "$ICONSET/icon_${s}x${s}@2x.png" >/dev/null
done
iconutil -c icns "$ICONSET" -o assets/icon.icns

echo "==> 2/4  PyInstaller onedir build"
rm -rf build dist
"$PY" -m PyInstaller ClipboardHistory.spec --noconfirm --clean

echo "==> 3/4  code-signing"
./sign_app.sh dist/ClipboardHistory.app

echo "==> 4/4  install to $DEST"
"$PY" main.py --quit >/dev/null 2>&1 || true
sleep 1
rm -rf "$DEST"
cp -R dist/ClipboardHistory.app "$DEST"
echo "Installed to $DEST  (open it: open \"$DEST\")"
echo "Remember: Login Item OR LaunchAgent, never both (two copies fight over the shortcut)."
