"""The "Invoices" window: the list of statements, the unpaid amount, printing and payments."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from PyQt5.QtCore import QDate, Qt
from PyQt5.QtWidgets import (QAbstractItemView, QDateEdit, QDialog, QDialogButtonBox, QFileDialog,
                             QFormLayout, QHBoxLayout, QLabel, QMessageBox, QPushButton,
                             QTableWidget, QTableWidgetItem, QVBoxLayout)

from src import APP_NAME
from src.integrity import IntegrityError
from src.invoices import Invoice, InvoiceLog
from src.statement_pdf import write_statement_pdf
from src.timeutil import format_duration, format_money
from src.tracker import SessionTracker
from src.worklog import SIGNATURE, WorkLog

PDF_FOLDER_NAME = "generated_invoices"     # inside the data folder

COLUMNS = ("Invoice", "Issued", "Period", "Time", "Amount", "Status")


class InvoicesDialog(QDialog):
    def __init__(self, invoice_log: InvoiceLog, worklog: WorkLog, tracker: SessionTracker,
                 folder: Path, parent=None):
        super().__init__(parent)
        self.invoice_log = invoice_log
        self.worklog = worklog
        self.tracker = tracker
        self.folder = folder
        self.setWindowTitle(f"{APP_NAME} - invoices")
        self.resize(720, 360)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.unpaid_label = QLabel()

        print_button = QPushButton("Print new invoice...")
        print_button.clicked.connect(self._print_new_invoice)
        paid_button = QPushButton("Mark as paid")
        paid_button.clicked.connect(self._mark_as_paid)
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.accept)

        buttons = QHBoxLayout()
        buttons.addWidget(print_button)
        buttons.addWidget(paid_button)
        buttons.addStretch()
        buttons.addWidget(close_button)

        layout = QVBoxLayout(self)
        layout.addWidget(self.table)
        layout.addWidget(self.unpaid_label)
        layout.addLayout(buttons)
        self._fill()

    def _money(self, amount) -> str:
        currency = self.invoice_log.settings.currency
        return f"{format_money(amount, currency, grouped=True)} {currency}"

    def _fill(self) -> None:
        invoices = self.invoice_log.invoices
        self.table.setRowCount(len(invoices))
        for row, invoice in enumerate(invoices):
            status = f"Paid {invoice.paid_on.isoformat()}" if invoice.paid_on else "Unpaid"
            cells = (invoice.number, invoice.issued.isoformat(),
                     f"{invoice.period_start.isoformat()} - {invoice.period_end.isoformat()}",
                     format_duration(invoice.seconds), self._money(invoice.amount), status)
            for column, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if column in (3, 4):
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table.setItem(row, column, item)
        self.table.resizeColumnsToContents()
        self.unpaid_label.setText(f"Unpaid:  {self._money(self.invoice_log.unpaid_amount())}")

    def _print_new_invoice(self) -> None:
        if self.tracker.is_running and not self._confirm_running_session_is_left_out():
            return
        try:
            draft = self.invoice_log.draft(self.worklog, date.today())
        except IntegrityError as error:
            QMessageBox.critical(self, APP_NAME, str(error))
            return
        if draft is None:
            QMessageBox.information(self, APP_NAME, "There is no recorded work that has not been invoiced yet.")
            return
        invoice, lines = draft

        pdf_folder = self.folder / PDF_FOLDER_NAME
        try:
            pdf_folder.mkdir(exist_ok=True)
        except OSError:
            pdf_folder = self.folder            # the dialog still lets the user pick a place
        default_path = _free_path(pdf_folder, f"invoice_{invoice.issued.isoformat()}")
        chosen, _ = QFileDialog.getSaveFileName(self, "Save invoice", str(default_path), "PDF (*.pdf)")
        if not chosen:
            return
        last_row = self.worklog.rows[-1]
        chain_end = f"{len(self.worklog.rows)} rows, last signature {last_row[SIGNATURE]}"
        try:
            write_statement_pdf(Path(chosen), invoice, lines, self.invoice_log.settings, chain_end)
        except OSError as error:
            QMessageBox.critical(self, APP_NAME, f"The invoice could not be saved:\n{error}")
            return
        try:
            self.invoice_log.record_issued(invoice)
        except OSError as error:
            # A PDF that the invoice log does not know about must not stay around:
            # the next invoice would get the same number and cover the same hours.
            removed = _try_to_remove(Path(chosen))
            QMessageBox.critical(
                self, APP_NAME,
                f"The invoice could not be recorded in the invoice log:\n{error}\n\n"
                + ("The PDF was removed again. Close the invoice log if it is open in "
                   "another program, then print the invoice again." if removed else
                   f"Delete this PDF by hand, it is not a valid invoice:\n{chosen}"))
            return
        self._fill()
        QMessageBox.information(
            self, APP_NAME,
            f"{invoice.number} saved:\n{chosen}\n\n"
            f"{format_duration(invoice.seconds)}  =  {self._money(invoice.amount)}",
        )

    def _confirm_running_session_is_left_out(self) -> bool:
        answer = QMessageBox.question(
            self, APP_NAME,
            "The counter is running. The current session is not saved yet, so it will "
            "not be on this invoice (it goes on the next one).\n\nContinue?",
        )
        return answer == QMessageBox.Yes

    def _mark_as_paid(self) -> None:
        selected = self.table.selectionModel().selectedRows()
        if not selected:
            QMessageBox.information(self, APP_NAME, "Select an invoice first.")
            return
        invoice = self.invoice_log.invoices[selected[0].row()]
        if invoice.paid_on is not None:
            QMessageBox.information(self, APP_NAME, f"{invoice.number} is already marked as paid.")
            return
        paid_on = PaymentDateDialog.ask(invoice, self._money(invoice.amount), self)
        if paid_on is None:
            return
        try:
            self.invoice_log.record_paid(invoice, paid_on)
        except OSError as error:
            QMessageBox.critical(self, APP_NAME, f"The payment could not be saved:\n{error}")
            return
        self._fill()


def _free_path(folder: Path, stem: str) -> Path:
    """folder/stem.pdf, or 'stem (1).pdf', 'stem (2).pdf'... if that name is taken."""
    path = folder / f"{stem}.pdf"
    number = 1
    while path.exists():
        path = folder / f"{stem} ({number}).pdf"
        number += 1
    return path


def _try_to_remove(path: Path) -> bool:
    try:
        path.unlink()
        return True
    except OSError:
        return False


class PaymentDateDialog(QDialog):
    """Asks when an invoice was paid."""

    def __init__(self, invoice: Invoice, amount: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"{APP_NAME} - mark as paid")
        self.date_edit = QDateEdit(QDate.currentDate())
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("yyyy-MM-dd")

        form = QFormLayout()
        form.addRow("Invoice", QLabel(invoice.number))
        form.addRow("Amount", QLabel(amount))
        form.addRow("Paid on", self.date_edit)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    @classmethod
    def ask(cls, invoice: Invoice, amount: str, parent=None):
        dialog = cls(invoice, amount, parent)
        if dialog.exec_() != QDialog.Accepted:
            return None
        return dialog.date_edit.date().toPyDate()
