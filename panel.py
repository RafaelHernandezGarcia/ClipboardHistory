"""The popup: search box + list of clipboard items + footer hints.

Windows' Win+V panel is the reference: it appears where you are, the most
recent copy is on top and already selected, Enter pastes it, typing filters,
Up/Down move, Esc closes. Every row also has hover buttons for pin and
delete. Cmd/Ctrl+1..9 paste the nth visible item directly.

Painting is done by a delegate over a small list model, so 500 items
scroll smoothly and the look is identical on both platforms.
"""
import os
import time

from PyQt6.QtCore import (
    Qt, QAbstractListModel, QModelIndex, QRect, QRectF, QSize, QPoint, QEvent,
    pyqtSignal, QTimer,
)
from PyQt6.QtGui import (
    QColor, QPainter, QPen, QBrush, QFont, QFontMetrics, QPixmap, QPainterPath,
    QGuiApplication, QCursor, QKeySequence, QImage,
)
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QListView, QLabel,
    QStyledItemDelegate, QStyle, QApplication, QAbstractItemView, QSizePolicy,
)

from platform_utils import IS_MACOS, SYSTEM_FONT, PASTE_MODIFIER_LABEL

ITEM_ROLE = Qt.ItemDataRole.UserRole + 1

PANEL_W = 420
PANEL_H = 540
RADIUS = 14
ROW_PAD = 10
WHEEL_STEP_PX = 40   # pixels per mouse-wheel notch (trackpads scroll 1:1)


class Theme:
    def __init__(self, dark):
        self.dark = dark
        if dark:
            self.bg = QColor(30, 30, 34, 245)
            self.border = QColor(255, 255, 255, 30)
            self.text = QColor("#F2F2F7")
            self.subtle = QColor("#9A9AA3")
            self.row_hover = QColor(255, 255, 255, 14)
            self.row_selected = QColor(88, 101, 242, 60)
            self.row_selected_border = QColor(120, 130, 255, 160)
            self.badge_bg = QColor(255, 255, 255, 18)
            self.badge_fg = QColor("#C7C7CF")
            self.search_bg = QColor(255, 255, 255, 14)
            self.search_fg = "#F2F2F7"
            self.divider = QColor(255, 255, 255, 20)
            self.accent = QColor("#7C8CFF")
            self.btn_bg = QColor(255, 255, 255, 26)
            self.btn_bg_hover = QColor(255, 255, 255, 50)
        else:
            self.bg = QColor(249, 249, 251, 247)
            self.border = QColor(0, 0, 0, 34)
            self.text = QColor("#1D1D1F")
            self.subtle = QColor("#6E6E73")
            self.row_hover = QColor(0, 0, 0, 12)
            self.row_selected = QColor(0, 103, 192, 26)
            self.row_selected_border = QColor(0, 103, 192, 140)
            self.badge_bg = QColor(0, 0, 0, 14)
            self.badge_fg = QColor("#3C3C43")
            self.search_bg = QColor(0, 0, 0, 10)
            self.search_fg = "#1D1D1F"
            self.divider = QColor(0, 0, 0, 16)
            self.accent = QColor("#0067C0")
            self.btn_bg = QColor(0, 0, 0, 20)
            self.btn_bg_hover = QColor(0, 0, 0, 48)


def system_is_dark():
    try:
        scheme = QGuiApplication.styleHints().colorScheme()
        return scheme == Qt.ColorScheme.Dark
    except Exception:
        return False


