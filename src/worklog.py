"""The monthly CSV worklog.

One row is one closed session. Sessions that run past midnight are split, so
every row belongs to exactly one day. A new file starts every month:
worklog_2026-11.csv, worklog_2026-12.csv, ...

Columns 1-8 are the statement itself. Columns 9-15 make every row verifiable:

    signature = HMAC(secret key, previous row's signature + row values)

The first row of each file chains to the settings lock id. Changing or inserting
a row, or deleting one in the middle, breaks the chain from that row on.

The signatures cannot show that rows are missing from the end, or that a file
was copied. So loading also checks the bookkeeping: only worklog_YYYY-MM.csv
files are accepted, every row must belong to its file's month, rows must be in
time order, and every total-time must continue the previous one.
"""

from __future__ import annotations

import csv
import json
import os
import re
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Callable, Optional

from src.integrity import IntegrityError, build_fingerprint, is_authentic, sign
from src.settings import LockedSettings
from src.timeutil import (CLOCK_FORMAT, DATE_FORMAT, format_duration, format_money, local_now,
                               parse_duration, start_of_day, wage)
from src.tracker import ClosedSession

DELIMITER = ","            # values with a decimal comma (e.g. "12,50") are quoted automatically
FILE_PATTERN = "worklog_*.csv"
FILE_NAME = re.compile(r"worklog_(\d{4}-\d{2})\.csv")

(DATE, SESSION_START, SESSION_END, SESSION_TIME, DAILY_TOTAL, TOTAL, DAILY_WAGE,
 TOTAL_WAGE, RATE, CURRENCY, LOCK_ID, BUILD, UTC_OFFSET, INVOICED_UNTIL, SIGNATURE) = range(15)
COLUMN_COUNT = 15


def header(currency: str) -> list:
    return [
        # the statement
        "date", "session-start", "session-end", "session-time",
        "daily-total-time", "total-time", f"daily-wage ({currency})", f"total-wage ({currency})",
        # verification
        "hourly-rate", "currency", "lock-id", "build", "utc-offset", "invoiced-until", "signature",
    ]


def file_name(day: date) -> str:
    return f"worklog_{day:%Y-%m}.csv"


def has_worklog_files(folder: Path) -> bool:
    return any(folder.glob(FILE_PATTERN))


def split_at_midnight(session: ClosedSession) -> list:
    """[23:00 -> 01:30] becomes [23:00 -> 24:00] and [00:00 -> 01:30]."""
    pieces = []
    start = session.start
    while True:
        midnight = start_of_day(start.date() + timedelta(days=1))
        if session.end <= midnight:
            pieces.append(ClosedSession(start, session.end))
            return pieces
        pieces.append(ClosedSession(start, midnight))
        start = midnight


def read_verified(path: Path) -> list:
    """All data rows of a worklog file, after checking every signature in the chain."""
    return read_signed_chain(path, first_column="date", column_count=COLUMN_COUNT, anchor_column=LOCK_ID)


def read_signed_chain(path: Path, first_column: str, column_count: int, anchor_column: int) -> list:
    """Rows of a signed CSV (worklog or invoice log), after checking every signature.

    The last column is the signature; the first row chains to its `anchor_column` value.
    """
    rows = []
    with open(path, newline="", encoding="utf-8") as csv_file:
        lines = csv.reader(csv_file, delimiter=DELIMITER)
        first_line = next(lines, None)
        if not first_line or first_line[0] != first_column:
            raise IntegrityError(f"{path.name}: the header row is missing or damaged.")

        previous_signature = None
        for line_number, row in enumerate(lines, start=2):
            if not row:
                continue
            if len(row) != column_count:
                raise IntegrityError(f"{path.name}, line {line_number}: unexpected number of columns.")
            values, signature = row[:-1], row[-1]
            if previous_signature is None:
                previous_signature = values[anchor_column]      # the chain's anchor
            if not is_authentic(chain_message(previous_signature, values), signature):
                raise IntegrityError(
                    f"{path.name}, line {line_number}: the signature does not match.\n\n"
                    "The row was modified, inserted or deleted, or it was written by a "
                    "different build of the counter."
                )
            previous_signature = signature
            rows.append(row)
    return rows


