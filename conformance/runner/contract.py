from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from functools import cache
from typing import Any, Final, cast

from runner.repository import REPOSITORY
from runner.schemas import parse_json, pointer_token, read_document, validator

PROTOCOL: Final = REPOSITORY / "protocol"
OPENAPI_FILE_NAME: Final = "openapi.yaml"
REGISTRY_FILE_NAME: Final = "registry.yaml"

PROTOCOL_VERSION: Final = 1
"""The protocol version the runner's raw client and fake server speak."""

REJECTED_HEADER: Final = "X-PipeAPI-Rejected"
"""The rejection marker, which the document's ``components/headers`` holds by name."""
CONTENT_TYPE_HEADER: Final = "Content-Type"

# The fields of a path item that hold an operation, in OpenAPI 3.2.
OPERATION_METHODS: Final = (
    "get",
    "put",
    "post",
    "delete",
    "options",
    "head",
    "patch",
    "trace",
    "query",
)
# The key that makes a media type a stream, in OpenAPI 3.2.
ITEM_SCHEMA: Final = "itemSchema"
JSON_LINES: Final = "application/jsonl"
# What ends each line of a JSON Lines stream, which the spec allows no CR before.
LINE_END: Final = b"\n"
# How much of a body that isn't JSON a violation quotes.
QUOTED_BYTES: Final = 200

type HeaderLines = Sequence[tuple[str, str]]
"""Header lines in the order they came, repeats included: each name with its value."""


class ContractViolation(AssertionError):
    """
    What a server sent doesn't meet its protocol version's OpenAPI document.

    It is an assertion's failure, so a case it ends fails as the case's own failure.
    """


@dataclass(frozen=True)
class Operation:
    """One operation of the document, which its ``operationId`` names."""

    id: str
    method: str
    """Its method, in upper case."""
    path: str
    pointer: str
    """A JSON pointer to it in the document."""


@dataclass(frozen=True)
class ResponseShape:
    """What the document gives one response of an operation, by its status."""

    operation: Operation
    status: int
    pointer: str
    """A JSON pointer to the response object, its reference followed."""
    media_type: str | None
    """The media type the response carries, or None when the document gives none."""
    media_pointer: str | None
    """A JSON pointer to that media type's object, its reference followed, or None."""
    streamed: bool
    """Whether that media type is a stream, whose items an item schema describes."""


