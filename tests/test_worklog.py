"""The CSV worklog, the locked settings and the crash checkpoint."""

import csv
import os
import shutil
import stat
import tempfile
import unittest
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

from src.checkpoint import Checkpoint
from src.integrity import IntegrityError
from src.settings import LOCK_FILE_NAME, LockedSettings, create_settings, load_settings
from src.tracker import ClosedSession, SessionTracker
from src.worklog import DELIMITER, WorkLog, read_verified, verify_file


def local(*parts) -> datetime:
    return datetime(*parts).astimezone()


SETTINGS = LockedSettings(lock_id="a1b2c3d4e5f6", hourly_rate=Decimal("4000"), currency="HUF",
                          max_idle_minutes=30, created="2026-11-01T08:00:00+01:00")


class TempFolderTest(unittest.TestCase):
    def setUp(self):
        self.folder = Path(tempfile.mkdtemp())

    def tearDown(self):
        for path in self.folder.iterdir():
            os.chmod(path, stat.S_IWRITE)          # the lock file is read-only
        shutil.rmtree(self.folder)


class WorkLogTest(TempFolderTest):
    def setUp(self):
        super().setUp()
        self.log = WorkLog(self.folder, SETTINGS)

    def rows(self, name="worklog_2026-11.csv"):
        return read_verified(self.folder / name)

    def test_rows_have_the_statement_layout(self):
        self.log.record(ClosedSession(local(2026, 11, 16, 9, 0, 0), local(2026, 11, 16, 12, 0, 5)))
        self.log.record(ClosedSession(local(2026, 11, 16, 13, 0, 0), local(2026, 11, 16, 14, 0, 0)))

        first, second = self.rows()
        self.assertEqual(first[:8], ["2026-11-16", "09:00:00", "12:00:05", "03:00:05",
                                     "03:00:05", "03:00:05", "12006", "12006"])
        self.assertEqual(second[:8], ["2026-11-16", "13:00:00", "14:00:00", "01:00:00",
                                      "04:00:05", "04:00:05", "16006", "16006"])
        self.assertEqual(second[8:11], ["4000", "HUF", "a1b2c3d4e5f6"])

    def test_session_over_midnight_is_split_into_days_and_months(self):
        self.log.record(ClosedSession(local(2026, 11, 30, 23, 0, 0), local(2026, 12, 1, 1, 30, 0)))
        (november,) = self.rows("worklog_2026-11.csv")
        (december,) = self.rows("worklog_2026-12.csv")
        self.assertEqual(november[:6], ["2026-11-30", "23:00:00", "24:00:00",
                                        "01:00:00", "01:00:00", "01:00:00"])
        self.assertEqual(december[:6], ["2026-12-01", "00:00:00", "01:30:00",
                                        "01:30:00", "01:30:00", "02:30:00"])

    def test_load_restores_the_totals(self):
        self.log.record(ClosedSession(local(2026, 11, 15, 9, 0, 0), local(2026, 11, 15, 10, 0, 0)))
        self.log.record(ClosedSession(local(2026, 11, 16, 9, 0, 0), local(2026, 11, 16, 9, 30, 0)))

        reloaded = WorkLog(self.folder, SETTINGS)
        reloaded.load()
        self.assertEqual(reloaded.total_seconds, 90 * 60)
        self.assertEqual(reloaded.seconds_on(local(2026, 11, 16).date()), 30 * 60)
        reloaded.record(ClosedSession(local(2026, 11, 16, 10, 0, 0), local(2026, 11, 16, 10, 10, 0)))
        self.assertEqual(len(self.rows()), 3)          # the chain continues after a restart

    def test_an_edited_row_is_detected(self):
        self.log.record(ClosedSession(local(2026, 11, 16, 9, 0, 0), local(2026, 11, 16, 10, 0, 0)))
        path = self.folder / "worklog_2026-11.csv"
        path.write_text(path.read_text().replace("01:00:00", "09:00:00"))
        with self.assertRaises(IntegrityError):
            WorkLog(self.folder, SETTINGS).load()

    def test_a_deleted_row_is_detected(self):
        for hour in (9, 11, 13):
            self.log.record(ClosedSession(local(2026, 11, 16, hour, 0, 0), local(2026, 11, 16, hour, 30, 0)))
        path = self.folder / "worklog_2026-11.csv"
        lines = path.read_text().splitlines(keepends=True)
        path.write_text("".join(lines[:2] + lines[3:]))         # drop the 2nd session
        with self.assertRaises(IntegrityError):
            verify_file(path)

    def test_a_worklog_of_another_setup_is_rejected(self):
        self.log.record(ClosedSession(local(2026, 11, 16, 9, 0, 0), local(2026, 11, 16, 10, 0, 0)))
        other = LockedSettings("ffffffffffff", Decimal("6000"), "HUF", 30, SETTINGS.created)
        with self.assertRaises(IntegrityError):
            WorkLog(self.folder, other).load()

    def test_verify_summarises_the_month(self):
        self.log.record(ClosedSession(local(2026, 11, 16, 9, 0, 0), local(2026, 11, 16, 10, 30, 0)))
        summary = verify_file(self.folder / "worklog_2026-11.csv")
        self.assertIn("is authentic", summary)
        self.assertIn("Wage in this file:  6 000 HUF", summary)

    def test_the_file_is_comma_separated_and_decimal_commas_are_quoted(self):
        euro = LockedSettings("a1b2c3d4e5f6", Decimal("25.50"), "EUR", 30, SETTINGS.created)
        WorkLog(self.folder, euro).record(
            ClosedSession(local(2026, 11, 16, 9, 0, 0), local(2026, 11, 16, 10, 0, 0)))
        path = self.folder / "worklog_2026-11.csv"
        with open(path, newline="", encoding="utf-8") as file:
            header, row = list(csv.reader(file, delimiter=DELIMITER))
        self.assertEqual(header[0], "date")
        self.assertEqual(header[6:8], ["daily-wage (EUR)", "total-wage (EUR)"])
        self.assertEqual(row[6:9], ["25,50", "25,50", "25,50"])
        self.assertIn('"25,50"', path.read_text())


