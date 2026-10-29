import json
from collections.abc import Hashable
from functools import cache, partial
from pathlib import Path
from typing import Any, NoReturn, override

import yaml
from jsonschema import Draft202012Validator
from jsonschema.protocols import Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012
from referencing.retrieval import to_cached_resource


def read_document(path: Path) -> Any:
    """
    Read a JSON or YAML file, by its suffix.

    A YAML mapping that holds a key twice fails to read, where PyYAML would keep the
    last value silently.

    Args:
        path: The file.

    Returns:
        What it holds.

    Raises:
        ValueError: The file is neither JSON nor YAML, or isn't valid JSON.
        yaml.YAMLError: The YAML doesn't parse, or a mapping holds a key twice.
    """
    if path.suffix == ".json":
        return json.loads(path.read_text(encoding="utf-8"))
    if path.suffix in {".yaml", ".yml"}:
        # Read from the file, so a parse error names it.
        with path.open(encoding="utf-8") as stream:
            return yaml.load(stream, Loader=_UniqueKeyLoader)
    message = f"{path} is neither JSON nor YAML"
    raise ValueError(message)


def parse_json(data: bytes) -> Any:
    """
    Parse JSON strictly: UTF-8, every object's names unique, and no NaN or Infinity.

    Python's parser accepts all of those, which other parsers read differently.

    Args:
        data: The JSON text's bytes.

    Returns:
        The value.

    Raises:
        ValueError: The bytes aren't such JSON, saying why.
    """
    return json.loads(
        data.decode("utf-8"),
        object_pairs_hook=_unique_names,
        parse_constant=_refuse_constant,
    )


def registry() -> Registry[Any]:
    """
    Make a registry that reads each file a reference names, by its ``file:`` URI.

    Each file is read and parsed once for the runner's process, whichever registry
    asks for it first, so a validator resolves its references without reading again.

    Returns:
        The registry; a file without ``$schema`` is a draft 2020-12 schema.
    """
    return Registry(retrieve=_retrieve)


def pointer_token(key: str) -> str:
    """
    Escape a key as one token of a JSON pointer, as RFC 6901 escapes it.

    Args:
        key: The key, such as a path or a media type.

    Returns:
        The token.

    Examples:
        >>> pointer_token("/__pipeapi/lease")
        '~1__pipeapi~1lease'
    """
    return key.replace("~", "~0").replace("/", "~1")


@cache
def validator(path: Path, pointer: str = "") -> Validator:
    """
    Make a validator of the schema at a JSON pointer in a file, once for each.

    Args:
        path: The file.
        pointer: The JSON pointer, empty for the whole file.

    Returns:
        The validator, which resolves the schema's references to other files.
    """
    schema = {"$ref": f"{path.as_uri()}#{pointer}"}
    return Draft202012Validator(schema, registry=registry())


class _UniqueKeyLoader(yaml.SafeLoader):
    """PyYAML's safe loader, which also refuses a key a mapping holds twice."""

    @override
    def construct_mapping(
        self, node: yaml.MappingNode, deep: bool = False
    ) -> dict[Hashable, Any]:
        mapping = super().construct_mapping(node, deep=deep)
        if len(mapping) < len(node.value):
            seen: set[str] = set()
            for key, _ in node.value:
                if str(key.value) in seen:
                    message = f"the key {key.value} appears twice"
                    raise yaml.constructor.ConstructorError(
                        None, None, message, key.start_mark
                    )
                seen.add(str(key.value))
        return mapping


# Gives the file, which read_document parses by its suffix, once for each URI.
@to_cached_resource(
    loads=read_document,
    from_contents=partial(Resource.from_contents, default_specification=DRAFT202012),
)
def _retrieve(uri: str) -> Path:
    return Path.from_uri(uri)


def _unique_names(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    names = [name for name, _ in pairs]
    for name in names:
        if names.count(name) > 1:
            raise ValueError(f"an object holds the name {name!r} twice")
    return dict(pairs)


def _refuse_constant(name: str) -> NoReturn:
    raise ValueError(f"{name} isn't JSON")
