"""
ClipboardHistory - a Win+V style clipboard history for macOS and Windows.

Flow: everything you copy is recorded (watcher.py -> history.py). Press the
shortcut (Cmd+Shift+V on macOS, Ctrl+Shift+V on Windows, changeable from
the menu) and the panel (panel.py) pops up at the mouse. Pick an item: it
goes back on the clipboard and, when "Paste Automatically" is on, is typed
into the app you came from with a simulated Cmd+V / Ctrl+V.

Same tray-app skeleton as ScreenCapture: single instance via a localhost
lock port, `main.py --quit` / `--show` talk to the running copy.
"""
import os
import sys
import time

LOCK_PORT = int(os.environ.get("CLIPBOARDHISTORY_LOCK_PORT", "47410"))


def _send_command(cmd: str) -> bool:
    import socket
    try:
        with socket.create_connection(("127.0.0.1", LOCK_PORT), timeout=1.0) as s:
            s.sendall(cmd.encode("ascii") + b"\n")
            return True
    except OSError:
        return False


def _query_status() -> str:
    """`main.py --status`: one line from the running copy (or 'not running')."""
    import socket
    try:
        with socket.create_connection(("127.0.0.1", LOCK_PORT), timeout=1.0) as s:
            s.sendall(b"status\n")
            s.settimeout(1.0)
            return s.recv(256).decode("ascii", "ignore").strip() or "no reply"
    except OSError:
        return "not running"


if __name__ == "__main__" and len(sys.argv) > 1 and sys.argv[1] in ("--quit", "--show", "--status"):
    if sys.argv[1] == "--status":
        print(_query_status())
        raise SystemExit(0)
    _ok = _send_command(sys.argv[1].lstrip("-"))
    print(("sent" if _ok else "no running instance") + f" ({sys.argv[1]})")
    raise SystemExit(0 if _ok else 1)

from platform_utils import (
    IS_MACOS, IS_WINDOWS, APP_NAME, PASTE_MODIFIER_LABEL, data_dir, open_folder,
    write_text, write_image, write_files, remember_front_app, restore_front_app,
    send_paste_keystroke, can_send_keystrokes, request_keystroke_permission,
    modifiers_released, prepare_panel_window, focus_panel_window,
    startup_enabled, set_startup_enabled, set_process_identity, pin_as_accessory_app,
    install_outside_click_monitor,
)

set_process_identity()

from PyQt6.QtCore import Qt, QTimer, QObject, pyqtSignal
from PyQt6.QtGui import QIcon, QAction, QCursor, QPixmap, QActionGroup
from PyQt6.QtWidgets import QApplication, QSystemTrayIcon, QMenu, QMessageBox, QDialog

import app_config
from hotkeys import make_hotkey, HotkeyDialog, pretty_hotkey
from history import HistoryStore
from watcher import ClipboardWatcher
from panel import HistoryPanel

ASSETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")


class Signals(QObject):
    show_requested = pyqtSignal()


