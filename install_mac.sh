#!/bin/bash
# macOS install: private venv in this folder + a LaunchAgent that starts the
# app at login and restarts it whenever it stops (even after Quit). Re-run
# after `git pull` to restart it.
#
#   ./install_mac.sh            install / update + start now
#   ./install_mac.sh --remove   stop and remove the LaunchAgent (files stay)
set -euo pipefail
cd "$(dirname "$0")"
HERE="$(pwd)"
LABEL="com.clipboardhistory.app"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
UID_="$(id -u)"

if [ "${1:-}" = "--remove" ]; then
  launchctl bootout "gui/$UID_/$LABEL" 2>/dev/null || true
  rm -f "$PLIST"
  echo "LaunchAgent removed. The app is no longer started at login."
  exit 0
fi

if [ ! -x .venv/bin/python ]; then
  echo "==> creating .venv"
  PY="$(command -v python3.14 || command -v python3.13 || command -v python3.12 || command -v python3)"
  "$PY" -m venv .venv
fi
echo "==> installing dependencies"
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt

echo "==> writing $PLIST"
# Same writer as the tray's "Launch at Login" item, so the two never differ.
.venv/bin/python3 -c "import platform_utils as p, sys; sys.exit(0 if p.set_startup_enabled(True, '$HERE/.venv/bin/python3', '$HERE/main.py') else 1)"

LAUNCHER="$HOME/Applications/ClipboardHistory.app"
if [ ! -e "$LAUNCHER/Contents/MacOS/ClipboardHistory" ]; then
  # A tiny applet so Cmd+Space "ClipboardHistory" starts the agent if it was
  # quit. Skipped when build.sh's real .app is installed at the same path.
  echo "==> writing Spotlight launcher $LAUNCHER"
  mkdir -p "$HOME/Applications"
  rm -rf "$LAUNCHER"
  osacompile -o "$LAUNCHER" -e "do shell script \"launchctl kickstart gui/$UID_/$LABEL || launchctl bootstrap gui/$UID_ '$PLIST'\""
  ICONSET="$(mktemp -d)/ch.iconset"; mkdir -p "$ICONSET"
  for s in 16 32 128 256 512; do
    sips -z $s $s assets/icon.png --out "$ICONSET/icon_${s}x${s}.png" >/dev/null
    d=$((s*2)); sips -z $d $d assets/icon.png --out "$ICONSET/icon_${s}x${s}@2x.png" >/dev/null
  done
  iconutil -c icns "$ICONSET" -o "$LAUNCHER/Contents/Resources/applet.icns"
  /usr/libexec/PlistBuddy -c "Add :LSUIElement bool true" "$LAUNCHER/Contents/Info.plist"
  codesign -f -s - "$LAUNCHER" 2>/dev/null || true
fi

echo "==> (re)starting"
launchctl bootout "gui/$UID_/$LABEL" 2>/dev/null || true
.venv/bin/python main.py --quit >/dev/null 2>&1 || true
sleep 1
launchctl bootstrap "gui/$UID_" "$PLIST"
# The old copy's port can stay busy for a few seconds; the agent then exits
# 1 and launchd retries every ~10 s, so poll instead of checking once.
for _ in $(seq 1 30); do
  STATUS="$(.venv/bin/python main.py --status)"
  [ "$STATUS" != "not running" ] && break
  sleep 1
done
echo "status: $STATUS"
echo
echo "Done. Press Cmd+Shift+V anywhere. Log: /tmp/clipboardhistory_agent.log"
echo "First paste: allow it under System Settings > Privacy & Security > Accessibility"
echo "(the app shows a dialog with an Open Settings button)."
