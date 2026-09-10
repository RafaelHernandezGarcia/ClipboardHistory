"""The clipboard history itself: items + on-disk persistence.

Layout under platform_utils.data_dir():
    history.json      list of items, newest first
    images/<id>.png   image items (the JSON only holds the file name)

Items are dicts (easy to JSON) with these keys:
    id        random hex
    kind      "text" | "image" | "files"
    text      the text (text items) / joined paths (files) / "" (image)
    files     list of absolute paths (files items)
    image     file name inside images/ (image items)
    width/height   pixel size of the image
    hash      content hash used to de-duplicate
    created   epoch seconds
    pinned    bool
    app       name of the app the item was copied from (may be "")

Rules: the same content copied twice moves the existing item to the top
(keeps its pin); unpinned items beyond max_items are dropped oldest first;
deleting an image item also deletes its PNG.
"""
import hashlib
import json
import os
import secrets
import time

from platform_utils import data_dir


def _new_id():
    return secrets.token_hex(8)


def content_hash(kind, payload):
    """Stable hash for de-duplication. payload: str (text/files) or bytes (png)."""
    h = hashlib.sha1()
    h.update(kind.encode("ascii"))
    h.update(b"\0")
    h.update(payload if isinstance(payload, bytes) else payload.encode("utf-8", "replace"))
    return h.hexdigest()


class HistoryStore:
    def __init__(self, max_items=100):
        self.dir = data_dir()
        self.images_dir = os.path.join(self.dir, "images")
        self.path = os.path.join(self.dir, "history.json")
        self.max_items = int(max_items)
        self.items = []
        self._load()

    # ------------------------------------------------------------ persistence

    def _load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                self.items = [d for d in data if isinstance(d, dict) and d.get("kind")]
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            self.items = []
        # Drop image items whose PNG vanished.
        self.items = [d for d in self.items
                      if d.get("kind") != "image" or os.path.exists(self.image_path(d))]

    def save(self):
        tmp = self.path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.items, f, ensure_ascii=False)
            os.replace(tmp, self.path)
        except OSError as e:
            print(f"[history] could not save: {e}")

    def image_path(self, item):
        return os.path.join(self.images_dir, item.get("image", ""))

    # ------------------------------------------------------------- mutations

    def add_text(self, text, app=""):
        text = text if isinstance(text, str) else str(text)
        if not text.strip():
            return None
        return self._add({"kind": "text", "text": text, "hash": content_hash("text", text)}, app)

    def add_files(self, paths, app=""):
        paths = [p for p in paths if p]
        if not paths:
            return None
        joined = "\n".join(paths)
        return self._add({"kind": "files", "text": joined, "files": list(paths),
                          "hash": content_hash("files", joined)}, app)

    def add_image(self, png_bytes, width, height, app=""):
        if not png_bytes:
            return None
        h = content_hash("image", png_bytes)
        existing = self._find_hash(h)
        if existing is not None:
            return self._bump(existing, app)
        name = f"{_new_id()}.png"
        try:
            with open(os.path.join(self.images_dir, name), "wb") as f:
                f.write(png_bytes)
        except OSError as e:
            print(f"[history] could not store image: {e}")
            return None
        return self._add({"kind": "image", "text": "", "image": name,
                          "width": int(width), "height": int(height), "hash": h}, app)

    def _find_hash(self, h):
        for it in self.items:
            if it.get("hash") == h:
                return it
        return None

    def _bump(self, item, app):
        """Existing content copied again: move to the top, refresh the time."""
        self.items.remove(item)
        item["created"] = time.time()
        if app:
            item["app"] = app
        self.items.insert(0, item)
        self.save()
        return item

    def _add(self, item, app):
        existing = self._find_hash(item["hash"])
        if existing is not None:
            return self._bump(existing, app)
        item.update({"id": _new_id(), "created": time.time(), "pinned": False, "app": app or ""})
        self.items.insert(0, item)
        self._prune()
        self.save()
        return item

    def _prune(self):
        unpinned = [it for it in self.items if not it.get("pinned")]
        excess = len(unpinned) - self.max_items
        if excess <= 0:
            return
        for it in reversed(unpinned):
            if excess <= 0:
                break
            self._remove_files(it)
            self.items.remove(it)
            excess -= 1

    def set_max_items(self, n):
        self.max_items = max(5, int(n))
        self._prune()
        self.save()

    def _remove_files(self, item):
        if item.get("kind") == "image":
            try:
                os.remove(self.image_path(item))
            except OSError:
                pass

    def delete(self, item_id):
        for it in list(self.items):
            if it.get("id") == item_id:
                self._remove_files(it)
                self.items.remove(it)
        self.save()

    def toggle_pin(self, item_id):
        for it in self.items:
            if it.get("id") == item_id:
                it["pinned"] = not it.get("pinned", False)
        self._prune()
        self.save()

    def move_to_top(self, item_id):
        for it in self.items:
            if it.get("id") == item_id:
                self.items.remove(it)
                it["created"] = time.time()
                self.items.insert(0, it)
                break
        self.save()

    def clear(self, keep_pinned=True):
        for it in list(self.items):
            if keep_pinned and it.get("pinned"):
                continue
            self._remove_files(it)
            self.items.remove(it)
        self.save()

    def get(self, item_id):
        for it in self.items:
            if it.get("id") == item_id:
                return it
        return None

    def read_image(self, item):
        try:
            with open(self.image_path(item), "rb") as f:
                return f.read()
        except OSError:
            return b""
