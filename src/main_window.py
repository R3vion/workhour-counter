"""The counter window: wires the tracker, the worklog and the checkpoint to the display."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (QCheckBox, QGridLayout, QHBoxLayout, QLabel, QMessageBox,
                             QPushButton, QVBoxLayout, QWidget)

from src import APP_NAME, VERSION
from src.checkpoint import Checkpoint
from src.dialogs import IntegrityDialog
from src.integrity import IS_RELEASE_BUILD, IntegrityError, short_fingerprint
from src.invoice_dialog import InvoicesDialog
from src.invoices import InvoiceLog
from src.mouse import MouseWatcher
from src.segment_display import SegmentDisplay
from src.settings import LockedSettings
from src.style import ACTIVE_ORANGE, INACTIVE_BLUE, MONEY_GREEN, TIME_WHITE
from src.timeutil import (DATE_TIME_FORMAT, format_duration, format_money, local_now,
                               start_of_day, wage)
from src.tracker import ClosedSession, SessionTracker
from src.worklog import WorkLog

WINDOW_SIZE = 500
BIG_DIGIT_HEIGHT = 66
SMALL_DIGIT_HEIGHT = 36
TICK_MILLISECONDS = 1000
CLOCK_TOLERANCE_SECONDS = 2
CLOCK_TOLERANCE_RATIO = 0.0005
FOOTER_SIDE_WIDTH = 170


class MainWindow(QWidget):
    def __init__(self, settings: LockedSettings, worklog: WorkLog, invoice_log: InvoiceLog,
                 checkpoint: Checkpoint, folder: Path):
        super().__init__()
        self.settings = settings
        self.worklog = worklog
        self.invoice_log = invoice_log
        self.checkpoint = checkpoint
        self.folder = folder
        self.tracker = SessionTracker(settings.max_idle)
        self._mouse = MouseWatcher()
        self._clock_reference = (local_now(), time.monotonic())    # when the two clocks agreed

        self._build_ui()
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.PreciseTimer)
        self._timer.timeout.connect(self._on_tick)
        self._timer.start(TICK_MILLISECONDS)
        self._refresh()

    def _build_ui(self) -> None:
        self.setWindowTitle(APP_NAME if IS_RELEASE_BUILD else f"{APP_NAME} [DEV BUILD]")
        self.setFixedSize(WINDOW_SIZE, WINDOW_SIZE)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 14, 18, 10)
        root.setSpacing(0)
        root.addLayout(self._build_live_counters())
        root.addSpacing(16)
        root.addLayout(self._build_buttons())
        root.addSpacing(16)
        root.addLayout(self._build_totals())
        root.addStretch()
        root.addLayout(self._build_footer())

    def _build_live_counters(self) -> QGridLayout:
        self.active_display = SegmentDisplay(ACTIVE_ORANGE, BIG_DIGIT_HEIGHT)
        self.inactive_display = SegmentDisplay(INACTIVE_BLUE, BIG_DIGIT_HEIGHT)
        self.inactive_caption = _caption("INACTIVE TIME", Qt.AlignHCenter)
        self.inactive_caption.setContentsMargins(0, 10, 0, 0)

        limit = QLabel(f"/ {format_duration(self.settings.max_idle_minutes * 60)}")
        limit.setObjectName("limit")
        limit.setFont(_pixel_font(13))
        limit.setContentsMargins(0, 0, 0, 10)

        grid = QGridLayout()
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(4)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(2, 1)
        grid.addWidget(_caption("ACTIVE TIME", Qt.AlignHCenter), 0, 0, 1, 3)
        grid.addWidget(self.active_display, 1, 1)
        grid.addWidget(self.inactive_caption, 2, 0, 1, 3)
        grid.addWidget(self.inactive_display, 3, 1)
        grid.addWidget(limit, 3, 2, Qt.AlignLeft | Qt.AlignBottom)
        return grid

    def _build_buttons(self) -> QHBoxLayout:
        self.start_button = QPushButton("START")
        self.start_button.setObjectName("start")
        self.start_button.clicked.connect(self._on_start_clicked)
        self.stop_button = QPushButton("STOP")
        self.stop_button.setObjectName("stop")
        self.stop_button.clicked.connect(self._on_stop_clicked)

        row = QHBoxLayout()
        row.addStretch()
        for button in (self.start_button, self.stop_button):
            button.setCursor(Qt.PointingHandCursor)
            row.addWidget(button)
            row.addSpacing(8)
        row.addStretch()
        return row

    def _build_totals(self) -> QGridLayout:
        """Three rows of (time | money): session, today, all time."""
        currency = self.settings.currency
        self.session_time = SegmentDisplay(TIME_WHITE, SMALL_DIGIT_HEIGHT, Qt.AlignLeft)
        self.session_wage = SegmentDisplay(MONEY_GREEN, SMALL_DIGIT_HEIGHT, Qt.AlignRight)
        self.daily_time = SegmentDisplay(TIME_WHITE, SMALL_DIGIT_HEIGHT, Qt.AlignLeft)
        self.daily_wage = SegmentDisplay(MONEY_GREEN, SMALL_DIGIT_HEIGHT, Qt.AlignRight)
        self.total_time = SegmentDisplay(TIME_WHITE, SMALL_DIGIT_HEIGHT, Qt.AlignLeft)
        self.total_wage = SegmentDisplay(MONEY_GREEN, SMALL_DIGIT_HEIGHT, Qt.AlignRight)
        rows = (
            ("SESSION DURATION", self.session_time, f"SESSION WAGE ({currency})", self.session_wage),
            ("DAILY TOTAL TIME", self.daily_time, f"DAILY WAGE ({currency})", self.daily_wage),
            ("TOTAL TIME", self.total_time, f"TOTAL WAGE ({currency})", self.total_wage),
        )

        grid = QGridLayout()
        grid.setHorizontalSpacing(0)
        grid.setVerticalSpacing(3)
        for spacer_column in (0, 2, 4):
            grid.setColumnStretch(spacer_column, 1)
        for index, (time_label, time_display, wage_label, wage_display) in enumerate(rows):
            time_caption = _caption(time_label)
            wage_caption = _caption(wage_label, Qt.AlignRight)
            if index > 0:
                time_caption.setContentsMargins(0, 8, 0, 0)
                wage_caption.setContentsMargins(0, 8, 0, 0)
            grid.addWidget(time_caption, index * 2, 1)
            grid.addWidget(wage_caption, index * 2, 3)
            grid.addWidget(time_display, index * 2 + 1, 1)
            grid.addWidget(wage_display, index * 2 + 1, 3)
        return grid

    def _build_footer(self) -> QHBoxLayout:
        """
        Bottom left: the build watermark (opens the integrity dialog).
        Bottom centre: INVOICES.
        Bottom right: always on top.
        """
        if IS_RELEASE_BUILD:
            self.build_button = QPushButton(f"v{VERSION}  ·  build {short_fingerprint()}")
            self.build_button.setObjectName("build")
        else:
            self.build_button = QPushButton("DEV BUILD  ·  not valid for billing")
            self.build_button.setObjectName("build_dev")
        self.build_button.setCursor(Qt.PointingHandCursor)
        self.build_button.setToolTip("Build fingerprint, locked settings and CSV verification")
        self.build_button.clicked.connect(self._on_build_clicked)

        always_on_top = QCheckBox("Always on top")
        always_on_top.setFont(_pixel_font(11))
        always_on_top.setLayoutDirection(Qt.RightToLeft)      # box after the text
        always_on_top.toggled.connect(self._set_always_on_top)

        invoices_button = QPushButton("INVOICES")
        invoices_button.setObjectName("invoices")
        invoices_button.setCursor(Qt.PointingHandCursor)
        invoices_button.clicked.connect(self._on_invoices_clicked)

        for side in (self.build_button, always_on_top):
            side.setFixedWidth(FOOTER_SIDE_WIDTH)

        row = QHBoxLayout()
        row.addWidget(self.build_button)
        row.addStretch()
        row.addWidget(invoices_button)
        row.addStretch()
        row.addWidget(always_on_top)
        return row

    # Clock -------------------------------------------------------------------------

    def _on_tick(self) -> None:
        now = local_now()
        self._save(self.tracker.tick(now, self._mouse.moved(), self._clock_changed(now)))
        if self._session_starts_in_the_past():
            return
        self.checkpoint.save_if_due(now, self.tracker, self.worklog.total_seconds)
        self._refresh(now)

    def _clock_changed(self, now) -> bool:
        """True if the system clock was moved.

        The monotonic clock cannot be set by the user. The wall clock must pass the
        same amount of time as it does, counted from the last moment they agreed.
        Counting from a fixed moment (not from the previous tick) matters: many
        small changes add up and are caught just like one big change.
        """
        monotonic = time.monotonic()
        reference_now, reference_monotonic = self._clock_reference
        real_elapsed = monotonic - reference_monotonic
        wall_elapsed = (now - reference_now).total_seconds()
        allowed = CLOCK_TOLERANCE_SECONDS + CLOCK_TOLERANCE_RATIO * real_elapsed
        if abs(wall_elapsed - real_elapsed) <= allowed:
            return False
        self._clock_reference = (now, monotonic)       # agree again from here
        return True

    def _session_starts_in_the_past(self) -> bool:
        """If the clock was set back, the open session would overlap recorded work: drop it."""
        start = self.tracker.session_start
        if start is None or self.worklog.is_after_last_session(start):
            return False
        self.tracker.cancel()
        self.checkpoint.clear()
        self._refresh()
        self._warn_about_clock()
        return True

    def _warn_about_clock(self) -> None:
        QMessageBox.warning(
            self, APP_NAME,
            "The system clock shows an earlier time than the end of the last recorded "
            f"session ({self.worklog.last_end.strftime(DATE_TIME_FORMAT)}).\n\n"
            "The counter was not started. Correct the system clock, then press Start.",
        )

    def _refresh(self, now=None) -> None:
        now = now or local_now()
        tracker = self.tracker
        session = tracker.session_seconds(now)
        daily = (self.worklog.seconds_on(now.date())
                 + tracker.session_seconds(now, since=start_of_day(now.date())))
        total = self.worklog.total_seconds + session

        self.active_display.set_text(format_duration(tracker.active_seconds()))
        self.inactive_display.set_text(format_duration(tracker.inactive_seconds(now)))
        self.session_time.set_text(format_duration(session))
        self.session_wage.set_text(self._money(session))
        self.daily_time.set_text(format_duration(daily))
        self.daily_wage.set_text(self._money(daily))
        self.total_time.set_text(format_duration(total))
        self.total_wage.set_text(self._money(total))

        self.start_button.setEnabled(not tracker.is_running)
        self.stop_button.setEnabled(tracker.is_running)
        self.inactive_caption.setText("INACTIVE TIME  ·  PAUSED, MOVE THE MOUSE TO CONTINUE" if tracker.is_paused else "INACTIVE TIME")

    def _money(self, seconds: int) -> str:
        currency = self.settings.currency
        return format_money(wage(seconds, self.settings.hourly_rate, currency), currency, grouped=True)

    # Start / Stop / saving ---------------------------------------------------------

    def _on_start_clicked(self) -> None:
        now = local_now()
        if not self.worklog.is_after_last_session(now):
            self._warn_about_clock()
            return
        self.tracker.start(now)
        self._refresh()

    def _on_stop_clicked(self) -> None:
        self._stop(confirmed_by_user=True)

    def _stop(self, confirmed_by_user: bool) -> None:
        now = local_now()
        if self._clock_changed(now):
            confirmed_by_user = False
        self._save(self.tracker.stop(now, confirmed_by_user))
        self._refresh()

    def _save(self, session: Optional[ClosedSession]) -> None:
        if session is None:
            return
        try:
            self.worklog.record(session, self.invoice_log.invoiced_until, self._ask_to_retry)
        except (OSError, IntegrityError) as error:
            QMessageBox.critical(self, APP_NAME, f"The session {_describe(session)} was NOT saved.\n\n{error}")
            return
        self.checkpoint.clear()

    def _ask_to_retry(self, error: OSError) -> bool:
        answer = QMessageBox.warning(
            self, APP_NAME,
            f"The worklog could not be written:\n{error}\n\n"
            "If the CSV file is open in another program (for example Excel), close it and press Retry.",
            QMessageBox.Retry | QMessageBox.Cancel, QMessageBox.Retry,
        )
        return answer == QMessageBox.Retry

    def recover_interrupted_session(self) -> None:
        """Called once at start: save the session an unexpected exit left behind."""
        try:
            session = self.checkpoint.load_interrupted_session(self.worklog.total_seconds)
        except IntegrityError as error:
            QMessageBox.warning(self, APP_NAME, str(error))
            self.checkpoint.clear()
            return
        if session is None or not self.worklog.is_after_last_session(session.start):
            self.checkpoint.clear()
            return
        self._save(session)
        self._refresh()
        QMessageBox.information(
            self, APP_NAME,
            "The previous run ended unexpectedly (crash or power loss).\n"
            f"Its session was recovered up to the last checkpoint and saved:\n\n{_describe(session)}",
        )

    # Window ------------------------------------------------------------------------

    def _set_always_on_top(self, enabled: bool) -> None:
        self.setWindowFlag(Qt.WindowStaysOnTopHint, enabled)
        self.show()            # changing window flags hides the window

    def _on_invoices_clicked(self) -> None:
        InvoicesDialog(self.invoice_log, self.worklog, self.tracker, self.folder, self).exec_()

    def _on_build_clicked(self) -> None:
        IntegrityDialog(self.settings, self.folder, self).exec_()

    def closeEvent(self, event) -> None:
        """Before closing, make sure Stop ran and the last session is saved."""
        if not self.tracker.is_running:
            event.accept()
            return
        box = QMessageBox(QMessageBox.Question, APP_NAME,
                          "The counter is still running.\n\n"
                          "Stop it and save the current session before exiting?", parent=self)
        stop_and_exit = box.addButton("Stop && Exit", QMessageBox.AcceptRole)
        box.addButton(QMessageBox.Cancel)
        box.exec_()
        if box.clickedButton() is stop_and_exit:
            self._stop(confirmed_by_user=True)
            event.accept()
        else:
            event.ignore()

    def stop_for_system_shutdown(self, *_) -> None:
        """Windows is shutting down or logging off: save without asking."""
        if self.tracker.is_running:
            self._stop(confirmed_by_user=False)


def _caption(text: str, alignment=Qt.AlignLeft) -> QLabel:
    label = QLabel(text)
    label.setObjectName("caption")
    label.setAlignment(alignment)
    font = _pixel_font(10)
    font.setWeight(QFont.DemiBold)
    font.setLetterSpacing(QFont.AbsoluteSpacing, 1.4)
    label.setFont(font)
    return label


def _pixel_font(pixels: int) -> QFont:
    font = QFont("Segoe UI")
    font.setPixelSize(pixels)
    return font


def _describe(session: ClosedSession) -> str:
    return (f"{session.start.strftime(DATE_TIME_FORMAT)} - {session.end.strftime('%H:%M:%S')} "
            f"({format_duration(session.seconds)})")
