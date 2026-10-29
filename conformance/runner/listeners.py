import selectors
import socket
import threading
from types import TracebackType
from typing import Final, Self

HOST: Final = "127.0.0.1"

# How often the listener's thread looks up from waiting, to see whether it should stop.
WAKE_SECONDS: Final = 0.05

# The listener's thread stops at once once asked; a hang guard.
STOP_GUARD_SECONDS: Final = 10.0


class ListenerStuck(Exception):
    """The listener's thread didn't stop within its hang guard."""


class RecordingListener:
    """
    A loopback listener that records each connection and closes it at once.

    It stands where nothing should connect, such as a proxy that the environment
    names and a client must ignore, so a client that connects fails fast rather than
    waiting on an answer that never comes.
    """

    def __init__(self) -> None:
        self._socket = socket.create_server((HOST, 0))
        self._socket.setblocking(False)
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._peers: list[tuple[str, int]] = []
        self._thread = threading.Thread(
            target=self._accept, name="recording listener", daemon=True
        )
        self._thread.start()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    @property
    def url(self) -> str:
        """The listener's address as an HTTP URL, as a proxy is named."""
        port: int = self._socket.getsockname()[1]
        return f"http://{HOST}:{port}"

    def _accept(self) -> None:
        with selectors.DefaultSelector() as selector:
            selector.register(self._socket, selectors.EVENT_READ)
            while not self._stop.is_set():
                if not selector.select(WAKE_SECONDS):
                    continue
                try:
                    connection, peer = self._socket.accept()
                except BlockingIOError:
                    continue
                connection.close()
                with self._lock:
                    self._peers.append((peer[0], peer[1]))

    def connections(self) -> list[tuple[str, int]]:
        """
        Take the connections recorded so far.

        Returns:
            Each connection's peer address, in the order they came.
        """
        with self._lock:
            return list(self._peers)

    def close(self) -> None:
        """
        Stop accepting and close the listener.

        Raises:
            ListenerStuck: The listener's thread didn't stop.
        """
        self._stop.set()
        self._thread.join(STOP_GUARD_SECONDS)
        self._socket.close()
        if self._thread.is_alive():
            raise ListenerStuck("the recording listener's thread didn't stop")
