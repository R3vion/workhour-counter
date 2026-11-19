"""The first-run setup dialog and the integrity (build info + CSV verification) dialog."""

from __future__ import annotations

import csv
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Optional

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog,
                             QFormLayout, QLabel, QMessageBox, QSpinBox, QVBoxLayout)

from src import APP_NAME, VERSION
from src.integrity import IS_RELEASE_BUILD, IntegrityError, build_fingerprint
from src.settings import LockedSettings, create_settings
from src.timeutil import CURRENCIES, DATE_TIME_FORMAT, decimals_for, format_money
from src.invoices import verify_csv


class SetupDialog(QDialog):
    """First run only: choose currency, hourly rate and idle limit, then lock them for good."""

    def __init__(self, folder: Path):
        super().__init__()
        self.folder = folder
        self.settings: Optional[LockedSettings] = None
        self.setWindowTitle(f"{APP_NAME} - first-time setup")
        self.setMinimumWidth(420)

        intro = QLabel(
            "These settings are locked permanently for this copy of the counter.\n"
            "To bill a different rate later, start again with a fresh copy of the "
            "app in a new folder."
        )
        intro.setWordWrap(True)

        self.currency = QComboBox()
        self.currency.addItems(CURRENCIES)
        self.rate = QDoubleSpinBox()
        self.rate.setRange(0, 1_000_000)
        self.idle_limit = QSpinBox()
        self.idle_limit.setRange(1, 240)
        self.idle_limit.setValue(30)
        self.idle_limit.setSuffix(" minutes")
        self.currency.currentTextChanged.connect(self._on_currency_changed)
        self._on_currency_changed(self.currency.currentText())

        form = QFormLayout()
        form.addRow("Currency", self.currency)
        form.addRow("Hourly rate", self.rate)
        form.addRow("Max inactive time", self.idle_limit)

        buttons = QDialogButtonBox()
        buttons.addButton("Lock settings", QDialogButtonBox.AcceptRole)
        buttons.addButton(QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._lock)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addSpacing(8)
        layout.addLayout(form)
        layout.addSpacing(8)
        layout.addWidget(buttons)

    @classmethod
    def run(cls, folder: Path) -> Optional[LockedSettings]:
        """Show the dialog; return the locked settings, or None if the user cancelled."""
        dialog = cls(folder)
        dialog.exec_()
        return dialog.settings

    def _on_currency_changed(self, currency: str) -> None:
        self.rate.setDecimals(decimals_for(currency))
        self.rate.setSingleStep(100 if currency == "HUF" else 1)
        self.rate.setSuffix(f" {currency} / hour")

    def _lock(self) -> None:
        currency = self.currency.currentText()
        unit = Decimal(1).scaleb(-decimals_for(currency))
        rate = Decimal(str(self.rate.value())).quantize(unit)
        if rate <= 0:
            QMessageBox.warning(self, APP_NAME, "Please enter an hourly rate greater than zero.")
            return

        question = (
            "Lock these settings permanently?\n\n"
            f"Hourly rate:  {format_money(rate, currency, grouped=True)} {currency}\n"
            f"Max inactive time:  {self.idle_limit.value()} minutes\n\n"
            "They cannot be changed later."
        )
        if QMessageBox.question(self, APP_NAME, question) != QMessageBox.Yes:
            return
        try:
            self.settings = create_settings(self.folder, rate, currency, self.idle_limit.value())
        except OSError as error:
            QMessageBox.critical(self, APP_NAME, f"The settings could not be saved in\n{self.folder}\n\n{error}")
            return
        self.accept()


class IntegrityDialog(QDialog):
    """Shows what this exe is and what it is locked to, and verifies CSV files."""

    def __init__(self, settings: LockedSettings, folder: Path, parent=None):
        super().__init__(parent)
        self.folder = folder
        self.setWindowTitle(f"{APP_NAME} - integrity")

        if IS_RELEASE_BUILD:
            fingerprint = QLabel(build_fingerprint())
            fingerprint.setFont(QFont("Consolas", 9))
        else:
            fingerprint = QLabel("DEV - running from source, not valid for billing")
        fingerprint.setTextInteractionFlags(Qt.TextSelectableByMouse)

        currency = settings.currency
        created = datetime.fromisoformat(settings.created).strftime(DATE_TIME_FORMAT)
        form = QFormLayout()
        form.addRow("Version", QLabel(VERSION))
        form.addRow("Build fingerprint (SHA-256)", fingerprint)
        form.addRow("Hourly rate", QLabel(f"{format_money(settings.hourly_rate, currency, True)} {currency} / hour"))
        form.addRow("Max inactive time", QLabel(f"{settings.max_idle_minutes} minutes"))
        form.addRow("Settings lock id", QLabel(settings.lock_id))
        form.addRow("Locked since", QLabel(created))
        form.addRow("Data folder", QLabel(str(folder)))

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        verify_button = buttons.addButton("Verify CSV...", QDialogButtonBox.ActionRole)
        verify_button.clicked.connect(self._verify)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addSpacing(8)
        layout.addWidget(buttons)

    def _verify(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Verify a worklog or the invoice log",
                                              str(self.folder), "CSV (*.csv)")
        if not path:
            return
        try:
            summary = verify_csv(Path(path))
        except IntegrityError as error:
            QMessageBox.critical(self, "Verification failed", str(error))
        except (OSError, ValueError, IndexError, csv.Error) as error:     # unreadable, or not a CSV at all
            QMessageBox.critical(self, "Verification failed", f"The file could not be read:\n{error}")
        else:
            QMessageBox.information(self, "Verification passed", summary)
