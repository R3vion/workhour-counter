"""Draws the app icon and saves it as assets/icon.ico.

    python tools/make_icon.py [preview.png]

The icon is a glowing amber stopwatch on a dark rounded tile. Every size is
drawn separately (so small sizes stay crisp), stored as PNG and packed into one
multi-size .ico file.
"""

import math
import struct
import sys
from pathlib import Path

from PyQt5.QtCore import QBuffer, QByteArray, QIODevice, QPointF, QRectF, Qt
from PyQt5.QtGui import QColor, QGuiApplication, QImage, QLinearGradient, QPainter, QPainterPath, QPen

SIZES = (16, 24, 32, 48, 64, 128, 256)
AMBER = QColor("#ffc53d")
CORE = QColor("#fff3cf")
OUTPUT = Path(__file__).resolve().parent.parent / "assets" / "icon.ico"


def draw_icon(size: int) -> QImage:
    image = QImage(size, size, QImage.Format_ARGB32)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing)
    s = float(size)

    # Dark tile
    tile = QRectF(s * 0.04, s * 0.04, s * 0.92, s * 0.92)
    tile_gradient = QLinearGradient(tile.topLeft(), tile.bottomLeft())
    tile_gradient.setColorAt(0.0, QColor("#3b3b3b"))
    tile_gradient.setColorAt(1.0, QColor("#1b1b1b"))
    painter.setPen(QPen(QColor("#565656"), max(1.0, s * 0.012)))
    painter.setBrush(tile_gradient)
    painter.drawRoundedRect(tile, s * 0.2, s * 0.2)

    # Stopwatch: case, stem, crown, hand (and hour ticks when there is room)
    center = QPointF(s * 0.5, s * 0.565)
    radius = s * 0.27
    shape = QPainterPath()
    shape.addEllipse(center, radius, radius)
    shape.moveTo(s * 0.5, center.y() - radius)
    shape.lineTo(s * 0.5, s * 0.215)
    shape.moveTo(s * 0.43, s * 0.195)
    shape.lineTo(s * 0.57, s * 0.195)
    angle = math.radians(50)
    shape.moveTo(center)
    shape.lineTo(center.x() + math.sin(angle) * radius * 0.68,
                 center.y() - math.cos(angle) * radius * 0.68)
    if size >= 32:
        for quarter in range(4):
            a = math.radians(quarter * 90)
            shape.moveTo(center.x() + math.sin(a) * radius * 0.80, center.y() - math.cos(a) * radius * 0.80)
            shape.lineTo(center.x() + math.sin(a) * radius * 0.64, center.y() - math.cos(a) * radius * 0.64)

    for width, alpha in ((0.15, 40), (0.09, 85), (0.055, 170)):
        glow = QColor(AMBER)
        glow.setAlpha(alpha)
        painter.strokePath(shape, QPen(glow, max(1.0, s * width), Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    painter.strokePath(shape, QPen(CORE, max(0.8, s * 0.024), Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))

    painter.setPen(Qt.NoPen)
    painter.setBrush(CORE)
    painter.drawEllipse(center, max(0.8, s * 0.032), max(0.8, s * 0.032))
    painter.end()
    return image


def png_bytes(image: QImage) -> bytes:
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(data)


def write_ico(path: Path, images: dict) -> None:
    """ICO = header + one directory entry per size + the PNG data of each size."""
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = len(header) + 16 * len(images)
    entries, payload = b"", b""
    for size, png in images.items():
        edge = 0 if size >= 256 else size          # 0 means 256 in the ICO format
        entries += struct.pack("<BBBBHHII", edge, edge, 0, 0, 1, 32, len(png), offset + len(payload))
        payload += png
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(header + entries + payload)


def main() -> None:
    app = QGuiApplication(sys.argv[:1])     # QPainter needs an application object
    images = {size: png_bytes(draw_icon(size)) for size in SIZES}
    write_ico(OUTPUT, images)
    print(f"Saved {OUTPUT}")
    if len(sys.argv) > 1:
        draw_icon(256).save(sys.argv[1])
        print(f"Saved preview {sys.argv[1]}")
    del app


if __name__ == "__main__":
    main()