def relative_time(ts):
    try:
        delta = time.time() - float(ts)
    except (TypeError, ValueError):
        return ""
    if delta < 45:
        return "just now"
    if delta < 3600:
        return f"{int(delta // 60)} min ago"
    if delta < 86400 * 2:
        h = int(delta // 3600)
        if h < 24:
            return f"{h} h ago"
        return "yesterday"
    return time.strftime("%b %d", time.localtime(float(ts)))


def preview_lines(text, max_lines=2):
    """First lines of the text with whitespace collapsed, for the row."""
    out = []
    for raw in str(text).splitlines():
        line = " ".join(raw.split())
        if line:
            out.append(line)
        if len(out) >= max_lines:
            break
    return out or [""]


class HistoryModel(QAbstractListModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._items = []

    def set_items(self, items):
        self.beginResetModel()
        self._items = list(items)
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._items)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or index.row() >= len(self._items):
            return None
        item = self._items[index.row()]
        if role == ITEM_ROLE:
            return item
        if role == Qt.ItemDataRole.DisplayRole:
            return item.get("text", "")
        return None

    def item_at(self, row):
        if 0 <= row < len(self._items):
            return self._items[row]
        return None


class HistoryDelegate(QStyledItemDelegate):
    """Paints a row: type badge / thumbnail, preview, meta line, hover buttons."""
    pin_clicked = pyqtSignal(str)
    delete_clicked = pyqtSignal(str)

    BADGE = 34
    BTN = 24
    THUMB_MAX_H = 120
    THUMB_MAX_W = 260

    def __init__(self, panel, store, theme):
        super().__init__(panel)
        self.panel = panel
        self.store = store
        self.theme = theme
        self.hover_row = -1
        self.hover_btn = None  # (row, "pin"|"del")
        self._thumbs = {}
        self.font_main = QFont(SYSTEM_FONT, 13)
        self.font_meta = QFont(SYSTEM_FONT, 11)
        self.font_badge = QFont(SYSTEM_FONT, 12, QFont.Weight.DemiBold)

    def set_theme(self, theme):
        self.theme = theme

    # ---------------------------------------------------------- geometry

    def thumbnail(self, item):
        key = item.get("id")
        pm = self._thumbs.get(key)
        if pm is not None:
            return pm
        dpr = self.panel.devicePixelRatioF() or 1.0
        img = QImage(self.store.image_path(item))
        if img.isNull():
            pm = QPixmap()
        else:
            scaled = img.scaled(int(self.THUMB_MAX_W * dpr), int(self.THUMB_MAX_H * dpr),
                                Qt.AspectRatioMode.KeepAspectRatio,
                                Qt.TransformationMode.SmoothTransformation)
            pm = QPixmap.fromImage(scaled)
            pm.setDevicePixelRatio(dpr)
        self._thumbs[key] = pm
        return pm

    def forget_thumbnail(self, item_id):
        self._thumbs.pop(item_id, None)

    def sizeHint(self, option, index):
        item = index.data(ITEM_ROLE) or {}
        if item.get("kind") == "image":
            pm = self.thumbnail(item)
            h = int(pm.height() / (pm.devicePixelRatio() or 1)) if not pm.isNull() else 60
            return QSize(PANEL_W, max(64, h) + ROW_PAD * 2 + 18)
        fm = QFontMetrics(self.font_main)
        lines = len(preview_lines(item.get("text", "")))
        return QSize(PANEL_W, fm.lineSpacing() * lines + 18 + ROW_PAD * 2 + 4)

    def button_rects(self, rect):
        """(pin_rect, delete_rect) inside a row rect."""
        y = rect.top() + ROW_PAD
        x_del = rect.right() - 12 - self.BTN
        x_pin = x_del - 6 - self.BTN
        return (QRect(x_pin, y, self.BTN, self.BTN), QRect(x_del, y, self.BTN, self.BTN))

    # ------------------------------------------------------------- paint

    def paint(self, painter, option, index):
        item = index.data(ITEM_ROLE) or {}
        t = self.theme
        rect = option.rect
        row = index.row()
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = row == self.hover_row

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        # background
        inner = rect.adjusted(8, 2, -8, -2)
        path = QPainterPath()
        path.addRoundedRect(QRectF(inner), 9, 9)
        if selected:
            painter.fillPath(path, t.row_selected)
            painter.setPen(QPen(t.row_selected_border, 1.2))
            painter.drawPath(path)
        elif hovered:
            painter.fillPath(path, t.row_hover)

        # badge (type glyph) or thumbnail
        kind = item.get("kind", "text")
        bx = inner.left() + 10
        by = inner.top() + ROW_PAD
        badge = QRect(bx, by, self.BADGE, self.BADGE)
        content_left = badge.right() + 12
        # Reserve the right edge for the shortcut label / hover buttons so
        # the text does not reflow when the mouse moves over the row.
        content_right = inner.right() - 12 - (self.BTN * 2 + 18)

        if kind == "image":
            self._paint_badge(painter, badge, "IMG")
            pm = self.thumbnail(item)
            if not pm.isNull():
                w = int(pm.width() / (pm.devicePixelRatio() or 1))
                h = int(pm.height() / (pm.devicePixelRatio() or 1))
                target = QRect(content_left, by, min(w, content_right - content_left), h)
                clip = QPainterPath()
                clip.addRoundedRect(QRectF(target), 6, 6)
                painter.save()
                painter.setClipPath(clip)
                painter.drawPixmap(target.topLeft(), pm)
                painter.restore()
                painter.setPen(QPen(t.divider, 1))
                painter.drawRoundedRect(QRectF(target), 6, 6)
                meta_y = target.bottom() + 4
            else:
                painter.setFont(self.font_main)
                painter.setPen(t.subtle)
                painter.drawText(QRect(content_left, by, content_right - content_left, 20),
                                 Qt.AlignmentFlag.AlignVCenter, "(image missing)")
                meta_y = by + 22
            size_txt = f"{item.get('width', '?')} x {item.get('height', '?')} px"
            meta = " · ".join(x for x in [size_txt, item.get("app", ""), relative_time(item.get("created"))] if x)
        else:
            self._paint_badge(painter, badge, "TXT" if kind == "text" else "FILE")
            painter.setFont(self.font_main)
            painter.setPen(t.text)
            fm = QFontMetrics(self.font_main)
            y = by - 1
            if kind == "files":
                names = [os.path.basename(p.rstrip("/\\")) or p for p in item.get("files", [])]
                lines = [", ".join(names[:5]) + (f" (+{len(names) - 5} more)" if len(names) > 5 else "")]
            else:
                lines = preview_lines(item.get("text", ""))
            for line in lines:
                txt = fm.elidedText(line, Qt.TextElideMode.ElideRight, content_right - content_left)
                painter.drawText(QRect(content_left, y, content_right - content_left, fm.lineSpacing()),
                                 Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, txt)
                y += fm.lineSpacing()
            meta_y = y + 2
            n = len(item.get("text", ""))
            count = f"{len(item.get('files', []))} file{'s' if len(item.get('files', [])) != 1 else ''}" \
                if kind == "files" else (f"{n:,} chars" if n > 60 else "")
            meta = " · ".join(x for x in [count, item.get("app", ""), relative_time(item.get("created"))] if x)

        # meta line
        painter.setFont(self.font_meta)
        painter.setPen(t.subtle)
        if item.get("pinned"):
            meta = "Pinned · " + meta if meta else "Pinned"
        painter.drawText(QRect(content_left, meta_y, content_right - content_left, 16),
                         Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                         QFontMetrics(self.font_meta).elidedText(meta, Qt.TextElideMode.ElideRight,
                                                                 content_right - content_left))

        # shortcut number (first 9 rows) drawn at the far right when idle
        if row < 9 and not (hovered or selected):
            painter.setFont(self.font_meta)
            painter.setPen(t.subtle)
            painter.drawText(QRect(inner.right() - 60, by, 48, self.BADGE),
                             Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                             f"{PASTE_MODIFIER_LABEL}+{row + 1}")

        # hover buttons
        if hovered or selected:
            pin_r, del_r = self.button_rects(rect)
            self._paint_button(painter, pin_r, "pin", item.get("pinned", False),
                               self.hover_btn == (row, "pin"))
            self._paint_button(painter, del_r, "del", False, self.hover_btn == (row, "del"))

        painter.restore()

    def _paint_badge(self, painter, rect, label):
        t = self.theme
        path = QPainterPath()
        path.addRoundedRect(QRectF(rect), 8, 8)
        painter.fillPath(path, t.badge_bg)
        painter.setFont(QFont(SYSTEM_FONT, 9, QFont.Weight.Bold))
        painter.setPen(t.badge_fg)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, label)

    def _paint_button(self, painter, rect, kind, active, hovered):
        t = self.theme
        path = QPainterPath()
        path.addEllipse(QRectF(rect))
        painter.fillPath(path, t.btn_bg_hover if hovered else t.btn_bg)
        pen = QPen(t.accent if active else t.text, 1.6)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        c = rect.center()
        if kind == "pin":
            # simple push-pin: head + needle
            painter.setBrush(QBrush(t.accent if active else Qt.BrushStyle.NoBrush))
            head = QRectF(c.x() - 4, c.y() - 6.5, 8, 7)
            painter.drawRoundedRect(head, 2, 2)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawLine(QPoint(c.x() - 6, c.y() + 1), QPoint(c.x() + 6, c.y() + 1))
            painter.drawLine(QPoint(c.x(), c.y() + 1), QPoint(c.x(), c.y() + 7))
        else:
            painter.drawLine(QPoint(c.x() - 4, c.y() - 4), QPoint(c.x() + 4, c.y() + 4))
            painter.drawLine(QPoint(c.x() + 4, c.y() - 4), QPoint(c.x() - 4, c.y() + 4))

    # ------------------------------------------------------------ events

    def editorEvent(self, event, model, option, index):
        item = index.data(ITEM_ROLE) or {}
        row = index.row()
        et = event.type()
        if et in (QEvent.Type.MouseMove,):
            pin_r, del_r = self.button_rects(option.rect)
            pos = event.position().toPoint()
            new_btn = (row, "pin") if pin_r.contains(pos) else (row, "del") if del_r.contains(pos) else None
            if new_btn != self.hover_btn or self.hover_row != row:
                self.hover_btn = new_btn
                self.hover_row = row
                self.panel.list.viewport().update()
            return False
        if et == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton:
            pin_r, del_r = self.button_rects(option.rect)
            pos = event.position().toPoint()
            if pin_r.contains(pos):
                self.pin_clicked.emit(item.get("id", ""))
                return True
            if del_r.contains(pos):
                self.delete_clicked.emit(item.get("id", ""))
                return True
        if et == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
            pin_r, del_r = self.button_rects(option.rect)
            pos = event.position().toPoint()
            if pin_r.contains(pos) or del_r.contains(pos):
                return True  # swallow so the click does not also select/paste
        return False


