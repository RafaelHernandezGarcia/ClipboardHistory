"""Watches the system clipboard and feeds new copies into the HistoryStore.

Detection: a 250 ms QTimer compares platform_utils.clipboard_sequence()
(NSPasteboard changeCount / GetClipboardSequenceNumber) - cheap and works on
both OSes. Qt's QClipboard.dataChanged is also connected as an extra
trigger (it fires reliably on Windows; on macOS Qt does not poll).

Reading uses Qt's QMimeData so the code path is the same everywhere:
    files  (local URLs)       -> "files" item
    text   (non-empty)        -> "text" item
    image                     -> "image" item stored as PNG
Text wins over image when both are present (Excel / Word publish an image
rendition of copied cells; the user wants the text).

Items the app itself puts back on the clipboard are NOT re-parsed:
main.py calls mark_own_change(item_id) right after writing, which records
the new sequence number and simply moves the item to the top.
"""
from PyQt6.QtCore import QObject, QTimer, QBuffer, QIODevice, QByteArray, pyqtSignal
from PyQt6.QtWidgets import QApplication

from platform_utils import clipboard_sequence, clipboard_is_private, front_app_name

MAX_TEXT_CHARS = 2_000_000
MAX_IMAGE_PIXELS = 40_000_000


class ClipboardWatcher(QObject):
    item_added = pyqtSignal(dict)

    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self.store_images = True
        self._last_seq = clipboard_sequence()
        self._timer = QTimer(self)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self.check)
        try:
            QApplication.clipboard().dataChanged.connect(self.check)
        except Exception:
            pass

    def start(self):
        self._timer.start()

    def stop(self):
        self._timer.stop()

    def mark_own_change(self, item_id):
        """We just wrote item_id to the clipboard: do not re-parse it."""
        self._last_seq = clipboard_sequence()
        self.store.move_to_top(item_id)

    # ------------------------------------------------------------------

    def check(self):
        seq = clipboard_sequence()
        if seq is not None:
            if seq == self._last_seq:
                return
            self._last_seq = seq
        try:
            self._ingest()
        except Exception as e:
            print(f"[watcher] {e}")

    def _ingest(self):
        if clipboard_is_private():
            return
        mime = QApplication.clipboard().mimeData()
        if mime is None:
            return
        app = front_app_name()
        item = None

        if mime.hasUrls():
            paths = [u.toLocalFile() for u in mime.urls() if u.isLocalFile()]
            if paths:
                item = self.store.add_files(paths, app)

        if item is None and mime.hasText():
            text = mime.text()
            if text and text.strip():
                if len(text) > MAX_TEXT_CHARS:
                    text = text[:MAX_TEXT_CHARS]
                item = self.store.add_text(text, app)

        if item is None and self.store_images and mime.hasImage():
            img = QApplication.clipboard().image()
            if not img.isNull() and img.width() * img.height() <= MAX_IMAGE_PIXELS:
                ba = QByteArray()
                buf = QBuffer(ba)
                buf.open(QIODevice.OpenModeFlag.WriteOnly)
                img.save(buf, "PNG")
                buf.close()
                item = self.store.add_image(bytes(ba.data()), img.width(), img.height(), app)

        if item is not None:
            self.item_added.emit(item)
