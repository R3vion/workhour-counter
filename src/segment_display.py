"""A display that draws text as seven-segment LED digits.

Each digit is made of separate segments (see `digit_path()`, not a font).
"""

from __future__ import annotations

from functools import lru_cache

from PyQt5.QtCore import QPointF, QSize, Qt
from PyQt5.QtGui import QColor, QPainter, QPainterPath, QPen, QTransform
from PyQt5.QtWidgets import QSizePolicy, QWidget

CELL_WIDTH = 0.58                  # width of one digit cell, relative to the display height
SEPARATOR_WIDTH = {":": 0.24, ",": 0.20, ".": 0.20, " ": 0.20}
GAP = 0.06                         # between digits, relative to the height
DIGIT_TOP = 0.13                   # where the digit starts inside its cell
DIGIT_HEIGHT = 0.70                # how tall the digit is
DIGIT_BOX_HEIGHT = 1.7             # digit_path() draws into a 1 x 1.7 box
SLANT = 0.12                       # horizontal lean per unit of height (the top leans right)

SEGMENT_WIDTH = 0.13               # stroke width of a segment


class SegmentDisplay(QWidget):
    def __init__(self, color: str, height: int, alignment=Qt.AlignCenter, parent=None):
        super().__init__(parent)
        self._color = QColor(color)
        self._height = height
        self._alignment = alignment
        self._text = ""
        self.setFixedHeight(height)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

    def set_text(self, text: str) -> None:
        if text != self._text:
            self._text = text
            self.updateGeometry()
            self.update()

    # Size -----------------------------------------------------------------------------

    def sizeHint(self) -> QSize:
        return QSize(int(self._content_width()) + 2, self._height)

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def _cell_width(self, char: str) -> float:
        if char.isdigit():
            return self._height * CELL_WIDTH
        return self._height * SEPARATOR_WIDTH.get(char, 0.2)

    def _content_width(self) -> float:
        if not self._text:
            return 0.0
        gaps = self._height * GAP * (len(self._text) - 1)
        return sum(self._cell_width(char) for char in self._text) + gaps

    def _start_x(self) -> float:
        free = self.width() - self._content_width()
        if self._alignment & Qt.AlignLeft:
            return 1.0
        if self._alignment & Qt.AlignRight:
            return free - 1.0
        return free / 2

    # Painting -------------------------------------------------------------------------

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        x = self._start_x()
        for char in self._text:
            if char.isdigit():
                self._draw_digit(painter, x, char)
            else:
                self._draw_separator(painter, x + self._cell_width(char) / 2, char)
            x += self._cell_width(char) + self._height * GAP

    def _draw_digit(self, painter: QPainter, x: float, digit: str) -> None:
        segments = self._digit_transform(x).map(digit_path(digit))
        _stroke(painter, segments, self._color, self._height * SEGMENT_WIDTH)

    def _digit_transform(self, cell_x: float) -> QTransform:
        """Maps digit_path()'s 1 x 1.7 box into the cell at `cell_x`, slanted to the right."""
        scale = self._height * DIGIT_HEIGHT / DIGIT_BOX_HEIGHT
        left = cell_x + (self._height * CELL_WIDTH - scale) / 2
        shear = -SLANT * scale                                   # higher points move right
        centre_shift = SLANT * scale * DIGIT_BOX_HEIGHT / 2      # keep the digit centred in its cell
        return QTransform(scale, 0, shear, scale, left + centre_shift, self._height * DIGIT_TOP)

    def _draw_separator(self, painter: QPainter, center_x: float, char: str) -> None:
        if char == ":":
            heights = (0.36, 0.64)
        elif char in ",.":
            heights = (0.80,)
        else:
            return
        middle = DIGIT_TOP + DIGIT_HEIGHT / 2
        radius = max(1.6, self._height * 0.055)
        painter.setPen(Qt.NoPen)
        painter.setBrush(self._color)
        for relative_y in heights:
            lean = SLANT * (middle - relative_y) * self._height # follow the digits' slant
            painter.drawEllipse(QPointF(center_x + lean, self._height * relative_y), radius, radius)


#   Seven-segment layout        a
#   (box 1 wide, 1.7 tall)    f   b
#                               g
#                             e   c
#                               d

_MIDDLE = DIGIT_BOX_HEIGHT / 2
_BREAK = 0.25 # how far each segment stays from the corners, so the segments look separate
SEGMENTS = {
    "a": ((_BREAK, 0.0), (1 - _BREAK, 0.0)),
    "b": ((1.0, _BREAK), (1.0, _MIDDLE - _BREAK)),
    "c": ((1.0, _MIDDLE + _BREAK), (1.0, DIGIT_BOX_HEIGHT - _BREAK)),
    "d": ((_BREAK, DIGIT_BOX_HEIGHT), (1 - _BREAK, DIGIT_BOX_HEIGHT)),
    "e": ((0.0, _MIDDLE + _BREAK), (0.0, DIGIT_BOX_HEIGHT - _BREAK)),
    "f": ((0.0, _BREAK), (0.0, _MIDDLE - _BREAK)),
    "g": ((_BREAK, _MIDDLE), (1 - _BREAK, _MIDDLE)),
}
DIGIT_SEGMENTS = {
    "0": "abcdef", "1": "bc", "2": "abged", "3": "abgcd", "4": "fgbc",
    "5": "afgcd", "6": "afgedc", "7": "abc", "8": "abcdefg", "9": "abcdfg",
}


@lru_cache(maxsize=None)
def digit_path(digit: str) -> QPainterPath:
    """The lit segments of `digit`, as separate strokes in a 1 wide, 1.7 tall box."""
    path = QPainterPath()
    for segment in DIGIT_SEGMENTS[digit]:
        start, end = SEGMENTS[segment]
        path.moveTo(*start)
        path.lineTo(*end)
    return path


def _stroke(painter: QPainter, path: QPainterPath, color: QColor, width: float) -> None:
    painter.strokePath(path, QPen(color, width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