class ClipboardHistoryApp:
    def __init__(self):
        self.app = QApplication(sys.argv)
        self.app.setApplicationName(APP_NAME)
        self.app.setOrganizationName(APP_NAME)
        self.app.setQuitOnLastWindowClosed(False)
        pin_as_accessory_app()

        self.config = app_config.load_config()
        self.hotkey_name = self.config.get("hotkey_name", app_config.DEFAULTS["hotkey_name"])

        self.store = HistoryStore(max_items=self.config.get("max_items", 100))
        self.watcher = ClipboardWatcher(self.store)
        self.watcher.store_images = bool(self.config.get("store_images", True))
        self.watcher.item_added.connect(self._on_item_added)

        self.panel = HistoryPanel(self.store, self.config.get("panel_theme", "auto"))
        self.panel.paste_requested.connect(self._on_paste_requested)
        self.panel.pin_toggled.connect(self._on_pin)
        self.panel.delete_requested.connect(self._on_delete)
        self.panel.clear_requested.connect(self._clear_history)
        prepare_panel_window(self.panel)
        install_outside_click_monitor(self.panel, self.panel.dismiss)

        self._front_token = None
        self._accessibility_nagged = False
        self._hotkey = None

        self.signals = Signals()
        self.signals.show_requested.connect(self.toggle_panel)

        self._setup_tray()
        self._setup_hotkey()
        self._setup_control_channel()
        self.watcher.start()
        print(f"[paste] automatic paste: "
              f"{'ready' if can_send_keystrokes() else 'needs the Accessibility permission'}")

    # ------------------------------------------------------------- tray

    def _app_icon(self):
        if IS_WINDOWS:
            p = os.path.join(ASSETS_DIR, "icon.ico")
            if os.path.exists(p):
                return QIcon(p)
        icon = QIcon()
        for name in ("icon_tray.png", "icon_tray@2x.png"):
            p = os.path.join(ASSETS_DIR, name)
            if os.path.exists(p):
                icon.addFile(p)
        if icon.isNull():
            icon = QIcon(os.path.join(ASSETS_DIR, "icon.png"))
        return icon

    def _setup_tray(self):
        self.tray = QSystemTrayIcon()
        self.tray.setIcon(self._app_icon())
        menu = QMenu()
        self._menu = menu

        self.open_action = QAction("Open Clipboard History", menu)
        self.open_action.triggered.connect(self.toggle_panel)
        menu.addAction(self.open_action)
        menu.addSeparator()

        self.hotkey_action = QAction("", menu)
        self.hotkey_action.triggered.connect(self._change_hotkey)
        menu.addAction(self.hotkey_action)

        self.auto_paste_action = QAction("Paste Automatically", menu)
        self.auto_paste_action.setCheckable(True)
        self.auto_paste_action.setChecked(bool(self.config.get("auto_paste", True)))
        self.auto_paste_action.toggled.connect(self._toggle_auto_paste)
        menu.addAction(self.auto_paste_action)

        self.images_action = QAction("Keep Copied Images", menu)
        self.images_action.setCheckable(True)
        self.images_action.setChecked(bool(self.config.get("store_images", True)))
        self.images_action.toggled.connect(self._toggle_images)
        menu.addAction(self.images_action)

        size_menu = QMenu("History Size", menu)
        group = QActionGroup(size_menu)
        group.setExclusive(True)
        current = int(self.config.get("max_items", 100))
        for n in (25, 50, 100, 200, 500):
            a = QAction(f"{n} items", size_menu)
            a.setCheckable(True)
            a.setChecked(n == current)
            a.triggered.connect(lambda _=False, n=n: self._set_max_items(n))
            group.addAction(a)
            size_menu.addAction(a)
        menu.addMenu(size_menu)

        theme_menu = QMenu("Appearance", menu)
        tgroup = QActionGroup(theme_menu)
        tgroup.setExclusive(True)
        cur_theme = self.config.get("panel_theme", "auto")
        for key, label in (("auto", "Match System"), ("light", "Light"), ("dark", "Dark")):
            a = QAction(label, theme_menu)
            a.setCheckable(True)
            a.setChecked(key == cur_theme)
            a.triggered.connect(lambda _=False, k=key: self._set_theme(k))
            tgroup.addAction(a)
            theme_menu.addAction(a)
        menu.addMenu(theme_menu)

        self.startup_action = QAction("Launch at Login" if IS_MACOS else "Start with Windows", menu)
        self.startup_action.setCheckable(True)
        self.startup_action.setChecked(startup_enabled())
        self.startup_action.toggled.connect(self._toggle_startup)
        menu.addAction(self.startup_action)
        menu.addSeparator()

        clear_action = QAction("Clear History...", menu)
        clear_action.triggered.connect(self._clear_history)
        menu.addAction(clear_action)
        folder_action = QAction("Open Data Folder", menu)
        folder_action.triggered.connect(lambda: open_folder(data_dir()))
        menu.addAction(folder_action)
        about_action = QAction(f"About {APP_NAME}", menu)
        about_action.triggered.connect(self._show_about)
        menu.addAction(about_action)
        menu.addSeparator()
        quit_action = QAction(f"Quit {APP_NAME}", menu)
        quit_action.triggered.connect(self._quit)
        menu.addAction(quit_action)

        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._on_tray_activated)
        self._refresh_labels()
        self.tray.show()

    def _refresh_labels(self):
        label = pretty_hotkey(self.hotkey_name)
        self.hotkey_action.setText(f"Shortcut:  {label}...")
        self.open_action.setText(f"Open Clipboard History  ({label})")
        self.tray.setToolTip(f"{APP_NAME} - press {label}")

    def _on_tray_activated(self, reason):
        # Left click on Windows opens the panel; macOS shows the menu itself.
        if IS_WINDOWS and reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.toggle_panel()

    # --------------------------------------------------------- settings

    def _save(self, key, value):
        self.config[key] = value
        app_config.save_config(self.config)

    def _toggle_auto_paste(self, on):
        self._save("auto_paste", bool(on))
        if on and not can_send_keystrokes():
            self._explain_accessibility()

    def _toggle_images(self, on):
        self._save("store_images", bool(on))
        self.watcher.store_images = bool(on)

    def _set_max_items(self, n):
        self._save("max_items", int(n))
        self.store.set_max_items(n)
        self.panel.set_items(self.store.items, keep_selection=True)

    def _set_theme(self, key):
        self._save("panel_theme", key)
        self.panel.set_theme_mode(key)

    def _toggle_startup(self, on):
        ok = set_startup_enabled(on, sys.executable, os.path.abspath(__file__),
                                 icon_path=os.path.join(ASSETS_DIR, "icon.ico"))
        if not ok:
            self._notify("Could not change the launch-at-login setting.", critical=True)
            self.startup_action.blockSignals(True)
            self.startup_action.setChecked(startup_enabled())
            self.startup_action.blockSignals(False)

    def _notify(self, text, ms=3000, critical=False):
        icon = QSystemTrayIcon.MessageIcon.Critical if critical else QSystemTrayIcon.MessageIcon.Information
        self.tray.showMessage(APP_NAME, text, icon, ms)

    # ----------------------------------------------------------- hotkey

    def _setup_hotkey(self):
        self._hotkey = make_hotkey(lambda: self.signals.show_requested.emit())
        if self._hotkey is None:
            return
        if not self._hotkey.register(self.hotkey_name):
            print(f"[hotkey] {self._hotkey.last_error}")
            self._notify(self._hotkey.last_error + " Pick another one under Shortcut.",
                         ms=6000, critical=True)

    def _change_hotkey(self):
        dlg = HotkeyDialog(self.hotkey_name)
        if dlg.exec() != QDialog.DialogCode.Accepted or not dlg.recorded_key_name:
            return
        previous = self.hotkey_name
        self.hotkey_name = dlg.recorded_key_name
        if self._hotkey is not None and not self._hotkey.register(self.hotkey_name):
            self._notify(self._hotkey.last_error, ms=5000, critical=True)
            self.hotkey_name = previous
            self._hotkey.register(previous)
            return
        self._save("hotkey_name", self.hotkey_name)
        self._refresh_labels()
        self._notify(f"Shortcut changed to {pretty_hotkey(self.hotkey_name)}", ms=2000)

    # ------------------------------------------------------------ panel

    def toggle_panel(self):
        if self.panel.isVisible():
            self.panel.dismiss()
            return
        self._front_token = remember_front_app()
        self.panel.set_items(self.store.items)
        self.panel.show_at(QCursor.pos())
        focus_panel_window(self.panel)

    def _on_item_added(self, item):
        if self.panel.isVisible():
            self.panel.set_items(self.store.items, keep_selection=True)

    def _on_pin(self, item_id):
        self.store.toggle_pin(item_id)
        self.panel.set_items(self.store.items, keep_selection=True)

    def _on_delete(self, item_id):
        self.panel.forget_thumbnail(item_id)
        self.store.delete(item_id)
        self.panel.set_items(self.store.items, keep_selection=True)

    def _clear_history(self):
        was_visible = self.panel.isVisible()
        if was_visible:
            self.panel.hide()
        box = QMessageBox()
        box.setWindowTitle(APP_NAME)
        box.setIcon(QMessageBox.Icon.Question)
        pinned = sum(1 for it in self.store.items if it.get("pinned"))
        box.setText("Clear the clipboard history?")
        box.setInformativeText("Pinned items are kept." if pinned else "This cannot be undone.")
        box.setStandardButtons(QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Yes)
        box.setDefaultButton(QMessageBox.StandardButton.Yes)
        box.setWindowFlags(box.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
        if box.exec() == QMessageBox.StandardButton.Yes:
            for it in self.store.items:
                self.panel.forget_thumbnail(it.get("id"))
            self.store.clear(keep_pinned=True)
            self.panel.set_items(self.store.items)

    # ------------------------------------------------------------ paste

    def _on_paste_requested(self, item):
        kind = item.get("kind")
        ok = False
        if kind == "text":
            ok = write_text(item.get("text", ""))
        elif kind == "files":
            ok = write_files(item.get("files", []))
        elif kind == "image":
            ok = write_image(self.store.read_image(item))
        if not ok:
            self._notify("That item could not be put on the clipboard.", critical=True)
            return
        self.watcher.mark_own_change(item.get("id"))

        token, self._front_token = self._front_token, None
        if not self.config.get("auto_paste", True):
            return
        if not can_send_keystrokes():
            if not self._accessibility_nagged:
                self._accessibility_nagged = True
                self._explain_accessibility()
            else:
                self._notify(f"Copied. Press {PASTE_MODIFIER_LABEL}+V to paste "
                             "(automatic paste needs the Accessibility permission).", ms=2500)
            return
        restore_front_app(token)
        deadline = time.time() + 1.5

        def _try_paste():
            # Wait until the user has let go of Cmd/Shift from the shortcut,
            # otherwise the app receives Cmd+Shift+V instead of Cmd+V.
            if not modifiers_released() and time.time() < deadline:
                QTimer.singleShot(30, _try_paste)
                return
            send_paste_keystroke()

        QTimer.singleShot(120, _try_paste)

    def _explain_accessibility(self):
        box = QMessageBox()
        box.setWindowTitle(APP_NAME)
        box.setIcon(QMessageBox.Icon.Information)
        box.setText("One permission is needed to paste automatically.")
        box.setInformativeText(
            "macOS only lets an app type a keystroke (the Cmd+V) into another app "
            "if it is allowed under System Settings > Privacy & Security > Accessibility.\n\n"
            "Click Open Settings, switch on ClipboardHistory (it may be listed as Python), "
            "then try again. Until then, picking an item copies it and you press Cmd+V yourself.")
        open_btn = box.addButton("Open Settings", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Later", QMessageBox.ButtonRole.RejectRole)
        box.setWindowFlags(box.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
        box.exec()
        if box.clickedButton() is open_btn:
            request_keystroke_permission()

    # --------------------------------------------------------- control

    def _setup_control_channel(self):
        self._control_sock = _lock_socket
        try:
            self._control_sock.listen(2)
            self._control_sock.setblocking(False)
        except OSError:
            self._control_sock = None
            return
        self._control_timer = QTimer()
        self._control_timer.setInterval(250)
        self._control_timer.timeout.connect(self._poll_control_channel)
        self._control_timer.start()

    def _poll_control_channel(self):
        import socket
        if self._control_sock is None:
            return
        try:
            conn, _ = self._control_sock.accept()
        except (BlockingIOError, OSError):
            return
        try:
            conn.settimeout(0.5)
            data = conn.recv(64).decode("ascii", "ignore").strip().lower()
        except OSError:
            data = ""
        if data == "quit":
            self._quit()
        elif data == "show":
            self.toggle_panel()
        elif data == "status":
            reply = (f"panel={'visible' if self.panel.isVisible() else 'hidden'} "
                     f"items={len(self.store.items)} shown={self.panel.model.rowCount()} "
                     f"search='{self.panel.search.text()}' hotkey={pretty_hotkey(self.hotkey_name)} "
                     f"auto_paste={'ok' if can_send_keystrokes() else 'needs-accessibility'}")
            try:
                conn.sendall(reply.encode("ascii") + b"\n")
            except OSError:
                pass
        try:
            conn.close()
        except OSError:
            pass

    # ------------------------------------------------------------- misc

    def _show_about(self):
        msg = QMessageBox()
        msg.setWindowTitle(APP_NAME)
        msg.setText(f"<b style='font-size:15px'>{APP_NAME}</b>")
        msg.setInformativeText(
            "Everything you copy is remembered.\n\n"
            f"Press {pretty_hotkey(self.hotkey_name)} anywhere to open the list: type to search, "
            "Up/Down to move, Enter to paste, Esc to close. "
            f"{PASTE_MODIFIER_LABEL}+1..9 paste the first nine items, "
            f"{PASTE_MODIFIER_LABEL}+P pins, {PASTE_MODIFIER_LABEL}+Backspace deletes.\n\n"
            "Copies from password managers are never recorded."
        )
        icon_path = os.path.join(ASSETS_DIR, "icon.png")
        if os.path.exists(icon_path):
            msg.setIconPixmap(QPixmap(icon_path).scaled(
                72, 72, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        msg.setWindowFlags(msg.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
        msg.exec()

    def _quit(self):
        self.watcher.stop()
        if self._hotkey is not None:
            self._hotkey.unregister()
        self.tray.hide()
        self.app.quit()

    def run(self):
        return self.app.exec()


def show_already_running_notification():
    temp_app = QApplication(sys.argv)
    temp_app.setQuitOnLastWindowClosed(False)
    tray = QSystemTrayIcon()
    icon_path = os.path.join(ASSETS_DIR, "icon.ico" if IS_WINDOWS else "icon.png")
    if os.path.exists(icon_path):
        tray.setIcon(QIcon(icon_path))
    tray.show()
    tray.showMessage(APP_NAME, f"{APP_NAME} is already running - look for its icon in the menu bar.",
                     QSystemTrayIcon.MessageIcon.Information, 3000)
    QTimer.singleShot(3500, temp_app.quit)
    temp_app.exec()


_lock_socket = None


def main():
    global _lock_socket
    import socket
    try:
        _lock_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        _lock_socket.bind(("127.0.0.1", LOCK_PORT))
    except socket.error:
        print(f"[lock] another copy already holds 127.0.0.1:{LOCK_PORT}; exiting")
        show_already_running_notification()
        sys.exit(0)
    app = ClipboardHistoryApp()
    sys.exit(app.run())


if __name__ == "__main__":
    main()
