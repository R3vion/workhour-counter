"""The session rules, step by step on a 30-minute idle limit."""

import unittest
from datetime import datetime, timedelta, timezone

from src.tracker import ClosedSession, SessionTracker

NINE = datetime(2026, 11, 16, 9, 0, 0, tzinfo=timezone.utc)


def at(minutes: int, seconds: int = 0) -> datetime:
    return NINE + timedelta(minutes=minutes, seconds=seconds)


class SessionTrackerTest(unittest.TestCase):
    def setUp(self):
        self.tracker = SessionTracker(max_idle=timedelta(minutes=30))
        self.tracker.start(at(0))

    def test_active_time_freezes_while_idle_and_catches_up_on_movement(self):
        self.tracker.tick(at(10), mouse_moved=True)
        self.tracker.tick(at(15), mouse_moved=False)
        self.assertEqual(self.tracker.active_seconds(), 10 * 60)
        self.assertEqual(self.tracker.inactive_seconds(at(15)), 5 * 60)
        self.assertEqual(self.tracker.session_seconds(at(15)), 15 * 60)

        self.tracker.tick(at(20), mouse_moved=True)
        self.assertEqual(self.tracker.active_seconds(), 20 * 60)
        self.assertEqual(self.tracker.inactive_seconds(at(20)), 0)

    def test_idle_limit_closes_the_session_at_the_last_activity(self):
        self.tracker.tick(at(20), mouse_moved=True)
        self.assertIsNone(self.tracker.tick(at(50), mouse_moved=False))

        closed = self.tracker.tick(at(50, 1), mouse_moved=False)
        self.assertEqual(closed, ClosedSession(at(0), at(20)))
        self.assertTrue(self.tracker.is_paused)
        self.assertEqual(self.tracker.session_seconds(at(51)), 0)
        self.assertEqual(self.tracker.active_seconds(), 0)
        self.assertEqual(self.tracker.inactive_seconds(at(51)), 31 * 60)

    def test_mouse_after_a_pause_starts_a_new_session(self):
        self.tracker.tick(at(10), mouse_moved=True)
        self.tracker.tick(at(41), mouse_moved=False)
        self.tracker.tick(at(180), mouse_moved=True)
        self.assertFalse(self.tracker.is_paused)
        self.assertEqual(self.tracker.session_start, at(180))
        self.assertEqual(self.tracker.inactive_seconds(at(180)), 0)

    def test_movement_after_a_long_gap_does_not_confirm_the_gap(self):
        """E.g. the computer slept: the first tick after waking sees both."""
        self.tracker.tick(at(10), mouse_moved=True)
        closed = self.tracker.tick(at(130), mouse_moved=True)
        self.assertEqual(closed, ClosedSession(at(0), at(10)))
        self.assertEqual(self.tracker.session_start, at(130))

    def test_a_changed_system_clock_never_adds_time(self):
        self.tracker.tick(at(10), mouse_moved=True)
        closed = self.tracker.tick(at(39), mouse_moved=True, clock_changed=True)
        self.assertEqual(closed, ClosedSession(at(0), at(10)))
        self.assertEqual(self.tracker.session_start, at(39))

    def test_pressing_stop_confirms_a_short_idle_stretch(self):
        self.tracker.tick(at(10), mouse_moved=True)
        self.assertEqual(self.tracker.stop(at(20)), ClosedSession(at(0), at(20)))
        self.assertFalse(self.tracker.is_running)

    def test_automatic_stop_ends_at_the_last_movement(self):
        self.tracker.tick(at(10), mouse_moved=True)
        closed = self.tracker.stop(at(20), confirmed_by_user=False)
        self.assertEqual(closed, ClosedSession(at(0), at(10)))

    def test_stop_while_paused_saves_nothing_more(self):
        self.tracker.tick(at(10), mouse_moved=True)
        self.tracker.tick(at(41), mouse_moved=False)
        self.assertIsNone(self.tracker.stop(at(50)))


if __name__ == "__main__":
    unittest.main()
