"""Crash safety net.

While a session is open, its start and last activity are saved every 5 minutes.
After an unexpected exit (crash, power loss) the next start closes that session
at its last saved activity and records it, so at most 5 minutes are lost. A
normal Stop, or the idle limit, deletes the checkpoint.

A checkpoint also stores the worklog's total-time at the moment it was saved,
and is only accepted while the worklog still stands there. Once its session is
in the worklog, by any path, the total has grown and the checkpoint is void. So
a checkpoint can never be recorded twice.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from src.integrity import IntegrityError, canonical, is_authentic, sign
from src.tracker import ClosedSession, SessionTracker

CHECKPOINT_FILE_NAME = "workhour_checkpoint.json"
CHECKPOINT_INTERVAL = timedelta(minutes=5)


class Checkpoint:
    def __init__(self, folder: Path, lock_id: str):
        self.path = folder / CHECKPOINT_FILE_NAME
        self.lock_id = lock_id
        self._saved_at: Optional[datetime] = None

    def save_if_due(self, now: datetime, tracker: SessionTracker, worklog_total: int) -> None:
        if tracker.session_start is None:
            return
        if now - (self._saved_at or tracker.session_start) < CHECKPOINT_INTERVAL:
            return
        fields = {
            "lock_id": self.lock_id,
            "session_start": tracker.session_start.isoformat(),
            "last_activity": tracker.last_activity.isoformat(),
            "worklog_total": worklog_total,
        }
        fields["signature"] = sign(canonical(fields))
        temporary = self.path.with_suffix(".tmp")
        try:
            temporary.write_text(json.dumps(fields), encoding="utf-8")
            os.replace(temporary, self.path)       # atomic: never a half-written checkpoint
        except OSError:
            return            # best effort: a missed checkpoint only widens the crash window
        self._saved_at = now

    def clear(self) -> None:
        self._saved_at = None
        try:
            self.path.unlink(missing_ok=True)
        except OSError:
            pass      # e.g. held by a virus scanner. A leftover is harmless: it is void once
                      # the worklog total has moved on, and the next checkpoint replaces it.

    def load_interrupted_session(self, worklog_total: int) -> Optional[ClosedSession]:
        """The session that was open when the app last ended unexpectedly, if any."""
        if not self.path.exists():
            return None
        try:
            fields = json.loads(self.path.read_text(encoding="utf-8"))
            signature = fields.pop("signature")
            session = ClosedSession(datetime.fromisoformat(fields["session_start"]),
                                    datetime.fromisoformat(fields["last_activity"]))
            saved_total = fields["worklog_total"]
        except (ValueError, KeyError, TypeError, AttributeError) as error:
            raise IntegrityError("The crash-recovery file is damaged and was ignored.") from error

        if fields.get("lock_id") != self.lock_id or not is_authentic(canonical(fields), signature):
            raise IntegrityError("The crash-recovery file was modified or belongs to another "
                                 "setup, so it was ignored.")
        if saved_total != worklog_total:
            return None       # its session is already in the worklog
        return session if session.seconds > 0 else None
