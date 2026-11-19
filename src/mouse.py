"""Tells whether the mouse really moved since the last look.

A movement counts only if the pointer is at least MIN_MOVE_PIXELS away from where
it last counted. This filters out the 1-2 pixel jitter of an optical mouse on a
bad surface.

While the screen is locked (or a UAC prompt is shown) Windows does not tell the
pointer position. That is treated as "no movement".
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from typing import Optional, Tuple

MIN_MOVE_PIXELS = 5


def cursor_position() -> Optional[Tuple[int, int]]:
    """The pointer position in screen pixels, or None if Windows refuses to tell it."""
    point = wintypes.POINT()
    if not ctypes.windll.user32.GetCursorPos(ctypes.byref(point)):
        return None
    return point.x, point.y


def is_real_move(last: Optional[Tuple[int, int]], now: Optional[Tuple[int, int]]) -> bool:
    if last is None or now is None:
        return False
    return max(abs(now[0] - last[0]), abs(now[1] - last[1])) >= MIN_MOVE_PIXELS


class MouseWatcher:
    def __init__(self):
        self._last_counted = cursor_position()

    def moved(self) -> bool:
        """Call once per tick."""
        position = cursor_position()
        if position is None:
            return False
        if self._last_counted is None:
            self._last_counted = position      # first valid reading (e.g. after unlock): a new reference
            return False
        if not is_real_move(self._last_counted, position):
            return False
        self._last_counted = position
        return True
