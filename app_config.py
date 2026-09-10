"""Persistent settings for ClipboardHistory - one store, config.json next to
this module (gitignored; see config.example.json).

Keys:
    hotkey_name     "Ctrl+Shift+V" (Qt spelling: Ctrl means Cmd on macOS)
    max_items       how many unpinned items to keep (pinned never expire)
    auto_paste      True = pick an item and it is typed into the app you
                    came from; False = it only goes to the clipboard
    panel_theme     "auto" | "light" | "dark"
    store_images    keep copied images / screenshots in the history
"""
import json
import os

from platform_utils import IS_MACOS

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

DEFAULTS = {
    # Qt records Command as "Ctrl" on macOS, so this is Cmd+Shift+V there
    # (the Windows key on a PC keyboard plugged into a Mac IS Command) and
    # Ctrl+Shift+V on Windows (Win+V belongs to Windows' own history).
    "hotkey_name": "Ctrl+Shift+V",
    "max_items": 100,
    "auto_paste": True,
    "panel_theme": "auto",
    "store_images": True,
}


def load_config():
    cfg = dict(DEFAULTS)
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            cfg.update(data)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    return cfg


def save_config(cfg):
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
    except OSError as e:
        print(f"[config] could not save {CONFIG_PATH}: {e}")


def get(key, default=None):
    return load_config().get(key, DEFAULTS.get(key, default))


def set_value(key, value):
    cfg = load_config()
    cfg[key] = value
    save_config(cfg)
    return cfg
