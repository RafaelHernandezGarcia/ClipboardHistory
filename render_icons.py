"""Render assets/icon.svg -> icon.png (512), icon_tray.png (22 / 44) and
icon.ico. Run once after editing the SVG: .venv/bin/python render_icons.py"""
import os
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QImage, QPainter, QColor
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtCore import QRectF

ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
app = QApplication([])
r = QSvgRenderer(os.path.join(ASSETS, "icon.svg"))

def render(size, name):
    img = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(QColor(0, 0, 0, 0))
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    r.render(p, QRectF(0, 0, size, size))
    p.end()
    img.save(os.path.join(ASSETS, name))
    return img

render(512, "icon.png")
render(22, "icon_tray.png")
render(44, "icon_tray@2x.png")
ico = render(256, "icon.ico")
print("rendered:", sorted(os.listdir(ASSETS)))