class SettingsTest(TempFolderTest):
    def test_settings_are_written_once_and_read_back(self):
        created = create_settings(self.folder, Decimal("25.50"), "EUR", 45)
        self.assertEqual(load_settings(self.folder), created)
        with self.assertRaises(FileExistsError):
            create_settings(self.folder, Decimal("99"), "EUR", 45)

    def test_an_edited_rate_is_detected(self):
        create_settings(self.folder, Decimal("4000"), "HUF", 30)
        path = self.folder / LOCK_FILE_NAME
        os.chmod(path, stat.S_IWRITE)
        path.write_text(path.read_text().replace('"4000"', '"6000"'))
        with self.assertRaises(IntegrityError):
            load_settings(self.folder)


class CheckpointTest(TempFolderTest):
    def test_an_interrupted_session_is_recovered_up_to_the_last_checkpoint(self):
        tracker = SessionTracker(timedelta(minutes=30))
        tracker.start(local(2026, 11, 16, 9, 0, 0))
        tracker.tick(local(2026, 11, 16, 9, 4, 0), mouse_moved=True)
        checkpoint = Checkpoint(self.folder, SETTINGS.lock_id)

        checkpoint.save_if_due(local(2026, 11, 16, 9, 4, 0), tracker, 0)    # not due yet
        self.assertIsNone(checkpoint.load_interrupted_session(0))
        tracker.tick(local(2026, 11, 16, 9, 5, 0), mouse_moved=True)
        checkpoint.save_if_due(local(2026, 11, 16, 9, 5, 0), tracker, 0)    # 5 minutes: saved

        recovered = Checkpoint(self.folder, SETTINGS.lock_id).load_interrupted_session(0)
        self.assertEqual(recovered, ClosedSession(local(2026, 11, 16, 9, 0, 0), local(2026, 11, 16, 9, 5, 0)))

    def test_an_edited_checkpoint_is_rejected(self):
        tracker = SessionTracker(timedelta(minutes=30))
        tracker.start(local(2026, 11, 16, 9, 0, 0))
        checkpoint = Checkpoint(self.folder, SETTINGS.lock_id)
        checkpoint.save_if_due(local(2026, 11, 16, 9, 5, 0), tracker, 0)
        checkpoint.path.write_text(checkpoint.path.read_text().replace("09:00:00", "07:00:00"))
        with self.assertRaises(IntegrityError):
            checkpoint.load_interrupted_session(0)

    def test_a_checkpoint_cannot_be_recorded_twice(self):
        """Its session is in the worklog, yet the same file is in the folder again."""
        log = WorkLog(self.folder, SETTINGS)
        tracker = SessionTracker(timedelta(minutes=30))
        tracker.start(local(2026, 11, 16, 9, 0, 0))
        tracker.tick(local(2026, 11, 16, 9, 5, 0), mouse_moved=True)
        checkpoint = Checkpoint(self.folder, SETTINGS.lock_id)
        checkpoint.save_if_due(local(2026, 11, 16, 9, 5, 0), tracker, log.total_seconds)
        kept_copy = checkpoint.path.read_bytes()

        log.record(tracker.stop(local(2026, 11, 16, 9, 30, 0)))
        checkpoint.clear()
        checkpoint.path.write_bytes(kept_copy)
        self.assertIsNone(checkpoint.load_interrupted_session(log.total_seconds))

    def test_a_checkpoint_that_cannot_be_deleted_does_not_stop_the_app(self):
        tracker = SessionTracker(timedelta(minutes=30))
        tracker.start(local(2026, 11, 16, 9, 0, 0))
        checkpoint = Checkpoint(self.folder, SETTINGS.lock_id)
        checkpoint.save_if_due(local(2026, 11, 16, 9, 5, 0), tracker, 0)
        os.chmod(checkpoint.path, stat.S_IREAD)
        checkpoint.clear()                                   # must not raise


