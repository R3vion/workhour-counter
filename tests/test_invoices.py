"""Invoices: what is billed, numbering, payments, tampering and the PDF."""

import sys
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

from PyQt5.QtWidgets import QApplication

from tests.test_worklog import SETTINGS, TempFolderTest, local
from src.integrity import IntegrityError
from src.invoices import InvoiceLog, verify_csv
from src.statement_pdf import write_statement_pdf
from src.tracker import ClosedSession
from src.worklog import WorkLog

APP = QApplication.instance() or QApplication(sys.argv[:1])    # the PDF writer needs one
TODAY = date(2026, 11, 30)


class InvoiceLogTest(TempFolderTest):
    def setUp(self):
        super().setUp()
        self.worklog = WorkLog(self.folder, SETTINGS)
        self.log = InvoiceLog(self.folder, SETTINGS)

    def work(self, day, start_hour, hours):
        self.worklog.record(ClosedSession(local(2026, 11, day, start_hour, 0, 0),
                                          local(2026, 11, day, start_hour + hours, 0, 0)))

    def test_a_draft_covers_everything_not_invoiced_yet_by_day(self):
        self.work(16, 9, 2)
        self.work(16, 13, 1)
        self.work(17, 9, 3)
        invoice, lines = self.log.draft(self.worklog, TODAY)
        self.assertEqual([(line.day.day, line.seconds) for line in lines], [(16, 3 * 3600), (17, 3 * 3600)])
        self.assertEqual(invoice.amount, Decimal(24000))
        self.assertEqual(invoice.number, "INV-2026-001")
        self.assertEqual((invoice.period_start, invoice.period_end), (date(2026, 11, 16), date(2026, 11, 17)))

    def test_invoiced_hours_are_never_billed_again(self):
        self.work(16, 9, 2)
        self.log.record_issued(self.log.draft(self.worklog, TODAY)[0])
        self.assertIsNone(self.log.draft(self.worklog, TODAY))

        self.work(18, 9, 1)
        invoice, lines = self.log.draft(self.worklog, TODAY)
        self.assertEqual(invoice.seconds, 3600)
        self.assertEqual(invoice.number, "INV-2026-002")

    def test_payments_and_unpaid_amount_survive_a_restart(self):
        self.work(16, 9, 2)
        first = self.log.draft(self.worklog, TODAY)[0]
        self.log.record_issued(first)
        self.work(17, 9, 1)
        self.log.record_issued(self.log.draft(self.worklog, TODAY)[0])
        self.log.record_paid(first, date(2026, 12, 5))

        reloaded = InvoiceLog(self.folder, SETTINGS)
        reloaded.load()
        self.assertEqual(reloaded.invoices[0].paid_on, date(2026, 12, 5))
        self.assertIsNone(reloaded.invoices[1].paid_on)
        self.assertEqual(reloaded.unpaid_amount(), Decimal(4000))

    def test_an_edited_invoice_log_is_detected(self):
        self.work(16, 9, 2)
        self.log.record_issued(self.log.draft(self.worklog, TODAY)[0])
        path = self.folder / "invoices.csv"
        path.write_text(path.read_text().replace("8000", "9000"))
        with self.assertRaises(IntegrityError):
            InvoiceLog(self.folder, SETTINGS).load()

    def test_verify_recognises_the_invoice_log_and_the_worklog(self):
        self.work(16, 9, 2)
        first = self.log.draft(self.worklog, TODAY)[0]
        self.log.record_issued(first)
        self.work(17, 9, 1)
        self.log.record_issued(self.log.draft(self.worklog, TODAY)[0])
        self.log.record_paid(first, date(2026, 12, 5))

        summary = verify_csv(self.folder / "invoices.csv")
        self.assertIn("Invoices:  2  (INV-2026-001 - INV-2026-002)", summary)
        self.assertIn("Unpaid invoices:  1  (4 000 HUF)", summary)
        self.assertIn("Time in this file", verify_csv(self.folder / "worklog_2026-11.csv"))

    def test_the_statement_pdf_is_written(self):
        self.work(16, 9, 2)
        invoice, lines = self.log.draft(self.worklog, TODAY)
        path = Path(self.folder) / "invoice_2026-11-30.pdf"
        write_statement_pdf(path, invoice, lines, SETTINGS, "1 rows, last signature abc")
        self.assertTrue(path.read_bytes().startswith(b"%PDF"))

    def issue(self):
        invoice = self.log.draft(self.worklog, TODAY)[0]
        self.log.record_issued(invoice)
        return invoice

    def restart(self):
        worklog, log = WorkLog(self.folder, SETTINGS), InvoiceLog(self.folder, SETTINGS)
        worklog.load()
        log.load()
        log.check_against(worklog)

    def work_after_invoice(self, day):
        self.worklog.record(ClosedSession(local(2026, 11, day, 9, 0, 0), local(2026, 11, day, 10, 0, 0)),
                            invoiced_until=self.log.invoiced_until)

    def test_a_deleted_invoice_log_is_detected(self):
        self.work(16, 9, 2)
        self.issue()
        self.work_after_invoice(17)
        self.restart()
        (self.folder / "invoices.csv").unlink()
        with self.assertRaises(IntegrityError):
            self.restart()

    def test_invoices_removed_from_the_end_are_detected(self):
        self.work(16, 9, 2)
        self.issue()
        self.work_after_invoice(17)
        self.issue()
        self.work_after_invoice(18)
        path = self.folder / "invoices.csv"
        path.write_text("".join(path.read_text().splitlines(keepends=True)[:2]))
        with self.assertRaises(IntegrityError):
            self.restart()

    def test_invoiced_rows_removed_from_the_worklog_are_detected(self):
        self.work(16, 9, 2)
        self.work(17, 9, 2)
        self.issue()
        path = self.folder / "worklog_2026-11.csv"
        path.write_text("".join(path.read_text().splitlines(keepends=True)[:2]))
        with self.assertRaises(IntegrityError):
            self.restart()


if __name__ == "__main__":
    unittest.main()
