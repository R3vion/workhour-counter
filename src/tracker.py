"""The time-keeping rules of a work session.

Vocabulary
    running        Start was pressed and Stop was not pressed yet.
    open session   The session currently being measured. While running, a session
                   is closed automatically when the idle limit is exceeded. The next
                   mouse movement then opens a new one.
    last activity  The last moment the mouse moved (or Start/Stop was pressed).

Rules
    Active time    = last activity - session start. It freezes while the mouse is
                     still, and catches up (the idle time is added) when it moves again.
    Session time   = now - session start, by the wall clock.
    Inactive time  = now - last activity.
    Idle limit     If the mouse is still for longer than the limit, the session is
                   closed at its last activity, so that whole idle stretch is not billed.
    Clock change   If the system clock was moved, the session is closed the same way,
                   so a changed clock can never add time.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from src.timeutil import whole_seconds


@dataclass(frozen=True)
class ClosedSession:
    """A finished stretch of billable work."""
    start: datetime
    end: datetime

    @property
    def seconds(self) -> int:
        return whole_seconds(self.end - self.start)


class SessionTracker:
    def __init__(self, max_idle: timedelta):
        self.max_idle = max_idle
        self.is_running = False
        self.session_start: Optional[datetime] = None
        self.last_activity: Optional[datetime] = None

    @property
    def is_paused(self) -> bool:
        """Running, but the idle limit closed the session; waiting for the mouse."""
        return self.is_running and self.session_start is None

    def start(self, now: datetime) -> None:
        if self.is_running:
            return
        self.is_running = True
        self.session_start = self.last_activity = now

    def tick(self, now: datetime, mouse_moved: bool,
             clock_changed: bool = False) -> Optional[ClosedSession]:
        """Called every second. Returns the session that had to be closed, if any."""
        if not self.is_running:
            return None
        closed = self._close_if_idle_too_long(now)
        if clock_changed and self.session_start is not None:
            closed = self._close_session()
        if mouse_moved:
            self.last_activity = now
            if self.session_start is None:
                self.session_start = now # back after a pause, new session
        return closed

    def stop(self, now: datetime, confirmed_by_user: bool = True) -> Optional[ClosedSession]:
        """End the run and return the session to save.

        Pressing Stop is itself activity, so it confirms a short idle stretch just
        before it. An automatic stop (e.g. system shutdown) does not: then the
        session ends at the last mouse movement.
        """
        if not self.is_running:
            return None
        closed = self._close_if_idle_too_long(now)
        if self.session_start is not None:
            if confirmed_by_user:
                self.last_activity = now
            closed = self._close_session()
        self.is_running = False
        self.last_activity = None
        return closed

    def cancel(self) -> None:
        """End the run and drop the open session without saving it (the clock is wrong)."""
        self.is_running = False
        self.session_start = self.last_activity = None

    def active_seconds(self) -> int:
        if self.session_start is None:
            return 0
        return whole_seconds(self.last_activity - self.session_start)

    def inactive_seconds(self, now: datetime) -> int:
        if not self.is_running:
            return 0
        return whole_seconds(now - self.last_activity)

    def session_seconds(self, now: datetime, since: Optional[datetime] = None) -> int:
        """Wall-clock length of the open session (optionally only the part after `since`)."""
        if self.session_start is None:
            return 0
        start = self.session_start if since is None else max(self.session_start, since)
        return whole_seconds(now - start)

    def _close_if_idle_too_long(self, now: datetime) -> Optional[ClosedSession]:
        if self.session_start is not None and now - self.last_activity > self.max_idle:
            return self._close_session()
        return None

    def _close_session(self) -> Optional[ClosedSession]:
        closed = ClosedSession(self.session_start, self.last_activity)
        self.session_start = None
        return closed if closed.seconds > 0 else None
