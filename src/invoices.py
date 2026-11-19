"""Invoices (work statements) and their payment status.

Every printed statement and every payment is appended to `invoices.csv`, a signed,
chained log just like the worklog. The log is append-only: marking an invoice as
paid adds a "paid" row instead of changing the "issued" row.

Which sessions an invoice covers is decided by the worklog's cumulative
`total-time`: an invoice covers every worklog row whose total-time is above the
previous invoice's and up to its own. So no hour can be billed twice or skipped.

The two logs watch each other. Every worklog row stores how far the invoice log
had invoiced when the row was written, so an invoice log that lost rows (or was
deleted) no longer matches the worklog, and the app refuses to start.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Optional

from src.integrity import IntegrityError, build_fingerprint, sign
from src.settings import LockedSettings
from src.timeutil import format_duration, format_money, parse_duration, wage
from src.worklog import (DATE, DELIMITER, SESSION_TIME, TOTAL, WorkLog, append_row,
                              chain_message, read_signed_chain, verify_file)

LOG_FILE_NAME = "invoices.csv"
HEADER = ["event", "invoice", "date", "period-start", "period-end", "time", "amount",
          "currency", "worklog-total", "lock-id", "build", "signature"]
(EVENT, INVOICE, EVENT_DATE, PERIOD_START, PERIOD_END, TIME, AMOUNT, CURRENCY, WORKLOG_TOTAL,
 LOCK_ID, BUILD, SIGNATURE) = range(12)
ISSUED, PAID = "issued", "paid"


def read_invoice_log(path: Path) -> list:
    """All rows of an invoice log, after checking every signature in the chain."""
    return read_signed_chain(path, first_column="event", column_count=len(HEADER), anchor_column=LOCK_ID)


def verify_csv(path: Path) -> str:
    """Verify a worklog or an invoice log (told apart by the header) and summarise it.

    Raises IntegrityError if anything in it was changed.
    """
    with open(path, newline="", encoding="utf-8") as csv_file:
        first_column = next(csv.reader(csv_file, delimiter=DELIMITER), [""])[0]
    return verify_invoice_log(path) if first_column == "event" else verify_file(path)


def verify_invoice_log(path: Path) -> str:
    rows = read_invoice_log(path)
    issued = [row for row in rows if row[EVENT] == ISSUED]
    if not issued:
        return f"{path.name} is authentic, but it contains no invoices yet."

    paid_numbers = {row[INVOICE] for row in rows if row[EVENT] == PAID}
    currency = issued[-1][CURRENCY]

    def total(selected) -> str:
        amount = sum((Decimal(row[AMOUNT].replace(",", ".")) for row in selected), Decimal(0))
        return f"{format_money(amount, currency, grouped=True)} {currency}"

    unpaid = [row for row in issued if row[INVOICE] not in paid_numbers]
    builds = ", ".join(sorted({row[BUILD][:12] for row in rows}))
    return "\n".join([
        f"{path.name} is authentic: every row carries a valid signature.",
        "",
        f"Invoices:  {len(issued)}  ({issued[0][INVOICE]} - {issued[-1][INVOICE]})",
        f"Invoiced in total:  {total(issued)}",
        f"Paid invoices:  {len(issued) - len(unpaid)}",
        f"Unpaid invoices:  {len(unpaid)}  ({total(unpaid)})",
        f"Recorded by build:  {builds}",
    ])


@dataclass
class Invoice:
    number: str                     # e.g. INV-2026-001
    issued: date
    period_start: date
    period_end: date
    seconds: int
    amount: Decimal
    worklog_total: int              # the worklog's total-time this invoice covers up to
    paid_on: Optional[date] = None


@dataclass(frozen=True)
class DayLine:
    """One line of a statement: the work of one day."""
    day: date
    seconds: int
    amount: Decimal


class InvoiceLog:
    def __init__(self, folder: Path, settings: LockedSettings):
        self.path = folder / LOG_FILE_NAME
        self.settings = settings
        self.invoices = []                         # oldest first
        self._last_signature = settings.lock_id    # chain anchor of an empty log

    def load(self) -> None:
        if not self.path.exists():
            return
        rows = read_invoice_log(self.path)
        by_number = {}
        for row in rows:
            if row[LOCK_ID] != self.settings.lock_id:
                raise IntegrityError(f"{self.path.name} belongs to a different setup.")
            if row[EVENT] == ISSUED:
                invoice = Invoice(
                    number=row[INVOICE],
                    issued=date.fromisoformat(row[EVENT_DATE]),
                    period_start=date.fromisoformat(row[PERIOD_START]),
                    period_end=date.fromisoformat(row[PERIOD_END]),
                    seconds=parse_duration(row[TIME]),
                    amount=Decimal(row[AMOUNT].replace(",", ".")),
                    worklog_total=parse_duration(row[WORKLOG_TOTAL]),
                )
                self.invoices.append(invoice)
                by_number[invoice.number] = invoice
            elif row[EVENT] == PAID:
                by_number[row[INVOICE]].paid_on = date.fromisoformat(row[EVENT_DATE])
        if rows:
            self._last_signature = rows[-1][SIGNATURE]

    def check_against(self, worklog: WorkLog) -> None:
        """Make sure the invoice log and the worklog tell the same story."""
        if self.invoiced_until < worklog.invoiced_until:
            raise IntegrityError(
                f"{self.path.name} is missing invoices that the worklog refers to.\n\n"
                "The invoice log was deleted or rows were removed from it."
            )
        if self.invoiced_until > worklog.total_seconds:
            raise IntegrityError(
                "The worklog is missing rows that were already invoiced.\n\n"
                "A worklog file was deleted or rows were removed from it."
            )

    # Reading ----------------------------------------------------------------------------

    @property
    def invoiced_until(self) -> int:
        """The worklog total-time already covered by invoices."""
        return self.invoices[-1].worklog_total if self.invoices else 0

    def unpaid_amount(self) -> Decimal:
        return sum((invoice.amount for invoice in self.invoices if invoice.paid_on is None), Decimal(0))

    def draft(self, worklog: WorkLog, today: date):
        """The next invoice and its day lines, covering everything not invoiced yet.

        Returns None when there is nothing new to bill.
        """
        rows = [row for row in worklog.rows if parse_duration(row[TOTAL]) > self.invoiced_until]
        if not rows:
            return None
        rate, currency = self.settings.hourly_rate, self.settings.currency

        seconds_by_day = {}
        for row in rows:
            day = date.fromisoformat(row[DATE])
            seconds_by_day[day] = seconds_by_day.get(day, 0) + parse_duration(row[SESSION_TIME])
        lines = [DayLine(day, seconds, wage(seconds, rate, currency))
                 for day, seconds in seconds_by_day.items()]

        # The invoiced time is the growth of the worklog total, not a sum over rows,
        # so nothing can be counted twice. The day lines must add up to the same.
        seconds = worklog.total_seconds - self.invoiced_until
        if seconds != sum(seconds_by_day.values()):
            raise IntegrityError("The worklog rows do not add up to the worklog total.")
        invoice = Invoice(
            number=self._next_number(today),
            issued=today,
            period_start=lines[0].day,
            period_end=lines[-1].day,
            seconds=seconds,
            amount=wage(seconds, rate, currency),
            worklog_total=worklog.total_seconds,
        )
        return invoice, lines

    def _next_number(self, today: date) -> str:
        this_year = sum(1 for invoice in self.invoices if invoice.issued.year == today.year)
        return f"INV-{today.year}-{this_year + 1:03d}"

    # Writing ------------------------------------------------------------------------------

    def record_issued(self, invoice: Invoice) -> None:
        self._append(ISSUED, invoice, invoice.issued)
        self.invoices.append(invoice)

    def record_paid(self, invoice: Invoice, paid_on: date) -> None:
        if invoice.paid_on is not None:
            raise ValueError(f"{invoice.number} is already marked as paid.")
        self._append(PAID, invoice, paid_on)
        invoice.paid_on = paid_on

    def _append(self, event: str, invoice: Invoice, event_date: date) -> None:
        currency = self.settings.currency
        values = [
            event,
            invoice.number,
            event_date.isoformat(),
            invoice.period_start.isoformat(),
            invoice.period_end.isoformat(),
            format_duration(invoice.seconds),
            format_money(invoice.amount, currency),
            currency,
            format_duration(invoice.worklog_total),
            self.settings.lock_id,
            build_fingerprint(),
        ]
        signature = sign(chain_message(self._last_signature, values))
        append_row(self.path, values + [signature], HEADER)
        self._last_signature = signature
