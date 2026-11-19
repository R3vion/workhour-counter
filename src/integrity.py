"""What makes the counter's data trustworthy.

SECRET_KEY
    The key of all signatures. Every release exe has its own random key,
    compiled into it. A development build uses a public key.
sign() / is_authentic()
    HMAC-SHA256 signatures for the settings lock, every CSV row and the crash
    checkpoint. Without the key nobody can produce a valid signature, so an
    edited value is detected. Missing or copied files are caught by the
    bookkeeping checks in worklog.py and invoices.py.
build_fingerprint()
    SHA-256 of the running exe. It is shown in the window as a watermark and
    written into every CSV row. A modified or rebuilt exe has a different
    fingerprint (and a different key).

Running from source uses a public development key and the fingerprint "DEV".
Such data is clearly marked and is not valid for billing.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import sys
from functools import lru_cache
from pathlib import Path

try:
    from src import _release
except ImportError:
    _release = None

DEV_KEY = b"workhour-counter-development-key"

IS_RELEASE_BUILD = _release is not None and _release.IS_RELEASE_BUILD
SECRET_KEY = _release.SECRET_KEY if IS_RELEASE_BUILD else DEV_KEY

# The file the user started: the release exe, or main.py from source. The data folder is next to it.
PROGRAM_PATH = _release.program_path() if IS_RELEASE_BUILD else Path(sys.argv[0]).resolve()


class IntegrityError(Exception):
    """Stored data was changed outside the app, or belongs to another build or setup."""


def sign(message: str) -> str:
    return hmac.new(SECRET_KEY, message.encode("utf-8"), hashlib.sha256).hexdigest()


def is_authentic(message: str, signature: str) -> bool:
    return hmac.compare_digest(sign(message), signature)


def canonical(fields: dict) -> str:
    """A stable text form of a dict, so the same fields always give the same signature."""
    return json.dumps(fields, sort_keys=True, separators=(",", ":"))


@lru_cache(maxsize=None)
def build_fingerprint() -> str:
    """SHA-256 of the running exe, or "DEV" for a development build."""
    return _release.fingerprint(PROGRAM_PATH) if IS_RELEASE_BUILD else "DEV"


def short_fingerprint() -> str:
    return build_fingerprint()[:12]
