import json
import os
import sys
import threading
from collections.abc import Mapping
from typing import BinaryIO, Self


class Channel:
    """
    The adapter's half of the protocol: one JSON object per line on what was stdout.

    Each message is written whole and flushed under one lock, so lines from calls
    running at once never interleave.
    """

    @classmethod
    def take_stdout(cls) -> Self:
        """
        Take the process's stdout for the protocol, and point standard output at stderr.

        A stray print then becomes a diagnostic rather than a broken line.

        Returns:
            The channel, which writes to what stdout was, in binary mode.
        """
        sys.stdout.flush()
        stream = os.fdopen(os.dup(sys.stdout.fileno()), "wb")
        os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
        sys.stdout = sys.stderr
        return cls(stream)

    def __init__(self, stream: BinaryIO) -> None:
        self._stream = stream
        self._lock = threading.Lock()

    def write(self, message: Mapping[str, object]) -> None:
        """
        Write a message on a line of its own, in UTF-8 and ending in LF.

        Args:
            message: The message.
        """
        line = json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n"
        with self._lock:
            self._stream.write(line.encode())
            self._stream.flush()