class HistoryList(QListView):
    """List view that reports the hovered row to the delegate and pastes
    on click / double click."""
    activated_item = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFrameShape(QListView.Shape.NoFrame)
        self.setUniformItemSizes(False)
        self.setSpacing(0)
        self.viewport().setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def mouseMoveEvent(self, event):
        idx = self.indexAt(event.position().toPoint())
        d = self.itemDelegate()
        if isinstance(d, HistoryDelegate):
            row = idx.row() if idx.isValid() else -1
            if row != d.hover_row:
                d.hover_row = row
                d.hover_btn = None
                self.viewport().update()
        super().mouseMoveEvent(event)

    def wheelEvent(self, event):
        """Gentle, predictable scrolling. Qt's per-pixel mode scrolls
        wheelScrollLines x singleStep per tick, and singleStep is derived
        from the (tall) rows, so one notch flew past several items."""
        sb = self.verticalScrollBar()
        pd = event.pixelDelta()
        ad = event.angleDelta()
        if not pd.isNull():
            delta = pd.y()                      # trackpad: 1:1 with the fingers
        else:
            delta = int(round(ad.y() / 120.0 * WHEEL_STEP_PX))
        if os.environ.get("CLIPBOARDHISTORY_DEBUG"):
            print(f"[wheel] pixel={pd.y()} angle={ad.y()} step={sb.singleStep()} -> {delta}px")
        if delta == 0:
            event.ignore()
            return
        sb.setValue(sb.value() - delta)
        event.accept()

    def leaveEvent(self, event):
        d = self.itemDelegate()
        if isinstance(d, HistoryDelegate):
            d.hover_row = -1
            d.hover_btn = None
            self.viewport().update()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event):
        idx = self.indexAt(event.position().toPoint())
        handled_by_delegate = False
        if idx.isValid():
            d = self.itemDelegate()
            if isinstance(d, HistoryDelegate):
                pin_r, del_r = d.button_rects(self.visualRect(idx))
                p = event.position().toPoint()
                handled_by_delegate = pin_r.contains(p) or del_r.contains(p)
        super().mouseReleaseEvent(event)
        if idx.isValid() and not handled_by_delegate and event.button() == Qt.MouseButton.LeftButton:
            item = idx.data(ITEM_ROLE)
            if item:
                self.activated_item.emit(item)


