"""Writes an invoice as a PDF work statement.

The statement lists the work day by day. The details of every session stay in
the signed CSV files, which the statement names together with the build that
recorded them.
"""

from __future__ import annotations

from pathlib import Path

from PyQt5.QtCore import QMarginsF
from PyQt5.QtGui import QPageLayout, QPageSize, QPdfWriter, QTextDocument

from src import APP_NAME, VERSION
from src.integrity import IS_RELEASE_BUILD, build_fingerprint
from src.invoices import Invoice
from src.settings import LockedSettings
from src.timeutil import format_duration, format_money
from src.worklog import file_name

STYLE = """
body  { font-family: 'Segoe UI', Arial; font-size: 10pt; color: #222; }
h1    { font-size: 20pt; margin-bottom: 0; }
.meta { color: #555; }
table.lines { border-collapse: collapse; }
table.lines th { background: #eeeeee; padding: 6px 10px; }
table.lines td { padding: 5px 10px; border-bottom: 1px solid #dddddd; }
tr.total td { font-weight: bold; border-top: 2px solid #222; border-bottom: none; }
.note { color: #666; font-size: 8pt; }
.dev  { color: #c0392b; font-weight: bold; }
"""


def write_statement_pdf(path: Path, invoice: Invoice, lines: list, settings: LockedSettings,
                        chain_end: str = "") -> None:
    """Write the statement to `path`. Raises OSError if the file could not be created.

    `chain_end` (row count and last signature of the worklog) is printed on the
    statement, so its reader can later check that nothing recorded so far went missing.
    """
    document = QTextDocument()
    document.setHtml(_html(invoice, lines, settings, chain_end))

    writer = QPdfWriter(str(path))
    writer.setTitle(f"Work Statement {invoice.number}")
    writer.setPageSize(QPageSize(QPageSize.A4))
    writer.setPageMargins(QMarginsF(18, 18, 18, 18), QPageLayout.Millimeter)
    document.print_(writer)
    del writer                                   # the PDF is finished when the writer is gone

    if not path.exists() or path.stat().st_size == 0:
        raise OSError(f"The PDF could not be written to {path}")


def _html(invoice: Invoice, lines: list, settings: LockedSettings, chain_end: str) -> str:
    currency = settings.currency

    def money(amount) -> str:
        return f"{format_money(amount, currency, grouped=True)} {currency}"

    rows = "".join(
        f"<tr><td>{line.day.isoformat()}</td>"
        f"<td align='right'>{format_duration(line.seconds)}</td>"
        f"<td align='right'>{money(line.amount)}</td></tr>"
        for line in lines
    )
    source_files = ", ".join(sorted({file_name(line.day) for line in lines}))
    build = build_fingerprint() if IS_RELEASE_BUILD else "DEV"
    dev_warning = ("<p class='dev'>DEV BUILD - running from source, not valid for billing.</p>"
                   if not IS_RELEASE_BUILD else "")

    return f"""
<html><head><style>{STYLE}</style></head><body>
<h1>Work Statement</h1>
<p class='meta'>
  <b>{invoice.number}</b><br>
  Issued: {invoice.issued.isoformat()}<br>
  Period: {invoice.period_start.isoformat()} &ndash; {invoice.period_end.isoformat()}<br>
  Hourly rate: {money(settings.hourly_rate)} / hour
</p>
{dev_warning}
<table class='lines' width='100%'>
  <tr><th align='left'>Date</th><th align='right'>Time worked</th><th align='right'>Amount</th></tr>
  {rows}
  <tr class='total'><td>Total</td>
      <td align='right'>{format_duration(invoice.seconds)}</td>
      <td align='right'>{money(invoice.amount)}</td></tr>
</table>
<p class='note'>
  Measured and recorded by {APP_NAME} v{VERSION}, build {build}.<br>
  <!--Worklog current state: {chain_end}.<br>-->
  Every row of these files is signed and can be verified with the same build.<br>
  Session details: {source_files}.<br>
  Settings lock id: {settings.lock_id}<br>
</p>
</body></html>
"""