class Contract:
    """
    One protocol version's machine-readable contract, as ``protocol/v<n>/`` holds it.

    It reads the version's OpenAPI document and registry, and checks what a server
    sends against the document, driven by the document rather than by route: the
    status must be one the operation lists, each header its response object defines
    must meet its definition, and the body, or each line of a stream, must meet the
    schema of the media type it carries. A schema's references resolve through
    :func:`runner.schemas.validator`.
    """

    def __init__(self, version: int) -> None:
        self.version = version
        directory = PROTOCOL / f"v{version}"
        self.document_path = directory / OPENAPI_FILE_NAME
        """The OpenAPI document's file."""
        self.document: Any = read_document(self.document_path)
        self.registry: Any = read_document(directory / REGISTRY_FILE_NAME)
        """What the registry holds, such as its constants and rejections."""
        self._operations = {
            operation.id: operation for operation in self._find_operations()
        }

    @property
    def operations(self) -> tuple[Operation, ...]:
        """Every operation of the document, in its order."""
        return tuple(self._operations.values())

    def _find_operations(self) -> Iterator[Operation]:
        for path, item in self.document["paths"].items():
            for method in OPERATION_METHODS:
                if method in item:
                    pointer = f"/paths/{pointer_token(path)}/{method}"
                    yield Operation(
                        item[method]["operationId"], method.upper(), path, pointer
                    )

    def _at(self, pointer: str) -> Any:
        node = self.document
        for segment in pointer.split("/")[1:]:
            key = segment.replace("~1", "/").replace("~0", "~")
            if isinstance(node, list):
                node = cast("list[Any]", node)[int(key)]
            else:
                node = cast("dict[str, Any]", node)[key]
        return node

    def _follow(self, pointer: str) -> tuple[str, Any]:
        # An OpenAPI reference object, such as a response's, followed to its target.
        seen = {pointer}
        while (reference := _reference(self._at(pointer))) is not None:
            if not reference.startswith("#"):
                message = f"{self._where(pointer)} refers outside the document"
                raise ValueError(message)
            pointer = reference.removeprefix("#")
            if pointer in seen:
                raise ValueError(f"{self._where(pointer)} refers to itself")
            seen.add(pointer)
        return pointer, self._at(pointer)

    def _schema_pointer(self, pointer: str) -> str:
        # A schema that is only a reference is named by what it refers to, such as the
        # hello schema, which validates the same. A cycle is left to the validator.
        seen = {pointer}
        while True:
            node = self._at(pointer)
            reference = _reference(node)
            if reference is None or len(node) > 1 or not reference.startswith("#"):
                return pointer
            target = reference.removeprefix("#")
            if target in seen:
                return pointer
            seen.add(target)
            pointer = target

    def _where(self, pointer: str) -> str:
        document = self.document_path.relative_to(REPOSITORY).as_posix()
        return f"{document}#{pointer}"

    def _schema_problem(self, subject: str, pointer: str, instance: Any) -> str | None:
        pointer = self._schema_pointer(pointer)
        errors = [
            f"    {error.json_path}: {error.message}"
            for error in validator(self.document_path, pointer).iter_errors(instance)
        ]
        if not errors:
            return None
        return f"{subject}, against #{pointer}:\n" + "\n".join(errors)

    def _header_problems(
        self, pointer: str, response: Mapping[str, Any], headers: HeaderLines
    ) -> list[str]:
        problems: list[str] = []
        for name in response.get("headers", {}):
            header_pointer, header = self._follow(
                f"{pointer}/headers/{pointer_token(name)}"
            )
            value = field_value(headers, name)
            if value is None:
                if header.get("required", False):
                    problem = f"the header {name} is missing, which #{header_pointer}"
                    problems.append(f"{problem} requires")
                continue
            if "schema" in header:
                problem = self._schema_problem(
                    f"the header {name}", f"{header_pointer}/schema", value
                )
                if problem is not None:
                    problems.append(problem)
        return problems

    def _media_type(
        self, pointer: str, response: Mapping[str, Any], headers: HeaderLines
    ) -> tuple[str | None, str | None]:
        # The media type the response carries, or None with the problem.
        content: Mapping[str, Any] = response.get("content", {})
        if not content:
            return None, None
        listed = ", ".join(content)
        given = field_value(headers, CONTENT_TYPE_HEADER)
        if given is None:
            return None, f"it has no {CONTENT_TYPE_HEADER}; #{pointer} gives {listed}"
        media_type = given.split(";")[0].strip().lower()
        for key in content:
            if key.lower() == media_type:
                return key, None
        return None, f"its {CONTENT_TYPE_HEADER} {given} isn't in #{pointer}: {listed}"

    def _violation(
        self, operation: Operation, status: int, problems: Sequence[str], what: str
    ) -> ContractViolation:
        document = self.document_path.relative_to(REPOSITORY).as_posix()
        lines = "\n".join(f"  {problem}" for problem in problems)
        return ContractViolation(
            f"the {operation.id} operation's {status} {what} doesn't meet "
            f"{document}:\n{lines}"
        )

    def operation(self, operation_id: str) -> Operation:
        """
        Find an operation by its ``operationId``.

        Args:
            operation_id: The ID.

        Returns:
            The operation.

        Raises:
            ValueError: The document holds no operation of that ID.
        """
        if operation_id not in self._operations:
            raise ValueError(f"{self._where('/paths')} holds no {operation_id}")
        return self._operations[operation_id]

    def constant(self, name: str) -> str:
        """
        Read one of the registry's constants.

        Args:
            name: Its name, such as ``host``.

        Returns:
            Its value.
        """
        value: str = self.registry["constants"][name]["value"]
        return value

    def rejection_status(self, code: str) -> int | None:
        """
        Find the status the registry gives a rejection.

        Args:
            code: The rejection's code, such as ``draining``.

        Returns:
            The status, or None for a code the registry doesn't hold.
        """
        rejection = self.registry["rejections"].get(code)
        if rejection is None:
            return None
        status: int = rejection["status"]
        return status

    def header_name(self, parameter: str) -> str:
        """
        Find the name of a request header the document's parameters define.

        Args:
            parameter: The parameter's key in ``components/parameters``, such as
                ``nonce``.

        Returns:
            The header's name, such as ``X-PipeAPI-Nonce``.

        Raises:
            ValueError: The parameter isn't a header.
        """
        pointer = f"/components/parameters/{pointer_token(parameter)}"
        definition = self._at(pointer)
        if definition.get("in") != "header":
            raise ValueError(f"{self._where(pointer)} isn't a header")
        name: str = definition["name"]
        return name

    def check_head(
        self, operation_id: str, status: int, headers: HeaderLines
    ) -> ResponseShape:
        """
        Check a response's status and headers against what its operation gives.

        Args:
            operation_id: The operation the request was for.
            status: The response's status.
            headers: The response's header lines.

        Returns:
            What the document gives the response, which its body is checked by.

        Raises:
            ContractViolation: The operation lists no such status, a header the
                response object defines is missing or doesn't meet its schema, or
                the response's media type is none the document gives it.
        """
        operation = self.operation(operation_id)
        responses_pointer = f"{operation.pointer}/responses"
        listed = [str(key) for key in self._at(responses_pointer)]
        candidates = (str(status), f"{status // 100}XX", "default")
        key = next((each for each in candidates if each in listed), None)
        if key is None:
            problem = (
                f"#{responses_pointer} lists no {status} response, only "
                + ", ".join(listed)
            )
            raise self._violation(operation, status, [problem], "response")
        pointer, response = self._follow(f"{responses_pointer}/{pointer_token(key)}")
        problems = self._header_problems(pointer, response, headers)
        media_type, problem = self._media_type(f"{pointer}/content", response, headers)
        if problem is not None:
            problems.append(problem)
        if problems:
            raise self._violation(operation, status, problems, "response")
        if media_type is None:
            return ResponseShape(operation, status, pointer, None, None, streamed=False)
        media_pointer, media = self._follow(
            f"{pointer}/content/{pointer_token(media_type)}"
        )
        return ResponseShape(
            operation,
            status,
            pointer,
            media_type,
            media_pointer,
            streamed=ITEM_SCHEMA in media,
        )

    def check_body(self, shape: ResponseShape, body: bytes) -> Any:
        """
        Check a whole response's body against the schema of its media type.

        A response the document gives no content has an empty body.

        Args:
            shape: What :meth:`check_head` found for the response.
            body: The body.

        Returns:
            The body parsed: a JSON value, or None for a response without content.

        Raises:
            ContractViolation: The body isn't empty where it should be, isn't JSON,
                or doesn't meet the schema.
            ValueError: The response is a stream, whose lines
                :meth:`check_stream_line` checks, or a media type the runner
                doesn't parse.
        """
        operation, status = shape.operation, shape.status
        media_pointer = shape.media_pointer
        if shape.media_type is None or media_pointer is None:
            if body:
                problem = (
                    f"its body holds {len(body)} bytes, where #{shape.pointer} gives "
                    "it no content"
                )
                raise self._violation(operation, status, [problem], "response")
            return None
        if shape.streamed:
            message = f"{operation.id}'s {status} response is a stream, read by line"
            raise ValueError(message)
        if not _is_json(shape.media_type):
            raise ValueError(f"the runner parses no body of {shape.media_type}")
        try:
            value = parse_json(body)
        except ValueError as error:
            problem = f"its body isn't JSON ({error}): {body[:QUOTED_BYTES]!r}"
            raise self._violation(operation, status, [problem], "response") from None
        if "schema" in self._at(media_pointer):
            problem = self._schema_problem("its body", f"{media_pointer}/schema", value)
            if problem is not None:
                raise self._violation(operation, status, [problem], "response")
        return value

    def check_response(
        self, operation_id: str, status: int, headers: HeaderLines, body: bytes
    ) -> Any:
        """
        Check a whole response: its status, its headers and its body.

        Args:
            operation_id: The operation the request was for.
            status: The response's status.
            headers: The response's header lines.
            body: The response's body.

        Returns:
            The body parsed, as :meth:`check_body` returns it.

        Raises:
            ContractViolation: The response doesn't meet the document.
            ValueError: The response is a stream, or carries a media type the runner
                doesn't parse.
        """
        shape = self.check_head(operation_id, status, headers)
        return self.check_body(shape, body)

    def check_stream_line(self, shape: ResponseShape, line: bytes, number: int) -> Any:
        """
        Check one line of a JSON Lines stream: that it ends in LF alone, as the spec
        has every line end, and meets the media type's item schema.

        Args:
            shape: What :meth:`check_head` found for the stream's response.
            line: The line as it was read, its LF included; a stream that ended
                within a line gives that line without one.
            number: The line's number in the stream, from 1, which a failure names.

        Returns:
            The line parsed, as a JSON value.

        Raises:
            ContractViolation: The line doesn't end in LF alone, isn't JSON or doesn't
                meet the item schema.
            ValueError: The response isn't a JSON Lines stream.
        """
        operation, status = shape.operation, shape.status
        media_pointer = shape.media_pointer
        if (
            not shape.streamed
            or shape.media_type != JSON_LINES
            or media_pointer is None
        ):
            message = f"{operation.id}'s {status} response is no {JSON_LINES} stream"
            raise ValueError(message)
        what = f"stream's line {number}"
        quoted = line[:QUOTED_BYTES]
        if not line.endswith(LINE_END):
            problem = f"the stream ended within it, with no LF: {quoted!r}"
            raise self._violation(operation, status, [problem], what)
        if line.endswith(b"\r" + LINE_END):
            problem = f"it ends in CRLF, where every line ends in LF alone: {quoted!r}"
            raise self._violation(operation, status, [problem], what)
        try:
            value = parse_json(line)
        except ValueError as error:
            problem = f"it isn't JSON ({error}): {quoted!r}"
            raise self._violation(operation, status, [problem], what) from None
        problem = self._schema_problem("it", f"{media_pointer}/{ITEM_SCHEMA}", value)
        if problem is not None:
            raise self._violation(operation, status, [problem], what)
        return value


@cache
def load_contract(version: int) -> Contract:
    """
    Read a protocol version's contract, once for each version.

    Args:
        version: The protocol version, whose files are in ``protocol/v<version>/``.

    Returns:
        The contract.
    """
    return Contract(version)


def field_value(headers: HeaderLines, name: str) -> str | None:
    """
    Read a header's value, by its name in any case.

    Args:
        headers: The header lines.
        name: The header's name.

    Returns:
        Its value, with the values of its repeats joined by commas as RFC 9110 lets a
        recipient join them, or None when no line names it.
    """
    values = [value for each, value in headers if each.lower() == name.lower()]
    return ", ".join(values) if values else None


def _reference(node: Any) -> str | None:
    if not isinstance(node, dict):
        return None
    reference = cast("dict[str, Any]", node).get("$ref")
    return reference if isinstance(reference, str) else None


def _is_json(media_type: str) -> bool:
    return media_type == "application/json" or media_type.endswith("+json")