def row_end(row: list) -> datetime:
    """The moment a row's session ended, timezone-aware."""
    hours, minutes, seconds = (int(part) for part in row[SESSION_END].split(":"))    # may be 24:00:00
    end = datetime.strptime(row[DATE], DATE_FORMAT) + timedelta(hours=hours, minutes=minutes, seconds=seconds)
    return datetime.fromisoformat(end.isoformat() + row[UTC_OFFSET])


def verify_file(path: Path) -> str:
    """Verify one worklog file and summarise it for the reader (e.g. the client).

    Raises IntegrityError if anything in it was changed.
    """
    rows = read_verified(path)
    if not rows:
        return f"{path.name} is authentic, but it contains no sessions yet."

    first, last = rows[0], rows[-1]
    total = parse_duration(first[TOTAL]) - parse_duration(first[SESSION_TIME])
    for number, row in enumerate(rows, start=1):
        total += parse_duration(row[SESSION_TIME])
        if parse_duration(row[TOTAL]) != total:
            raise IntegrityError(f"{path.name}, session {number}: the total-time does not continue "
                                 "the previous row. Rows are missing or out of order.")

    currency = last[CURRENCY]
    rate = Decimal(last[RATE].replace(",", "."))
    seconds_in_file = sum(parse_duration(row[SESSION_TIME]) for row in rows)
    money_in_file = format_money(wage(seconds_in_file, rate, currency), currency, grouped=True)
    builds = ", ".join(sorted({row[BUILD][:12] for row in rows}))
    lines = [
        f"{path.name} is authentic: every row carries a valid signature.",
        "",
        f"Rows (sessions):  {len(rows)}",
        f"Period:  {first[DATE]} - {last[DATE]}",
        f"Time in this file:  {format_duration(seconds_in_file)}",
        f"Wage in this file:  {money_in_file} {currency}",
        f"Hourly rate:  {format_money(rate, currency, grouped=True)} {currency}",
        f"Total time, all months:  {last[TOTAL]}",
        f"Settings lock id:  {', '.join(sorted({row[LOCK_ID] for row in rows}))}",
        f"Recorded by build:  {builds}",
        f"Last signature:  {last[SIGNATURE]}",
        "",
    ]
    if row_end(last) > local_now():
        lines += ["", "WARNING: the last session ends in the future. The clock was wrong when it was recorded."]
    return "\n".join(lines)


