import sys
from pathlib import Path

from PyQt5.QtCore import QLockFile, Qt
from PyQt5.QtGui import QFont, QIcon
from PyQt5.QtWidgets import QApplication, QMessageBox

from src import APP_NAME
from src.checkpoint import Checkpoint
from src.dialogs import SetupDialog
from src.integrity import PROGRAM_PATH, IntegrityError, build_fingerprint
from src.invoices import InvoiceLog
from src.main_window import MainWindow
from src.settings import load_settings
from src.style import STYLE_SHEET
from src.worklog import WorkLog, has_worklog_files

ICON_PATH = Path(__file__).resolve().parent / "assets" / "icon.ico"
INSTANCE_LOCK_NAME = ".workhour_running"     # next to the exe, only while it runs
DATA_FOLDER_NAME = "workhour_data"           # lock, worklogs, invoices, checkpoint


def main() -> int:
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setWindowIcon(QIcon(str(ICON_PATH)))
    app.setFont(QFont("Segoe UI", 9))
    app.setStyleSheet(STYLE_SHEET)

    folder = PROGRAM_PATH.parent
    build_fingerprint() # hash the exe once, while its path is certainly valid

    # Preventing two counters writing into the same worklog
    instance_lock = QLockFile(str(folder / INSTANCE_LOCK_NAME))
    if not instance_lock.tryLock(100):
        reason = ("The counter is already running from this folder."
                  if instance_lock.error() == QLockFile.LockFailedError
                  else f"The folder is not writable:\n{folder}")
        QMessageBox.warning(None, APP_NAME, reason)
        return 1

    folder = folder / DATA_FOLDER_NAME
    try:
        folder.mkdir(exist_ok=True)
    except OSError as error:
        QMessageBox.critical(None, APP_NAME, f"The data folder could not be created:\n{folder}\n\n{error}")
        return 1

    try:
        settings = load_settings(folder)
        if settings is None:
            if has_worklog_files(folder):
                raise IntegrityError(
                    "This folder contains worklog files, but the settings lock file is "
                    "missing. The worklog cannot be continued without its original settings."
                )
            settings = SetupDialog.run(folder)
            if settings is None:
                return 0 # setup cancelled, nothing was locked
        worklog = WorkLog(folder, settings)
        worklog.load()
        invoice_log = InvoiceLog(folder, settings)
        invoice_log.load()
        invoice_log.check_against(worklog)
    except IntegrityError as error:
        QMessageBox.critical(None, APP_NAME, str(error))
        return 1

    window = MainWindow(settings, worklog, invoice_log, Checkpoint(folder, settings.lock_id), folder)
    app.commitDataRequest.connect(window.stop_for_system_shutdown)
    app.aboutToQuit.connect(window.stop_for_system_shutdown)
    window.show()
    window.recover_interrupted_session()
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
