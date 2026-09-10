# ClipboardHistory

A Win+V style clipboard history for macOS and Windows. Everything you copy
(text, links, images, screenshots, files) is remembered. Press one shortcut
and a list pops up where you are: pick an item and it is pasted.

- **macOS: Cmd+Shift+V** (on a PC keyboard: Windows key + Shift + V).
  Plain Windows+V is Cmd+V on a Mac, the normal paste, so it cannot be taken.
- **Windows: Ctrl+Shift+V** (Windows has its own Win+V).
- Change the shortcut any time from the menu-bar / tray icon.

## Using it

| Key                  | Action                                  |
|----------------------|-----------------------------------------|
| Shortcut             | open / close the list                   |
| type                 | search                                  |
| Up / Down            | move                                    |
| Enter or click       | paste the selected item                 |
| Cmd/Ctrl + 1..9      | paste the 1st..9th item directly        |
| Cmd/Ctrl + P         | pin / unpin (pinned items never expire) |
| Cmd/Ctrl + Backspace | delete                                  |
| Esc, click outside   | close                                   |

Menu: Paste Automatically, Keep Copied Images, History Size (25..500),
Appearance (match system / light / dark), Launch at Login, Clear History.

Copies from password managers (1Password, Bitwarden, ...) are never
recorded: they flag their clipboard content and the watcher skips it.

## macOS install (this is how it runs on the Mac)

```
cd ~/Documents/ClipboardHistory
./install_mac.sh
```

Creates `.venv`, installs PyQt6 + pyobjc, writes a LaunchAgent
(`~/Library/LaunchAgents/com.clipboardhistory.app.plist`) that starts the
app at login and keeps it running, and starts it now. Log:
`/tmp/clipboardhistory_agent.log`.

First automatic paste: macOS asks for the **Accessibility** permission
(System Settings > Privacy & Security > Accessibility). The app shows a
dialog with an Open Settings button; switch on the entry (it may be listed
as "python3" or "Python"). Without it, picking an item still copies it and
you press Cmd+V yourself.

`./install_mac.sh --remove` stops it and removes the LaunchAgent.
`./build.sh` optionally builds a signed ClipboardHistory.app (see CLAUDE.md).

## Windows install

Double-click `install.bat`. It copies the app to
`%LOCALAPPDATA%\ClipboardHistory` with a private venv, adds a Start Menu
entry and a Startup shortcut, and starts the app. `uninstall.bat` removes
it. Development: `run.bat` (console) or `run_hidden.bat`.

## Development

```
.venv/bin/python main.py            # run in the foreground (macOS)
.venv/bin/python main.py --status   # one-line state of the running copy
.venv/bin/python main.py --show     # open / close the panel
.venv/bin/python main.py --quit     # ask the running copy to exit
```

Only one copy runs at a time (TCP lock on 127.0.0.1:47410; override with
env `CLIPBOARDHISTORY_LOCK_PORT`). Env `CLIPBOARDHISTORY_DATA_DIR` points
the history somewhere else (tests). `CLIPBOARDHISTORY_DEBUG=1` logs panel
focus events.

Files: `main.py` (tray app, paste flow), `panel.py` (the popup),
`watcher.py` (clipboard polling), `history.py` (storage), `hotkeys.py` +
`hotkey_mac.py` (global shortcut), `platform_utils.py` (every OS-specific
bit), `app_config.py` (settings in `config.json`).

History lives in `~/Library/Application Support/ClipboardHistory` (macOS)
or `%LOCALAPPDATA%\ClipboardHistory` (Windows): `history.json` + `images/`.
