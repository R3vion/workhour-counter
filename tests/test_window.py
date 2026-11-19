"""The window's clock rules, driven by hand with stand-in clocks (the real clock is not touched)."""

import sys
import types
import unittest
from datetime import datetime, timedelta

from PyQt5.QtWidgets import QApplication

import src.main_window as main_window
from tests.test_worklog import SETTINGS, TempFolderTest
from src.checkpoint import Checkpoint
from src.invoices import InvoiceLog
from src.mouse import is_real_move
from src.worklog import SESSION_END, SESSION_START, SESSION_TIME, WorkLog

APP = QApplication.instance() or QApplication(sys.argv[:1])


class FakeMouse:
    """Moves on every tick unless told otherwise."""
    def __init__(self):
        self.moving = True

    def moved(self) -> bool:
        return self.moving


class FakeMessageBox:
    """Records warnings instead of showing them."""
    shown = []

    @classmethod
    def warning(cls, parent, title, text, *args):
        cls.shown.append(text)

    critical = warning


class WindowClockTest(TempFolderTest):
    def setUp(self):
        super().setUp()
        self.wall = datetime(2026, 11, 16, 9, 0, 0).astimezone()     # what the system clock shows
        self.real = 1000.0                                           # seconds that really passed
        self.original = (main_window.local_now, main_window.time, main_window.QMessageBox)
        main_window.local_now = lambda: self.wall
        main_window.time = types.SimpleNamespace(monotonic=lambda: self.real)
        main_window.QMessageBox = FakeMessageBox
        FakeMessageBox.shown = []

        self.worklog = WorkLog(self.folder, SETTINGS)
        self.window = main_window.MainWindow(SETTINGS, self.worklog, InvoiceLog(self.folder, SETTINGS),
                                             Checkpoint(self.folder, SETTINGS.lock_id), self.folder)
        self.window._timer.stop()
        self.window._mouse = FakeMouse()

    def tearDown(self):
        main_window.local_now, main_window.time, main_window.QMessageBox = self.original
        self.window.deleteLater()
        super().tearDown()

    def pass_time(self, wall_seconds, real_seconds=1.0):
        self.wall += timedelta(seconds=wall_seconds)
        self.real += real_seconds

    def tick(self, wall_seconds=1, real_seconds=1.0):
        self.pass_time(wall_seconds, real_seconds)
        self.window._on_tick()

    def recorded(self):
        return [(row[SESSION_START], row[SESSION_END], row[SESSION_TIME]) for row in self.worklog.rows]

    def test_an_untouched_clock_records_the_real_time(self):
        self.window._on_start_clicked()
        for _ in range(600):
            self.tick()
        self.window._on_stop_clicked()
        self.assertEqual(self.recorded(), [("09:00:00", "09:10:00", "00:10:00")])

    def test_a_clock_jump_seen_by_a_tick_adds_nothing(self):
        self.window._on_start_clicked()
        for _ in range(10):
            self.tick()
        self.tick(wall_seconds=29 * 60)
        self.window._on_stop_clicked()
        self.assertEqual(self.recorded(), [("09:00:00", "09:00:10", "00:00:10")])

    def test_a_clock_jump_right_before_stop_adds_nothing(self):
        self.window._on_start_clicked()
        for _ in range(10):
            self.tick()
        self.pass_time(wall_seconds=29 * 60, real_seconds=0.2)
        self.window._on_stop_clicked()
        self.assertEqual(self.recorded(), [("09:00:00", "09:00:10", "00:00:10")])

    def test_many_small_clock_steps_add_up_and_are_caught(self):
        self.window._on_start_clicked()
        for _ in range(600):
            self.tick(wall_seconds=5)
        self.window._on_stop_clicked()
        billed = sum(self.worklog._daily_seconds.values())
        self.assertLessEqual(billed, 600)

    def test_a_slow_quartz_is_not_mistaken_for_a_clock_change(self):
        self.window._on_start_clicked()
        for _ in range(3600):
            self.tick(real_seconds=1.0001)
        self.window._on_stop_clicked()
        self.assertEqual(self.recorded(), [("09:00:00", "10:00:00", "01:00:00")])

    def test_start_is_refused_while_the_clock_is_before_the_last_session(self):
        self.window._on_start_clicked()
        for _ in range(600):
            self.tick()
        self.window._on_stop_clicked()

        self.tick(wall_seconds=-3600)                               # stopped: the clock goes back an hour
        self.window._on_start_clicked()
        self.assertFalse(self.window.tracker.is_running)
        self.assertEqual(len(FakeMessageBox.shown), 1)

        self.tick(wall_seconds=3600)                                # corrected
        self.window._on_start_clicked()
        self.assertTrue(self.window.tracker.is_running)

    def test_a_clock_set_back_while_running_drops_the_overlapping_session(self):
        self.window._on_start_clicked()
        for _ in range(600):
            self.tick()
        self.tick(wall_seconds=-300)
        self.assertEqual(self.recorded(), [("09:00:00", "09:10:00", "00:10:00")])
        self.assertFalse(self.window.tracker.is_running)
        self.assertEqual(len(FakeMessageBox.shown), 1)


class MouseTest(unittest.TestCase):
    def test_only_a_real_movement_counts(self):
        self.assertFalse(is_real_move((100, 100), (102, 103)))      # sensor jitter
        self.assertTrue(is_real_move((100, 100), (105, 100)))
        self.assertFalse(is_real_move((100, 100), None))            # locked screen: position unknown
        self.assertFalse(is_real_move(None, (100, 100)))


if __name__ == "__main__":
    unittest.main()
