import codecs
import re
from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True)
class ServerSentEvent:
    """An event an event stream dispatched."""

    event_type: str
    """The event's type, which is ``message`` where the stream named none."""
    data: str
    """The event's data, its lines joined by LF."""
    event_id: str | None
    """The stream's last event ID as it dispatched the event, or None if it set none."""


# Not httpx2's EventSource, which dispatches a block without data that the HTML
# standard discards.
class EventStreamParser:
    """
    Parses an event stream as the HTML standard interprets one.

    The bytes are decoded as UTF-8, a leading byte order mark dropped, and lines end
    in CRLF, CR or LF. A blank line dispatches the event its lines gave, unless it
    has no data; its type is ``message`` unless an ``event`` field named one, and
    its ID is the last ``id`` field's value, which carries on to later events.
    """

    def __init__(self) -> None:
        self._decoder = codecs.getincrementaldecoder("utf-8-sig")(errors="replace")
        self._pending = ""
        self._after_cr = False
        self._data: list[str] = []
        self._event_type = ""
        self._last_event_id: str | None = None

    def _line(self, line: str) -> ServerSentEvent | None:
        if not line:
            return self._dispatch()
        if line.startswith(":"):
            return None
        name, _, value = line.partition(":")
        value = value.removeprefix(" ")
        if name == "event":
            self._event_type = value
        elif name == "data":
            self._data.append(value)
        elif name == "id" and "\0" not in value:
            self._last_event_id = value
        # retry sets only the reconnection time, which no event carries.
        return None

    def _dispatch(self) -> ServerSentEvent | None:
        data, event_type = self._data, self._event_type
        self._data, self._event_type = [], ""
        if not data:
            return None
        joined = "\n".join(data)
        return ServerSentEvent(event_type or "message", joined, self._last_event_id)

    def feed(self, chunk: bytes) -> list[ServerSentEvent]:
        """
        Parse the stream's next bytes.

        Its end needs no call, since the standard discards an event the stream
        leaves undispatched.

        Args:
            chunk: The bytes, which may end within a line or a character.

        Returns:
            The events the bytes dispatched, in order.
        """
        text = self._decoder.decode(chunk)
        if not text:
            return []
        if self._after_cr and text.startswith("\n"):
            text = text[1:]
        buffer = self._pending + text
        events: list[ServerSentEvent] = []
        start = 0
        for end in _LINE_END.finditer(buffer):
            event = self._line(buffer[start : end.start()])
            if event is not None:
                events.append(event)
            start = end.end()
        self._pending = buffer[start:]
        # A CR the bytes end with may be the first half of a CRLF.
        self._after_cr = buffer.endswith("\r")
        return events


_LINE_END: Final = re.compile(r"\r\n|\r|\n")
