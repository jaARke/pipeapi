import codecs
import json
from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, cast

import pytest
from jsonschema import ValidationError

from reference_app.app import create_app
from reference_app.environment import Settings
from runner.invariants import events_out_of_order
from runner.schemas import read_document, registry, validator

ADAPTER_PROTOCOL: Final = Path(__file__).resolve().parents[1] / "adapter-protocol"
SCHEMA: Final = "adapter-protocol.schema.json"
SCHEMAS: Final = sorted(ADAPTER_PROTOCOL.glob(f"v*/{SCHEMA}"))
EXAMPLES: Final = sorted(ADAPTER_PROTOCOL.glob("v*/examples/*.jsonl"))
# The keywords of a union whose failure lists each member's errors in its context.
UNIONS: Final = {"oneOf", "anyOf"}

Message = dict[str, Any]


@dataclass(frozen=True)
class Line:
    """One line of an example transcript."""

    example: Path
    number: int
    message: Message

    @property
    def id(self) -> str:
        return f"{name_of(self.example)}:{self.number}"


def name_of(path: Path) -> str:
    return path.relative_to(ADAPTER_PROTOCOL).as_posix()


def schema_of(example: Path) -> Path:
    """The schema of the version whose directory holds the example."""
    return example.parents[1] / SCHEMA


def read_transcript(example: Path) -> list[Line]:
    text = example.read_bytes().decode()
    transcript: list[Line] = []
    for number, line in enumerate(text.removesuffix("\n").split("\n"), start=1):
        try:
            transcript.append(Line(example, number, json.loads(line)))
        except json.JSONDecodeError as error:
            error.add_note(f"in {name_of(example)}:{number}")
            raise
    return transcript


def causes(error: ValidationError) -> Iterator[ValidationError]:
    """
    The errors that explain a failure: in a union, those of the members it could be.

    A member whose constant failed on a property of the instance itself, such as a
    command's name, is another member, so its errors explain nothing. Nor does an
    unevaluatedProperties error beside a failed union, which follows from it.
    """
    if error.validator not in UNIONS or not error.context:
        yield error
        return
    members: defaultdict[str | int, list[ValidationError]] = defaultdict(list)
    for member_error in error.context:
        members[member_error.relative_schema_path[0]].append(member_error)
    candidates = [
        errors
        for errors in members.values()
        if not any(
            each.validator == "const" and len(each.relative_path) == 1
            for each in errors
        )
    ]
    if not candidates:
        yield error
        return
    for errors in candidates:
        union_failed = any(each.validator in UNIONS for each in errors)
        for member_error in errors:
            if not (union_failed and member_error.validator == "unevaluatedProperties"):
                yield from causes(member_error)


def references(node: object) -> Iterator[str]:
    """Every $ref in a schema."""
    if isinstance(node, dict):
        mapping = cast("dict[str, Any]", node)
        if isinstance(reference := mapping.get("$ref"), str):
            yield reference
        for value in mapping.values():
            yield from references(value)
    elif isinstance(node, list):
        for value in cast("list[Any]", node):
            yield from references(value)


def names_in(schema: Message, union: str, key: str) -> set[str]:
    """The name each member of one of the schema's unions holds as its constant."""
    members: list[Message] = schema["$defs"][union]["oneOf"]
    return {member["properties"][key]["const"] for member in members}


def outcomes_in(schema: Message) -> set[str]:
    """The property each outcome of a reply requires."""
    members: list[Message] = schema["$defs"]["reply"]["oneOf"]
    return {member["required"][0] for member in members}


LINES: Final = [line for example in EXAMPLES for line in read_transcript(example)]
TYPED_REQUESTS: Final = [
    line
    for line in LINES
    if line.message["type"] == "command" and line.message["command"] == "typed_request"
]


def test_the_adapter_protocol_has_a_version() -> None:
    assert SCHEMAS, f"no v*/{SCHEMA} in {ADAPTER_PROTOCOL}"


@pytest.mark.parametrize("schema", SCHEMAS, ids=lambda schema: schema.parent.name)
def test_every_reference_in_a_schema_resolves(schema: Path) -> None:
    resolver = registry().resolver(base_uri=schema.as_uri())
    for reference in references(read_document(schema)):
        resolver.lookup(reference)


@pytest.mark.parametrize("schema", SCHEMAS, ids=lambda schema: schema.parent.name)
def test_the_examples_show_every_command_event_and_outcome(schema: Path) -> None:
    document = read_document(schema)
    messages = [line.message for line in LINES if schema_of(line.example) == schema]
    shown_commands = {each["command"] for each in messages if each["type"] == "command"}
    shown_events = {each["event"] for each in messages if each["type"] == "event"}
    shown_outcomes = {
        key for each in messages if each["type"] == "reply" for key in each
    }
    assert names_in(document, "command", "command") - shown_commands == set()
    assert names_in(document, "event", "event") - shown_events == set()
    assert outcomes_in(document) - shown_outcomes == set()


@pytest.mark.parametrize("example", EXAMPLES, ids=name_of)
def test_an_example_is_json_lines(example: Path) -> None:
    data = example.read_bytes()
    text = data.decode()
    assert not data.startswith(codecs.BOM_UTF8), "no byte order mark"
    assert b"\r" not in data, "lines end in LF alone"
    assert text.endswith("\n"), "every line ends in LF"
    for number, line in enumerate(text.removesuffix("\n").split("\n"), start=1):
        assert isinstance(json.loads(line), dict), f"line {number} isn't an object"


@pytest.mark.parametrize("line", LINES, ids=lambda line: line.id)
def test_each_line_of_an_example_meets_the_schema(line: Line) -> None:
    errors = [
        f"{cause.json_path}: {cause.message}"
        for error in validator(schema_of(line.example)).iter_errors(line.message)
        for cause in causes(error)
    ]
    assert errors == []


@pytest.mark.parametrize("example", EXAMPLES, ids=name_of)
def test_an_example_opens_with_the_hello_and_answers_each_command_once(
    example: Path,
) -> None:
    first, *rest = [line.message for line in read_transcript(example)]
    assert first["type"] == "hello", "the adapter speaks first"
    assert all(message["type"] != "hello" for message in rest), "one hello"
    commands: dict[int, str] = {}
    answered: set[int] = set()
    for message in rest:
        if message["type"] == "command":
            assert message["id"] not in commands, f"command {message['id']} reused"
            commands[message["id"]] = message["command"]
        elif message["type"] == "reply":
            id_ = message["id"]
            assert commands.get(id_) == message["command"], (
                f"reply {id_} answers no command"
            )
            assert id_ not in answered, f"command {id_} answered twice"
            answered.add(id_)
    assert commands.keys() - answered == set(), "every command gets its reply"


@pytest.mark.parametrize("example", EXAMPLES, ids=name_of)
def test_the_lifecycle_events_of_an_example_keep_the_connector_apis_order(
    example: Path,
) -> None:
    transcript = [line.message for line in read_transcript(example)]
    assert events_out_of_order(transcript) == []


@pytest.mark.parametrize("line", TYPED_REQUESTS, ids=lambda line: line.id)
def test_a_typed_request_names_an_operation_of_the_reference_app(line: Line) -> None:
    schema = create_app(Settings(log=None)).openapi()
    operations = {
        operation["operationId"]
        for path in schema["paths"].values()
        for operation in path.values()
    }
    assert line.message["operation"] in operations
