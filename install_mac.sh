#!/bin/bash
# macOS install: private venv in this folder + a LaunchAgent that starts the
# app at login and keeps it running. Re-run after `git pull` to restart it.
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
mkdir -p "$HOME/Library/LaunchAgents"
cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$HERE/.venv/bin/python3</string>
    <string>-u</string>
    <string>$HERE/main.py</string>
  </array>
  <key>WorkingDirectory</key><string>$HERE</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><dict><key>SuccessfulExit</key><false/></dict>
  <key>StandardErrorPath</key><string>/tmp/clipboardhistory_agent.log</string>
  <key>StandardOutPath</key><string>/tmp/clipboardhistory_agent.log</string>
</dict></plist>
PLIST

echo "==> (re)starting"
.venv/bin/python main.py --quit >/dev/null 2>&1 || true
launchctl bootout "gui/$UID_/$LABEL" 2>/dev/null || true
sleep 1
launchctl bootstrap "gui/$UID_" "$PLIST"
sleep 3
echo "status: $(.venv/bin/python main.py --status)"
echo
echo "Done. Press Cmd+Shift+V anywhere. Log: /tmp/clipboardhistory_agent.log"
echo "First paste: allow it under System Settings > Privacy & Security > Accessibility"
echo "(the app shows a dialog with an Open Settings button)."
