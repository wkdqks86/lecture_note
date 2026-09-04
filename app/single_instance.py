import ctypes
import getpass
import sys

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

# Per-user name so separate Windows accounts don't block each other.
SERVER_NAME = f"LectureNotes-single-instance-{getpass.getuser()}"

CONNECT_TIMEOUT_MS = 500

ASFW_ANY = -1

# LectureNotes.iss checks this name (AppMutex) to see whether the app is running
# before it overwrites files. The installer can't just close our window instead:
# closeEvent hides to the tray rather than quitting, so the process would live on
# holding the exe open, and the install would fail halfway through.
RUNNING_MUTEX_NAME = "LectureNotes-running"


def _allow_foreground_handoff() -> None:
    """Windows refuses to let a background process raise its own window. The
    launching process has to hand over that right first, or the running
    instance only blinks in the taskbar instead of coming to the front."""
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.user32.AllowSetForegroundWindow(ASFW_ANY)
    except (AttributeError, OSError):
        pass


class SingleInstance(QObject):
    """Keeps only one app process alive.

    Running twice used to start two AutoRecordControllers, and both wrote the
    same `auto_<date>_<period>.wav` path with wave.open(..., "wb") -- the
    second open truncated the first one's file, so finished recordings came
    out empty or corrupt. A second launch now hands off to the running
    process and exits instead.
    """

    activate_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._server: QLocalServer | None = None
        self._mutex: int | None = None

    def _claim_running_mutex(self) -> None:
        """Held for the lifetime of the process purely so the installer can see
        that the app is up."""
        if sys.platform != "win32":
            return
        try:
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
            kernel32.CreateMutexW.restype = ctypes.c_void_p
            self._mutex = kernel32.CreateMutexW(None, False, RUNNING_MUTEX_NAME)
        except (AttributeError, OSError):
            self._mutex = None

    def _release_running_mutex(self) -> None:
        if self._mutex is None:
            return
        try:
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
            kernel32.CloseHandle(self._mutex)
        except (AttributeError, OSError):
            pass
        self._mutex = None

    def try_acquire(self) -> bool:
        """True if this process owns the app, False if an existing instance
        was told to show itself (this process should exit)."""
        socket = QLocalSocket()
        socket.connectToServer(SERVER_NAME)
        if socket.waitForConnected(CONNECT_TIMEOUT_MS):
            _allow_foreground_handoff()
            socket.write(b"activate")
            socket.flush()
            socket.waitForBytesWritten(CONNECT_TIMEOUT_MS)
            socket.disconnectFromServer()
            return False

        self._claim_running_mutex()

        # Nothing answered, so any leftover name belongs to a crashed run.
        QLocalServer.removeServer(SERVER_NAME)
        server = QLocalServer(self)
        if not server.listen(SERVER_NAME):
            # Can't listen, so future launches won't find us. Still better to
            # run than to refuse to start.
            return True

        server.newConnection.connect(self._on_new_connection)
        self._server = server
        return True

    def _on_new_connection(self):
        if self._server is None:
            return
        while self._server.hasPendingConnections():
            connection = self._server.nextPendingConnection()
            connection.disconnected.connect(connection.deleteLater)
            self.activate_requested.emit()

    def release(self):
        if self._server is not None:
            self._server.close()
            self._server = None
        QLocalServer.removeServer(SERVER_NAME)
        self._release_running_mutex()
