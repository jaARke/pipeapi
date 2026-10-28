import json
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, cast

import pytest
import yaml
from jsonschema import Draft202012Validator
from jsonschema.protocols import Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

PROTOCOL: Final = Path(__file__).resolve().parents[2] / "protocol"
OPENAPI_DOCUMENT: Final = "v*/openapi.yaml"
OPENAPI_DOCUMENTS: Final = sorted(PROTOCOL.glob(OPENAPI_DOCUMENT))
# The key that makes a media type a stream, in OpenAPI 3.2.
ITEM_SCHEMA: Final = "itemSchema"


@dataclass(frozen=True)
class StreamExample:
    """An example of a stream: a media type with an itemSchema, in OpenAPI 3.2."""

    document: Path
    media_type: str
    """A JSON pointer to the media type in the document."""
    name: str
    example: Mapping[str, Any]

    @property
    def id(self) -> str:
        where = self.document.relative_to(PROTOCOL).as_posix()
        return f"{where}#{self.media_type} {self.name}"


@dataclass(frozen=True)
class StreamItem:
    """One item of a stream example."""

    stream: StreamExample
    index: int
    item: Any

    @property
    def id(self) -> str:
        return f"{self.stream.id} item {self.index}"


def escape(key: str) -> str:
    return key.replace("~", "~0").replace("/", "~1")


def media_types_with_items(
    node: object, pointer: str = ""
) -> Iterator[tuple[str, Mapping[str, Any]]]:
    """Every object in the document that has an itemSchema, with its JSON pointer."""
    if isinstance(node, dict):
        mapping = cast("dict[str, Any]", node)
        if ITEM_SCHEMA in mapping:
            yield pointer, mapping
        for key, value in mapping.items():
            yield from media_types_with_items(value, f"{pointer}/{escape(key)}")
    elif isinstance(node, list):
        for index, value in enumerate(cast("list[Any]", node)):
            yield from media_types_with_items(value, f"{pointer}/{index}")


def read_document(path: Path) -> Any:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def stream_examples() -> list[StreamExample]:
    examples: list[StreamExample] = []
    for path in OPENAPI_DOCUMENTS:
        for pointer, media_type in media_types_with_items(read_document(path)):
            for name, example in media_type.get("examples", {}).items():
                examples.append(StreamExample(path, pointer, name, example))
    return examples


def items_of(stream: StreamExample) -> list[StreamItem]:
    """The items an example gives: its dataValue, or each line of serializedValue."""
    if "dataValue" in stream.example:
        return [StreamItem(stream, 0, stream.example["dataValue"])]
    text: str = stream.example["serializedValue"]
    lines = text.removesuffix("\n").split("\n")
    return [
        StreamItem(stream, index, json.loads(line)) for index, line in enumerate(lines)
    ]


STREAM_EXAMPLES: Final = stream_examples()
STREAM_ITEMS: Final = [item for stream in STREAM_EXAMPLES for item in items_of(stream)]


def item_validator(stream: StreamExample) -> Validator:
    """A validator of the stream's items, resolving references against its document."""
    uri = stream.document.as_uri()
    resource: Resource[Any] = Resource.from_contents(
        read_document(stream.document), default_specification=DRAFT202012
    )
    empty: Registry[Any] = Registry()
    registry = empty.with_resource(uri, resource)
    schema = {"$ref": f"{uri}#{stream.media_type}/{ITEM_SCHEMA}"}
    return Draft202012Validator(schema, registry=registry)


def test_the_protocol_has_openapi_documents() -> None:
    assert OPENAPI_DOCUMENTS, f"no {OPENAPI_DOCUMENT} in {PROTOCOL}"


@pytest.mark.parametrize("path", OPENAPI_DOCUMENTS, ids=lambda path: path.parent.name)
def test_a_document_has_streams_and_every_stream_an_example(path: Path) -> None:
    streams = list(media_types_with_items(read_document(path)))
    assert streams, f"no media type in {path} has an {ITEM_SCHEMA}"
    for pointer, media_type in streams:
        assert media_type.get("examples"), f"{pointer} gives no example"


@pytest.mark.parametrize("stream", STREAM_EXAMPLES, ids=lambda stream: stream.id)
def test_a_stream_example_gives_its_data_or_its_serialized_lines(
    stream: StreamExample,
) -> None:
    forms = {"dataValue", "serializedValue"} & stream.example.keys()
    assert len(forms) == 1, "give exactly one of dataValue and serializedValue"
    if "serializedValue" in stream.example:
        text: str = stream.example["serializedValue"]
        assert text.endswith("\n"), "every line ends in LF"
        assert "" not in text.removesuffix("\n").split("\n"), "a line is empty"


@pytest.mark.parametrize("item", STREAM_ITEMS, ids=lambda item: item.id)
def test_each_item_of_a_stream_example_meets_the_item_schema(item: StreamItem) -> None:
    errors = [
        f"{error.json_path}: {error.message}"
        for error in item_validator(item.stream).iter_errors(item.item)
    ]
    assert errors == []