class WorkLog:
    """Reads and appends the monthly worklog files of one locked setup."""

    def __init__(self, folder: Path, settings: LockedSettings):
        self.folder = folder
        self.settings = settings
        self.total_seconds = 0
        self.invoiced_until = 0        # the highest invoiced total-time any row refers to
        self.last_end: Optional[datetime] = None     # when the last recorded session ended
        self.rows = []                 # every verified row, oldest first
        self._daily_seconds = {}       # date -> seconds recorded on that day
        self._last_signature = {}      # file name -> signature of its last row

    def load(self) -> None:
        """Verify every worklog file and restore the totals of the earlier periods."""
        for path in sorted(self.folder.glob(FILE_PATTERN)):
            name = FILE_NAME.fullmatch(path.name)
            if name is None:
                raise IntegrityError(
                    f"{path.name} is not a worklog of this counter (expected worklog_YYYY-MM.csv).\n\n"
                    "Copies of worklog files must not be kept in the counter's folder. "
                    "Move the file somewhere else."
                )
            rows = read_verified(path)
            for number, row in enumerate(rows, start=1):
                self._check_and_count(row, f"{path.name}, session {number}", month=name.group(1))
            self.rows.extend(rows)
            if rows:
                self._last_signature[path.name] = rows[-1][SIGNATURE]

    def _check_and_count(self, row: list, where: str, month: str) -> None:
        """Make sure `row` continues everything loaded before it, then add it to the totals."""
        if row[LOCK_ID] != self.settings.lock_id:
            raise IntegrityError(f"{where} belongs to a different setup (lock id {row[LOCK_ID]}), "
                                 "not to the settings of this folder.")
        day = datetime.strptime(row[DATE], DATE_FORMAT).date()
        seconds = parse_duration(row[SESSION_TIME])
        end = row_end(row)
        in_order = (
            row[DATE].startswith(month)
            and parse_duration(row[TOTAL]) == self.total_seconds + seconds
            and parse_duration(row[DAILY_TOTAL]) == self.seconds_on(day) + seconds
            and (self.last_end is None or end >= self.last_end)
        )
        if not in_order:
            raise IntegrityError(
                f"{where} does not continue the rows before it.\n\n"
                "A worklog file is missing, was copied or renamed, or rows were removed."
            )
        self._daily_seconds[day] = self.seconds_on(day) + seconds
        self.total_seconds += seconds
        self.last_end = end
        self.invoiced_until = max(self.invoiced_until, parse_duration(row[INVOICED_UNTIL]))

    def seconds_on(self, day: date) -> int:
        return self._daily_seconds.get(day, 0)

    def is_after_last_session(self, moment: datetime) -> bool:
        """A new session may only start where the recorded ones ended, never before."""
        return self.last_end is None or moment >= self.last_end

    def record(self, session: ClosedSession, invoiced_until: int = 0,
               on_write_error: Callable[[OSError], bool] = lambda error: False) -> None:
        """Append a closed session (one row per day it touches).

        `invoiced_until` is the total-time the invoice log covers right now; it is
        written into the row, so a later loss of the invoice log is noticed.

        If a write fails (e.g. the CSV is open in Excel), `on_write_error` decides
        whether to retry. If it says no, the error is raised.
        """
        if not self.is_after_last_session(session.start):
            raise IntegrityError("The session starts before the end of the last recorded session, "
                                 "so it was not saved. The system clock was set back.")
        for piece in split_at_midnight(session):
            while True:
                try:
                    self._append(piece, invoiced_until)
                    break
                except OSError as error:
                    if not on_write_error(error):
                        raise

    def _append(self, piece: ClosedSession, invoiced_until: int) -> None:
        day = piece.start.date()
        daily = self.seconds_on(day) + piece.seconds
        total = self.total_seconds + piece.seconds
        rate, currency = self.settings.hourly_rate, self.settings.currency
        end_clock = _clock_on(day, piece.end)
        invoiced_until = max(invoiced_until, self.invoiced_until)

        values = [
            day.strftime(DATE_FORMAT),
            piece.start.strftime(CLOCK_FORMAT),
            end_clock,
            format_duration(piece.seconds),
            format_duration(daily),
            format_duration(total),
            format_money(wage(daily, rate, currency), currency),
            format_money(wage(total, rate, currency), currency),
            format_money(rate, currency),
            currency,
            self.settings.lock_id,
            build_fingerprint(),
            _utc_offset(piece.end),
            format_duration(invoiced_until),
        ]
        path = self.folder / file_name(day)
        previous_signature = self._last_signature.get(path.name, self.settings.lock_id)
        signature = sign(chain_message(previous_signature, values))

        append_row(path, values + [signature], header(currency))

        # Only after the row is safely on disk:
        self._daily_seconds[day] = daily
        self.total_seconds = total
        self.last_end = piece.end
        self.invoiced_until = invoiced_until
        self.rows.append(values + [signature])
        self._last_signature[path.name] = signature


def chain_message(previous_signature: str, values: list) -> str:
    """What a row's signature covers: the previous row's signature and this row's values.

    The values are written as a JSON list, so every cell keeps its own borders
    (a plain comma-joined text would not tell "25,50" from two cells).
    """
    return previous_signature + "\n" + json.dumps(values, separators=(",", ":"))


def _clock_on(day: date, moment: datetime) -> str:
    """Clock time of `moment` on `day`. The midnight that ends the day is written as 24:00:00."""
    return "24:00:00" if moment.date() > day else moment.strftime(CLOCK_FORMAT)


def _utc_offset(moment: datetime) -> str:
    """E.g. "+01:00". With it, session-end is an exact moment, also across clock changes."""
    offset = moment.strftime("%z")
    return f"{offset[:3]}:{offset[3:5]}"


def append_row(path: Path, row: list, header_row: list) -> None:
    is_new_file = not path.exists()
    with open(path, "a", newline="", encoding="utf-8") as csv_file:
        writer = csv.writer(csv_file, delimiter=DELIMITER)
        if is_new_file:
            writer.writerow(header_row)
        writer.writerow(row)
        csv_file.flush()
        os.fsync(csv_file.fileno()) # billing data: make sure it reached the disk
