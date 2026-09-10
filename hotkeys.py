"""Global shortcut: name parsing, both OS backends and the "press a key"
dialog. Lifted from ScreenCapture/main.py so the two apps behave the same.

Naming: "Ctrl+Shift+V". Qt swaps Ctrl/Cmd on macOS, so "Ctrl" in a stored
name means the Command key there (= the Windows key on a PC keyboard) and
"Meta" means the physical Control key. pretty_hotkey() shows the right
label for the platform.
"""
import threading

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QKeySequence
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QPushButton, QHBoxLayout

from platform_utils import IS_WINDOWS, IS_MACOS

if IS_WINDOWS:
    import ctypes
    import ctypes.wintypes

# Windows virtual-key codes for the keys we let people pick.
_WIN_VK = {
    "PRINT": 0x2C, "PRINTSCREEN": 0x2C, "SYSREQ": 0x2C,
    "PAUSE": 0x13, "SCROLLLOCK": 0x91, "NUMLOCK": 0x90,
    "INSERT": 0x2D, "INS": 0x2D, "HOME": 0x24, "END": 0x23,
    "PGUP": 0x21, "PAGEUP": 0x21, "PGDOWN": 0x22, "PAGEDOWN": 0x22,
    "DEL": 0x2E, "DELETE": 0x2E, "SPACE": 0x20, "TAB": 0x09,
    "BACKSPACE": 0x08, "ENTER": 0x0D, "RETURN": 0x0D,
}
for _i in range(1, 25):
    _WIN_VK[f"F{_i}"] = 0x70 + _i - 1
for _c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
    _WIN_VK[_c] = ord(_c)
for _d in "0123456789":
    _WIN_VK[_d] = ord(_d)

_WIN_BARE_OK = {k for k in _WIN_VK if k[0] == "F" and k[1:].isdigit()} | {
    "PRINT", "PRINTSCREEN", "SYSREQ", "PAUSE", "SCROLLLOCK", "NUMLOCK", "INSERT", "INS",
}

_MOD_ALIASES = {
    "CTRL": "Ctrl", "CONTROL": "Ctrl", "SHIFT": "Shift", "ALT": "Alt",
    "OPTION": "Alt", "META": "Meta", "WIN": "Meta", "WINDOWS": "Meta",
    "CMD": "Meta", "COMMAND": "Meta", "SUPER": "Meta",
}


def parse_hotkey(name: str):
    """'Ctrl+Shift+V' -> (['Ctrl', 'Shift'], 'V')."""
    parts = [p.strip() for p in str(name or "").replace(" ", "").split("+") if p.strip()]
    if not parts:
        return [], ""
    mods = []
    for p in parts[:-1]:
        m = _MOD_ALIASES.get(p.upper())
        if m and m not in mods:
            mods.append(m)
    key = parts[-1].upper()
    if key in ("PRINT SCREEN", "PRINTSCREEN"):
        key = "PRINT"
    return mods, key


def pretty_hotkey(name: str) -> str:
    """Human label: 'Cmd+Shift+V' on macOS, 'Ctrl+Shift+V' / 'Win+V' on Windows."""
    mods, key = parse_hotkey(name)
    label = {"PRINT": "PrintScreen", "SCROLLLOCK": "Scroll Lock",
             "PGUP": "Page Up", "PGDOWN": "Page Down"}.get(
        key, key.title() if len(key) > 1 else key)
    if IS_MACOS:
        mods = [{"Ctrl": "Cmd", "Meta": "Ctrl"}.get(m, m) for m in mods]
    else:
        mods = ["Win" if m == "Meta" else m for m in mods]
    return "+".join(mods + [label])


def hotkey_usable(name: str):
    """(usable, bare_ok) for the current platform."""
    mods, k = parse_hotkey(name)
    if IS_WINDOWS:
        return k in _WIN_VK, k in _WIN_BARE_OK
    if IS_MACOS:
        from hotkey_mac import lookup, BARE_OK
        return lookup(k) is not None, k in BARE_OK
    return True, True


