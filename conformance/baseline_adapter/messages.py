import base64
from typing import Literal, NotRequired, TypedDict

type Pairs = list[list[str]]
"""Names and values in order, a name repeated for each of its values."""

type LanguageErrorKind = Literal["cancellation", "timeout", "other"]
"""What ended a call that failed with an error of the language's own."""

type RefusalCode = Literal["unknown_command", "invalid_command", "adapter_error"]
"""Why the adapter didn't make a call, each a fault of the runner or the adapter."""


class Command(TypedDict):
    """The fields every command carries."""

    type: Literal["command"]
    id: int
    command: str


class BytesFields(TypedDict, total=False):
    """Bytes, as the UTF-8 text they encode, or else in base64."""

    text: str
    base64: str


class Body(BytesFields, total=False):
    """A request's body: whole bytes, a form's fields, or a stream the runner feeds."""

    form: Pairs
    multipart: Pairs
    stream: Literal[True]


class ConnectCommand(Command):
    """Opens a Backend, named by the command's ID."""

    options: dict[str, object]
    logging: NotRequired[str]
    sinks: NotRequired[dict[str, str]]


class CloseCommand(Command):
    """Closes a Backend."""

    backend: int


class CancelCommand(Command):
    """Fires the cancellation of a call under way, named by its command's ID."""

    commandId: int


class RequestCommand(Command):
    """Sends a request, named by the command's ID, and reads its response."""

    backend: int
    via: str
    method: str
    target: str
    headers: NotRequired[Pairs]
    body: NotRequired[Body]
    options: NotRequired[dict[str, object]]
    timeout: NotRequired[float]
    validate: NotRequired[bool]


class SseCommand(Command):
    """Sends a GET request, named by the command's ID, and iterates its events."""

    backend: int
    via: str
    target: str
    headers: NotRequired[Pairs]
    options: NotRequired[dict[str, object]]
    timeout: NotRequired[float]


class BodyChunkCommand(Command, BytesFields):
    """Feeds a chunk of a request's streamed body."""

    request: int


class BodyEndCommand(Command):
    """Ends a request's streamed body."""

    request: int


class WebSocketOpenCommand(Command):
    """Opens a WebSocket, named by the command's ID."""

    backend: int
    target: str
    headers: NotRequired[Pairs]


class WebSocketSendCommand(Command):
    """Sends a text message, or a binary one in base64."""

    socket: int
    text: NotRequired[str]
    binary: NotRequired[str]


class WebSocketCloseCommand(Command):
    """Starts a WebSocket's closing handshake."""

    socket: int
    code: NotRequired[int]
    reason: NotRequired[str]


class LanguageError(TypedDict):
    """An error of the language's own that ended a call."""

    kind: LanguageErrorKind
    name: str
    message: str


class Refusal(TypedDict):
    """Why the adapter didn't make the call a command asked for."""

    code: RefusalCode
    message: str


class Refused(Exception):
    """The adapter didn't make the call a command asked for, as its refusal says."""

    def __init__(self, code: RefusalCode, message: str) -> None:
        super().__init__(message)
        self.refusal = Refusal(code=code, message=message)


class CallFailed(Exception):
    """A call failed with an error of the language's own, of the kind it tells."""

    def __init__(self, kind: LanguageErrorKind, error: BaseException) -> None:
        super().__init__(kind)
        self.language_error = language_error(kind, error)


def language_error(kind: LanguageErrorKind, error: BaseException) -> LanguageError:
    """
    Describe an error of the language's own.

    Args:
        kind: What ended the call.
        error: The error.

    Returns:
        The error's kind, its type's name and its message.
    """
    return LanguageError(kind=kind, name=type(error).__name__, message=str(error))


def encode_bytes(data: bytes) -> BytesFields:
    """
    Carry bytes as text when they are UTF-8, and in base64 otherwise.

    Args:
        data: The bytes.

    Returns:
        The fields that carry them.
    """
    try:
        return {"text": data.decode()}
    except UnicodeDecodeError:
        return {"base64": base64.b64encode(data).decode("ascii")}


def decode_bytes(fields: BytesFields) -> bytes:
    """
    Read the bytes a command carries.

    Args:
        fields: The command's ``text`` or ``base64``.

    Returns:
        The bytes.
    """
    text = fields.get("text")
    if text is not None:
        return text.encode()
    return base64.b64decode(fields.get("base64", ""))
