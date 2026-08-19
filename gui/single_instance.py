"""One-instance coordination with argument forwarding over a local Qt socket."""

import hashlib
import json
import os
import tempfile
import time

from PySide6.QtCore import QLockFile, QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket


def _instance_identity(scope=None):
    scope = scope or os.path.expanduser("~")
    normalized = os.path.normcase(os.path.abspath(scope))
    return hashlib.sha256(normalized.encode("utf-8", errors="surrogatepass")).hexdigest()[:20]


class SingleInstance(QObject):
    message_received = Signal(object)

    def __init__(self, scope=None, parent=None):
        super().__init__(parent)
        identity = _instance_identity(scope)
        self.server_name = f"ODeR-{identity}"
        self.lock_path = os.path.join(tempfile.gettempdir(), f"{self.server_name}.lock")
        self.lock = QLockFile(self.lock_path)
        self.server = QLocalServer(self)
        self.server.newConnection.connect(self._accept_connections)
        self._buffers = {}
        self._pending_messages = []
        self._ready = False
        self.is_primary = False

    def acquire(self):
        if not self.lock.tryLock(0):
            return False
        QLocalServer.removeServer(self.server_name)
        if not self.server.listen(self.server_name):
            self.lock.unlock()
            return False
        self.is_primary = True
        return True

    def forward(self, arguments=None, cwd=None, attempts=12):
        payload = json.dumps({
            "arguments": [str(value) for value in (arguments or [])],
            "cwd": str(cwd or os.getcwd()),
        }, ensure_ascii=False).encode("utf-8") + b"\n"
        for _attempt in range(max(1, attempts)):
            socket = QLocalSocket()
            socket.connectToServer(self.server_name)
            if socket.waitForConnected(250):
                socket.write(payload)
                if socket.waitForBytesWritten(1000):
                    socket.disconnectFromServer()
                    socket.waitForDisconnected(250)
                    return True
            socket.abort()
            time.sleep(0.1)
        return False

    def set_ready(self):
        self._ready = True
        pending = list(self._pending_messages)
        self._pending_messages.clear()
        return pending

    def _accept_connections(self):
        while self.server.hasPendingConnections():
            socket = self.server.nextPendingConnection()
            self._buffers[socket] = bytearray()
            socket.readyRead.connect(lambda s=socket: self._consume(s))
            socket.disconnected.connect(lambda s=socket: self._finish_socket(s))
            if socket.bytesAvailable():
                self._consume(socket)

    def _consume(self, socket):
        buffer = self._buffers.setdefault(socket, bytearray())
        buffer.extend(bytes(socket.readAll()))
        while b"\n" in buffer:
            raw, _, remaining = buffer.partition(b"\n")
            self._buffers[socket] = buffer = bytearray(remaining)
            self._dispatch(raw, socket)

    def _dispatch(self, raw, socket):
        try:
            payload = json.loads(raw.decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("message is not an object")
            arguments = payload.get("arguments")
            if not isinstance(arguments, list) or not all(isinstance(value, str) for value in arguments):
                raise ValueError("invalid arguments")
            if not isinstance(payload.get("cwd"), str):
                raise ValueError("invalid working directory")
        except (UnicodeDecodeError, ValueError, json.JSONDecodeError):
            socket.write(b"error\n")
            socket.flush()
            return
        if self._ready:
            self.message_received.emit(payload)
        else:
            self._pending_messages.append(payload)
        socket.write(b"ok\n")
        socket.flush()

    def _finish_socket(self, socket):
        if socket.bytesAvailable():
            self._consume(socket)
        self._buffers.pop(socket, None)
        socket.deleteLater()

    def close(self):
        if self.server.isListening():
            self.server.close()
            QLocalServer.removeServer(self.server_name)
        if self.is_primary:
            self.lock.unlock()
            self.is_primary = False