class WorkLogBookkeepingTest(TempFolderTest):
    """What the signatures alone cannot show: missing, copied or misplaced rows."""

    def setUp(self):
        super().setUp()
        self.log = WorkLog(self.folder, SETTINGS)

    def work(self, month, day, start_hour=9, hours=1):
        self.log.record(ClosedSession(local(2026, month, day, start_hour, 0, 0),
                                      local(2026, month, day, start_hour + hours, 0, 0)))

    def reload(self):
        WorkLog(self.folder, SETTINGS).load()

    def test_a_copy_of_a_monthly_file_is_rejected(self):
        self.work(11, 16)
        shutil.copy(self.folder / "worklog_2026-11.csv", self.folder / "worklog_2026-11 - Copy.csv")
        with self.assertRaises(IntegrityError):
            self.reload()

    def test_a_file_renamed_to_another_month_is_rejected(self):
        self.work(11, 16)
        os.rename(self.folder / "worklog_2026-11.csv", self.folder / "worklog_2026-12.csv")
        with self.assertRaises(IntegrityError):
            self.reload()

    def test_a_missing_month_is_detected(self):
        for month in (9, 10, 11):
            self.work(month, 15)
        (self.folder / "worklog_2026-10.csv").unlink()
        with self.assertRaises(IntegrityError):
            self.reload()

    def test_a_session_before_the_last_recorded_one_is_refused(self):
        self.work(11, 16, start_hour=9, hours=2)
        self.assertFalse(self.log.is_after_last_session(local(2026, 11, 16, 10, 59, 59)))
        self.assertTrue(self.log.is_after_last_session(local(2026, 11, 16, 11, 0, 0)))
        with self.assertRaises(IntegrityError):
            self.work(10, 20)                                # the clock showed last month
        self.reload()                                        # nothing was written

    def test_the_last_end_survives_a_restart_also_at_midnight(self):
        self.log.record(ClosedSession(local(2026, 11, 16, 23, 0, 0), local(2026, 11, 17, 0, 0, 0)))
        reloaded = WorkLog(self.folder, SETTINGS)
        reloaded.load()
        self.assertEqual(reloaded.last_end, local(2026, 11, 17, 0, 0, 0))

    def test_cells_keep_their_borders_in_the_signature(self):
        euro = LockedSettings("a1b2c3d4e5f6", Decimal("25.50"), "EUR", 30, SETTINGS.created)
        WorkLog(self.folder, euro).record(
            ClosedSession(local(2026, 11, 16, 9, 0, 0), local(2026, 11, 16, 10, 0, 0)))
        path = self.folder / "worklog_2026-11.csv"
        path.write_text(path.read_text().replace('"25,50","25,50","25,50"', '25,"50,25","50,25,50"'))
        with self.assertRaises(IntegrityError):
            read_verified(path)


if __name__ == "__main__":
    unittest.main()
