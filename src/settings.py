"""The locked billing settings: a fixed hourly rate that cannot be changed while in use.

The hourly rate, the currency and the idle limit are chosen once, in the first-run
dialog, and stored in the data folder in a signed lock file. No code path rewrites
it. If the file is edited by hand, its signature breaks and the app refuses to
start. A different rate needs a fresh copy of the app in a new folder.
"""

from __future__ import annotations

import json
import os
import stat
import uuid
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from typing import Optional

from src.integrity import IntegrityError, canonical, is_authentic, sign
from src.timeutil import local_now

LOCK_FILE_NAME = "workhour_settings.lock"


@dataclass(frozen=True)
class LockedSettings:
    lock_id: str             # ties CSV rows and checkpoints to this setup
    hourly_rate: Decimal
    currency: str
    max_idle_minutes: int
    created: str             # ISO timestamp of the first run

    @property
    def max_idle(self) -> timedelta:
        return timedelta(minutes=self.max_idle_minutes)

    def to_fields(self) -> dict:
        return {
            "lock_id": self.lock_id,
            "hourly_rate": str(self.hourly_rate),
            "currency": self.currency,
            "max_idle_minutes": self.max_idle_minutes,
            "created": self.created,
        }


def load_settings(folder: Path) -> Optional[LockedSettings]:
    """The locked settings of this copy, or None on the very first run."""
    path = folder / LOCK_FILE_NAME
    if not path.exists():
        return None
    try:
        fields = json.loads(path.read_text(encoding="utf-8"))
        signature = fields.pop("signature")
        settings = LockedSettings(
            lock_id=fields["lock_id"],
            hourly_rate=Decimal(fields["hourly_rate"]),
            currency=fields["currency"],
            max_idle_minutes=int(fields["max_idle_minutes"]),
            created=fields["created"],
        )
    except (ValueError, KeyError, ArithmeticError) as error:
        raise IntegrityError(f"The settings lock file ({path.name}) is damaged.") from error

    if not is_authentic(canonical(fields), signature):
        raise IntegrityError(
            f"The settings lock file ({path.name}) was modified, or it was created by "
            "a different build of the counter.\n\n"
            "Locked settings cannot be changed. To use different settings, start with "
            "a fresh copy of the app in a new folder."
        )
    return settings


def create_settings(folder: Path, hourly_rate: Decimal, currency: str,
                    max_idle_minutes: int) -> LockedSettings:
    """Write the lock file. This fails if one already exists, because settings are set exactly once."""
    settings = LockedSettings(
        lock_id=uuid.uuid4().hex[:12],
        hourly_rate=hourly_rate,
        currency=currency,
        max_idle_minutes=max_idle_minutes,
        created=local_now().isoformat(),
    )
    fields = settings.to_fields()
    fields["signature"] = sign(canonical(fields))

    path = folder / LOCK_FILE_NAME
    with open(path, "x", encoding="utf-8") as lock_file: # "x" never overwrites
        json.dump(fields, lock_file, indent=2)
    os.chmod(path, stat.S_IREAD)
    return settings
