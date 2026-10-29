import threading
import time
from pathlib import Path
from types import TracebackType
from typing import Self


class Trace:
    """
    The trace log of one case, or of one piece of the runner's own work.

    Each record is a line: the seconds since the trace began, its source, and its text,
    such as a line an adapter wrote or a process's start and exit. A record is written
    and flushed before :meth:`record` returns, so the trace survives the runner being
    killed, and records from several threads never interleave.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._file = path.open("a", encoding="utf-8", newline="\n")
        self._lock = threading.Lock()
        self._start = time.monotonic()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def record(self, source: str, text: str) -> None:
        """
        Write a record, one line for each line of its text.

        Args:
            source: Where it comes from, such as ``adapter 1 stdout``.
            text: What happened.
        """
        elapsed = time.monotonic() - self._start
        lines = text.splitlines() or [""]
        with self._lock:
            if self._file.closed:
                return
            for line in lines:
                self._file.write(f"{elapsed:9.3f} {source}: {line}\n")
            self._file.flush()

    def close(self) -> None:
        """Close the file; a record written after it is dropped."""
        with self._lock:
            self._file.close()
