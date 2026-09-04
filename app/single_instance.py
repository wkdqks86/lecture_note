import ctypes
import getpass
import sys

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

# Per-user name so separate Windows accounts don't block each other.
SERVER_NAME = f"LectureNotes-single-instance-{getpass.getuser()}"

CONNECT_TIMEOUT_MS = 500

ASFW_ANY = -1


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