class WindowsHotkey:
    """RegisterHotKey on a dedicated message-pump thread (see ScreenCapture)."""
    MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, MOD_NOREPEAT = 0x1, 0x2, 0x4, 0x8, 0x4000
    WM_HOTKEY, WM_QUIT, PM_NOREMOVE = 0x0312, 0x0012, 0x0000
    HOTKEY_ID = 1

    def __init__(self, on_press):
        self._on_press = on_press
        self._thread = None
        self._thread_id = None
        self.last_error = ""

    def register(self, name: str) -> bool:
        self.unregister()
        mods, key = parse_hotkey(name)
        vk = _WIN_VK.get(key)
        if vk is None:
            self.last_error = f"Unsupported key: {key}"
            return False
        mod_flags = self.MOD_NOREPEAT
        for m in mods:
            mod_flags |= {"Ctrl": self.MOD_CONTROL, "Shift": self.MOD_SHIFT,
                          "Alt": self.MOD_ALT, "Meta": self.MOD_WIN}[m]
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        ready = threading.Event()
        result = {}

        def _loop():
            self._thread_id = kernel32.GetCurrentThreadId()
            msg = ctypes.wintypes.MSG()
            user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, self.PM_NOREMOVE)
            ok = user32.RegisterHotKey(None, self.HOTKEY_ID, mod_flags, vk)
            result["ok"] = bool(ok)
            if not ok:
                result["err"] = kernel32.GetLastError()
            ready.set()
            if not ok:
                return
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == self.WM_HOTKEY and msg.wParam == self.HOTKEY_ID:
                    try:
                        self._on_press()
                    except Exception as e:
                        print(f"[hotkey] callback error: {e}")
            user32.UnregisterHotKey(None, self.HOTKEY_ID)

        self._thread = threading.Thread(target=_loop, daemon=True, name="ch-hotkey")
        self._thread.start()
        ready.wait(timeout=3)
        if not result.get("ok"):
            err = result.get("err", "?")
            self.last_error = (f"Could not register {pretty_hotkey(name)} (error {err}). "
                               "Another app may already use it.")
            self._thread = None
            return False
        print(f"[hotkey] {pretty_hotkey(name)} registered")
        return True

    def unregister(self):
        if self._thread is not None and self._thread_id:
            try:
                ctypes.windll.user32.PostThreadMessageW(self._thread_id, self.WM_QUIT, 0, 0)
                self._thread.join(timeout=2)
            except Exception:
                pass
        self._thread = None
        self._thread_id = None


class MacHotkey:
    """Carbon RegisterEventHotKey wrapper with the same register()/unregister()
    shape as WindowsHotkey. Callback runs on the main thread."""

    def __init__(self, on_press):
        self._on_press = on_press
        self._mgr = None
        self.last_error = ""

    def register(self, name: str) -> bool:
        from hotkey_mac import HotkeyManager, lookup, CMD_KEY, SHIFT_KEY, OPTION_KEY, CONTROL_KEY
        self.unregister()
        mods, key = parse_hotkey(name)
        vk = lookup(key)
        if vk is None:
            self.last_error = f"'{name}' is not a key macOS can register."
            return False
        carbon_mods = 0
        for m in mods:
            carbon_mods |= {"Ctrl": CMD_KEY, "Shift": SHIFT_KEY,
                            "Alt": OPTION_KEY, "Meta": CONTROL_KEY}[m]
        mgr = HotkeyManager()
        try:
            mgr.register(vk=vk, modifiers=carbon_mods, on_press=self._on_press, signature="clip")
        except Exception as e:
            self.last_error = f"Could not register {pretty_hotkey(name)}: {e}"
            return False
        self._mgr = mgr
        print(f"[hotkey] {pretty_hotkey(name)} registered")
        return True

    def unregister(self):
        if self._mgr is not None:
            try:
                self._mgr.unregister_all()
            except Exception:
                pass
        self._mgr = None


def make_hotkey(on_press):
    """The right backend for this OS (None where global hotkeys are unsupported)."""
    if IS_WINDOWS:
        return WindowsHotkey(on_press)
    if IS_MACOS:
        return MacHotkey(on_press)
    return None


class HotkeyDialog(QDialog):
    """Press the combination you want; it is validated and stored."""

    def __init__(self, current_key_name, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Set clipboard history shortcut")
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
        self.setFixedSize(380, 180)
        self.recorded_key_name = None

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 18, 20, 16)

        self.label = QLabel(f"Current shortcut: <b>{pretty_hotkey(current_key_name)}</b>")
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.label)

        self.instruction = QLabel("Press the key combination you want to use "
                                  "(for example Cmd+Shift+V)..." if IS_MACOS else
                                  "Press the key combination you want to use "
                                  "(for example Ctrl+Shift+V)...")
        self.instruction.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.instruction.setWordWrap(True)
        self.instruction.setStyleSheet("color: #666; font-style: italic;")
        layout.addWidget(self.instruction)

        btn_layout = QHBoxLayout()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addStretch()
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)
        self.setFocus()

    def keyPressEvent(self, event):
        key = event.key()
        if key in (Qt.Key.Key_Control, Qt.Key.Key_Shift, Qt.Key.Key_Alt, Qt.Key.Key_Meta,
                   Qt.Key.Key_unknown):
            return
        if key == Qt.Key.Key_Escape:
            self.reject()
            return
        seq = QKeySequence(int(event.modifiers().value) | key).toString()
        if not seq:
            return
        seq = seq.replace("Print Screen", "Print").replace("ScrollLock", "Scroll Lock")
        mods_list, k = parse_hotkey(seq)
        usable, bare_ok = hotkey_usable(seq)
        if not usable:
            self.instruction.setText(f"'{seq}' cannot be used as a global shortcut. Try another key.")
            self.instruction.setStyleSheet("color: #b00020;")
            return
        if not mods_list and not bare_ok:
            self.instruction.setText(
                f"'{seq}' alone would block that key everywhere. "
                "Add a modifier (e.g. Ctrl+Shift+V) or use an F-key.")
            self.instruction.setStyleSheet("color: #b00020;")
            return
        self.recorded_key_name = "+".join(mods_list + [k])
        self.instruction.setText(f"Selected: <b>{pretty_hotkey(self.recorded_key_name)}</b>")
        self.instruction.setStyleSheet("color: #007700; font-weight: bold;")
        QTimer.singleShot(400, self.accept)