class HistoryPanel(QWidget):
    paste_requested = pyqtSignal(dict)
    pin_toggled = pyqtSignal(str)
    delete_requested = pyqtSignal(str)
    clear_requested = pyqtSignal()
    dismissed = pyqtSignal()

    def __init__(self, store, theme_mode="auto"):
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint)
        self.store = store
        self.theme_mode = theme_mode
        self.theme = self._pick_theme()
        self._all_items = []
        self._suppress_dismiss = False
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setFixedSize(PANEL_W, PANEL_H)

        root = QVBoxLayout(self)
        root.setContentsMargins(1, 1, 1, 1)
        root.setSpacing(0)

        header = QWidget()
        hl = QVBoxLayout(header)
        hl.setContentsMargins(14, 14, 14, 8)
        hl.setSpacing(8)
        top = QHBoxLayout()
        self.title = QLabel("Clipboard")
        self.title.setFont(QFont(SYSTEM_FONT, 15, QFont.Weight.DemiBold))
        top.addWidget(self.title)
        top.addStretch()
        self.count_label = QLabel("")
        self.count_label.setFont(QFont(SYSTEM_FONT, 11))
        top.addWidget(self.count_label)
        hl.addLayout(top)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Search history...")
        self.search.setFont(QFont(SYSTEM_FONT, 13))
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._apply_filter)
        self.search.installEventFilter(self)
        hl.addWidget(self.search)
        root.addWidget(header)

        self.model = HistoryModel(self)
        self.delegate = HistoryDelegate(self, store, self.theme)
        self.delegate.pin_clicked.connect(self.pin_toggled)
        self.delegate.delete_clicked.connect(self.delete_requested)
        self.list = HistoryList()
        self.list.setModel(self.model)
        self.list.setItemDelegate(self.delegate)
        self.list.activated_item.connect(self._on_item_activated)
        root.addWidget(self.list, 1)

        self.empty = QLabel("Nothing here yet.\nCopy something and it will show up in this list.")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setFont(QFont(SYSTEM_FONT, 13))
        self.empty.setWordWrap(True)
        self.empty.setParent(self)
        self.empty.hide()

        footer = QWidget()
        fl = QHBoxLayout(footer)
        fl.setContentsMargins(14, 8, 14, 12)
        self.hint = QLabel("")
        self.hint.setFont(QFont(SYSTEM_FONT, 11))
        fl.addWidget(self.hint)
        fl.addStretch()
        self.clear_btn = QLabel("<a href='clear'>Clear all</a>")
        self.clear_btn.setFont(QFont(SYSTEM_FONT, 11))
        self.clear_btn.setTextInteractionFlags(Qt.TextInteractionFlag.LinksAccessibleByMouse)
        self.clear_btn.linkActivated.connect(lambda _: self.clear_requested.emit())
        fl.addWidget(self.clear_btn)
        root.addWidget(footer)

        self._apply_theme()

    # ------------------------------------------------------------ theming

    def _pick_theme(self):
        if self.theme_mode == "dark":
            return Theme(True)
        if self.theme_mode == "light":
            return Theme(False)
        return Theme(system_is_dark())

    def set_theme_mode(self, mode):
        self.theme_mode = mode
        self.theme = self._pick_theme()
        self._apply_theme()

    def _apply_theme(self):
        t = self.theme
        self.delegate.set_theme(t)
        fg = t.text.name()
        sub = t.subtle.name()
        sbg = f"rgba({t.search_bg.red()},{t.search_bg.green()},{t.search_bg.blue()},{t.search_bg.alpha()})"
        self.title.setStyleSheet(f"color: {fg}; background: transparent;")
        self.count_label.setStyleSheet(f"color: {sub}; background: transparent;")
        self.hint.setStyleSheet(f"color: {sub}; background: transparent;")
        self.empty.setStyleSheet(f"color: {sub}; background: transparent;")
        self.clear_btn.setStyleSheet(f"background: transparent; a {{ color: {sub}; }}")
        self.search.setStyleSheet(
            f"QLineEdit {{ background: {sbg}; color: {t.search_fg}; border: 1px solid transparent;"
            f" border-radius: 8px; padding: 6px 10px; selection-background-color: {t.accent.name()}; }}"
            f"QLineEdit:focus {{ border: 1px solid {t.accent.name()}; }}")
        self.list.setStyleSheet(
            "QListView { background: transparent; border: none; outline: none; }"
            "QListView::item { border: none; }"
            f"QScrollBar:vertical {{ background: transparent; width: 8px; margin: 2px; }}"
            f"QScrollBar::handle:vertical {{ background: rgba(128,128,128,110); border-radius: 4px; min-height: 30px; }}"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }"
            "QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }")
        self.hint.setText(f"Enter to paste · Esc to close · {PASTE_MODIFIER_LABEL}+P to pin")
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(r, RADIUS, RADIUS)
        p.fillPath(path, self.theme.bg)
        p.setPen(QPen(self.theme.border, 1))
        p.drawPath(path)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.empty.setGeometry(20, 120, self.width() - 40, 120)

    # --------------------------------------------------------------- data

    def set_items(self, items, keep_selection=False):
        current_id = None
        if keep_selection:
            cur = self.current_item()
            current_id = cur.get("id") if cur else None
        self._all_items = list(items)
        self._apply_filter(self.search.text(), select_id=current_id)

    def _apply_filter(self, text="", select_id=None):
        q = (text or "").strip().lower()
        if q:
            items = []
            for it in self._all_items:
                hay = (it.get("text", "") + " " + it.get("app", "")).lower()
                if it.get("kind") == "image":
                    hay += " image picture screenshot png"
                if it.get("kind") == "files":
                    hay += " file " + " ".join(it.get("files", [])).lower()
                if all(w in hay for w in q.split()):
                    items.append(it)
        else:
            items = self._all_items
        self.model.set_items(items)
        n = len(self._all_items)
        pinned = sum(1 for it in self._all_items if it.get("pinned"))
        self.count_label.setText(f"{n} item{'s' if n != 1 else ''}" + (f" · {pinned} pinned" if pinned else ""))
        self.empty.setVisible(len(items) == 0)
        if len(items) == 0:
            self.empty.setText("No matches." if q else
                               "Nothing here yet.\nCopy something and it will show up in this list.")
        self.clear_btn.setVisible(n > 0)
        # select
        row = 0
        if select_id:
            for i, it in enumerate(items):
                if it.get("id") == select_id:
                    row = i
                    break
        if items:
            self.list.setCurrentIndex(self.model.index(min(row, len(items) - 1)))
            self.list.scrollTo(self.list.currentIndex(), QAbstractItemView.ScrollHint.EnsureVisible)

    def current_item(self):
        idx = self.list.currentIndex()
        if idx.isValid():
            return idx.data(ITEM_ROLE)
        return None

    def forget_thumbnail(self, item_id):
        self.delegate.forget_thumbnail(item_id)

    # ------------------------------------------------------------ showing

    def show_at(self, pos: QPoint):
        """Show near pos (usually the mouse), kept fully inside that screen."""
        screen = QGuiApplication.screenAt(pos) or QGuiApplication.primaryScreen()
        avail = screen.availableGeometry()
        x = pos.x() - 40
        y = pos.y() + 12
        if x + self.width() > avail.right() - 8:
            x = avail.right() - 8 - self.width()
        if y + self.height() > avail.bottom() - 8:
            y = pos.y() - 12 - self.height()
        x = max(avail.left() + 8, x)
        y = max(avail.top() + 8, y)
        self.search.blockSignals(True)
        self.search.clear()
        self.search.blockSignals(False)
        self._apply_filter("")
        self.move(x, y)
        self.show()
        self.raise_()
        self.search.setFocus(Qt.FocusReason.PopupFocusReason)

    def dismiss(self):
        if self.isVisible():
            self.hide()
            self.dismissed.emit()

    def event(self, ev):
        if os.environ.get("CLIPBOARDHISTORY_DEBUG") and ev.type() in (
                QEvent.Type.WindowActivate, QEvent.Type.WindowDeactivate, QEvent.Type.Show,
                QEvent.Type.Hide, QEvent.Type.FocusIn, QEvent.Type.FocusOut):
            print(f"[panel] {ev.type().name} visible={self.isVisible()} active={self.isActiveWindow()}")
        if ev.type() == QEvent.Type.WindowDeactivate and self.isVisible() and not self._suppress_dismiss:
            # clicked somewhere else -> close like a menu would
            QTimer.singleShot(0, self._dismiss_if_inactive)
        return super().event(ev)

    def _dismiss_if_inactive(self):
        if self.isVisible() and not self.isActiveWindow():
            self.dismiss()

    # ---------------------------------------------------------- keyboard

    def eventFilter(self, obj, ev):
        if obj is self.search and ev.type() == QEvent.Type.KeyPress:
            if self._handle_key(ev):
                return True
        return super().eventFilter(obj, ev)

    def keyPressEvent(self, ev):
        if not self._handle_key(ev):
            super().keyPressEvent(ev)

    def _handle_key(self, ev):
        key = ev.key()
        mods = ev.modifiers()
        cmd = bool(mods & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier))
        if key == Qt.Key.Key_Escape:
            self.dismiss()
            return True
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            it = self.current_item()
            if it:
                self._on_item_activated(it)
            return True
        if key in (Qt.Key.Key_Up, Qt.Key.Key_Down, Qt.Key.Key_PageUp, Qt.Key.Key_PageDown,
                   Qt.Key.Key_Home, Qt.Key.Key_End):
            n = self.model.rowCount()
            if n == 0:
                return True
            row = self.list.currentIndex().row()
            if key == Qt.Key.Key_Up:
                row = max(0, row - 1)
            elif key == Qt.Key.Key_Down:
                row = min(n - 1, row + 1)
            elif key == Qt.Key.Key_PageUp:
                row = max(0, row - 6)
            elif key == Qt.Key.Key_PageDown:
                row = min(n - 1, row + 6)
            elif key == Qt.Key.Key_Home:
                row = 0
            else:
                row = n - 1
            self.list.setCurrentIndex(self.model.index(row))
            self.list.scrollTo(self.list.currentIndex(), QAbstractItemView.ScrollHint.EnsureVisible)
            return True
        if cmd and key == Qt.Key.Key_P:
            it = self.current_item()
            if it:
                self.pin_toggled.emit(it["id"])
            return True
        if cmd and key in (Qt.Key.Key_Backspace, Qt.Key.Key_Delete):
            it = self.current_item()
            if it:
                self.delete_requested.emit(it["id"])
            return True
        if cmd and Qt.Key.Key_1 <= key <= Qt.Key.Key_9:
            it = self.model.item_at(key - Qt.Key.Key_1)
            if it:
                self._on_item_activated(it)
            return True
        return False

    def _on_item_activated(self, item):
        self._suppress_dismiss = True
        self.hide()
        self._suppress_dismiss = False
        self.paste_requested.emit(item)
