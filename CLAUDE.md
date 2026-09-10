# CLAUDE.md - working notes for ClipboardHistory

A Win+V style clipboard history tray app for macOS and Windows. Sibling of
ScreenCapture (~/Documents/ScreenCapture) and built the same way: PyQt6 UI,
native bits via PyObjC (macOS) / ctypes (Windows), ONE codebase, every OS
branch in platform_utils.py (IS_MACOS / IS_WINDOWS). No sys.platform checks
elsewhere. Plain ASCII in code and docs.

## Run it

macOS (the live setup): a LaunchAgent runs `.venv/bin/python3 -u main.py`
from this folder. `./install_mac.sh` writes + (re)starts it; log in
/tmp/clipboardhistory_agent.log. Restart after edits:
```
launchctl kickstart -k gui/$(id -u)/com.clipboardhistory.app
```
Foreground dev run: `.venv/bin/python main.py` (quit the agent copy first
with `main.py --quit`, or launchctl bootout, or the two fight over the port).

Windows: install.bat -> %LOCALAPPDATA%\ClipboardHistory + private venv +
Start Menu / Startup shortcuts (no exe: unsigned binaries trip endpoint
security; python.exe is signed). Never use tasklist/taskkill to find or
stop it (see ScreenCapture notes); `main.py --quit` over the lock port.

Control channel (single-instance TCP port 47410): `--show`, `--quit`,
`--status` (prints panel visible/hidden, item counts, hotkey, whether
automatic paste has its permission). Use --status when testing; it beats
screenshots.

## Architecture

main.py (tray, hotkey, paste flow, control channel) -> panel.py (popup:
search + QListView + HistoryDelegate, keyboard handling) -> history.py
(HistoryStore: history.json + images/ in the data dir) <- watcher.py
(250 ms poll of the clipboard change counter, reads via QMimeData).
hotkeys.py = parse/pretty names, WindowsHotkey (RegisterHotKey thread),
MacHotkey (Carbon, wraps hotkey_mac.py copied from ScreenCapture sc/).

Settings: app_config.py -> config.json next to main.py. Hotkey names use
Qt spelling: "Ctrl+Shift+V" means Cmd+Shift+V on macOS (Qt swaps Ctrl/Cmd;
"Meta" is the physical Control key). Default is Cmd+Shift+V / Ctrl+Shift+V.

## The paste flow (the part that matters)

1. Hotkey -> remember_front_app() (NSWorkspace frontmostApplication /
   GetForegroundWindow) BEFORE showing anything.
2. Panel shows at the mouse. macOS: the NSWindow gets the NonactivatingPanel
   style mask + level 25 + CanJoinAllSpaces (prepare_panel_window) and
   makeKeyAndOrderFront (focus_panel_window). It becomes key WITHOUT
   activating our app, so typing/arrows work and the previous app stays
   active. Verified 2026-09-09: arrows, Enter, typing into the search box
   and Esc all reach the panel this way.
3. Pick -> hide panel -> write item natively (NSPasteboard: string / NSImage
   which publishes TIFF+PNG / NSURL list; Qt clipboard on Windows) ->
   watcher.mark_own_change(id) so it is not re-parsed as a new copy (a
   re-encoded image would hash differently and duplicate) -> restore the
   remembered app -> wait until Cmd/Shift are physically released
   (modifiers_released) -> CGEventPost Cmd+V / keybd_event Ctrl+V.
4. macOS needs the Accessibility permission for the keystroke. The grant is
   per binary identity: under the LaunchAgent that is the venv's python3.
   Without it the app explains once (dialog with Open Settings), then just
   copies and tells the user to press Cmd+V. Under a signed .app
   (build.sh + LocalAppDev cert, same recipe as ScreenCapture) the grant
   sticks to the bundle across rebuilds.

## Dismissal

Two mechanisms, both needed: Qt WindowDeactivate (posted when the panel
resigns key) and a global NSEvent mouse-down monitor (no permission needed
for mouse events) in platform_utils.install_outside_click_monitor. The
hotkey toggles: pressing it while open closes the panel.

## Watcher details

- Change detection = NSPasteboard changeCount / GetClipboardSequenceNumber
  polled every 250 ms. Qt's dataChanged does NOT poll on macOS.
- Order: local file URLs -> non-empty text -> image. Text beats image on
  purpose (Excel/Word publish an image rendition of copied cells).
- Privacy: org.nspasteboard.ConcealedType / TransientType and the Windows
  ExcludeClipboardContentFromMonitorProcessing format are skipped.
- Same content copied again moves the existing item to the top (hash
  dedup), keeping its pin. Unpinned items beyond max_items are pruned;
  deleting an image item deletes its PNG.

## Testing without a keyboard

Headless panel render (light + dark) with sample items: see the harness
used on 2026-09-09 - set env CLIPBOARDHISTORY_DATA_DIR to a temp dir,
build a HistoryStore, add_text/add_files/add_image, HistoryPanel(store,
"light").set_items(store.items), panel.grab().save(...). End-to-end on the
Mac: start the app, `pbcopy` a few strings, post Cmd+Shift+V with a Quartz
CGEvent (this shell's python is Accessibility-trusted), then key code 125
(Down) and 36 (Return) and read TextEdit's document text with osascript.
Outside-click dismissal: post a synthetic mouse click elsewhere and check
`main.py --status`.

## Known remaining work
- Windows side written to mirror ScreenCapture but not yet run on the
  Windows laptop: RegisterHotKey thread, keybd_event Ctrl+V, Startup
  shortcut, clipboard sequence number, CF_HDROP via Qt urls.
- Copying a file from Finder records the paths only; if the file moves the
  item cannot be pasted (write_files drops missing paths).
- No rich text: text items are stored and pasted as plain text.
