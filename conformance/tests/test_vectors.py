import hmac
import json
import re
from collections.abc import Callable, Mapping
from functools import partial
from pathlib import Path
from typing import Any, Final, Literal, NotRequired, TypedDict

import pytest

from runner.proofs import (
    ENROLLMENT_MISTAKES,
    HELLO_MISTAKES,
    EnrollmentMistake,
    HelloMistake,
    ProofInput,
    decode_b64u_32,
    encode_b64u_32,
    enrollment_header,
    enrollment_proof_input,
    hello_proof_input,
)

VECTORS: Final = Path(__file__).resolve().parents[2] / "protocol" / "v1" / "vectors"

# The flags that describe a proof case's input. Every other flag of a proof case names
# the one mistake its proof was computed with, which runner.proofs derives.
PROOF_INPUT_FLAGS: Final = frozenset(
    {"GeneratedToken", "UserToken", "MultiByteToken", "PidRange", "UntrimmedToken"}
)
MISTAKES_OF: Final[Mapping[str, frozenset[str]]] = {
    "hello_proof": HELLO_MISTAKES,
    "enrollment_proof": ENROLLMENT_MISTAKES,
}

UNIX_PREFIX: Final = "unix://"
NPIPE_PREFIX: Final = "npipe:////./pipe/"
# A unix:// path takes every template but {session}.
UNIX_TEMPLATES: Final = frozenset({"user", "pid"})
# Windows limits the whole pipe path, this prefix and the name together, in UTF-16
# code units.
PIPE_PATH_PREFIX: Final = r"\\.\pipe" + "\\"
MAX_PIPE_PATH_CODE_UNITS: Final = 256
TCP_ENDPOINT: Final = re.compile(r"tcp://(?:127\.0\.0\.1|\[::1\]):(0|[1-9][0-9]*)")
MAX_PORT: Final = 65535
REFUSED_PORTS: Final = frozenset({80, 443})
# A template, or a brace outside one.
TEMPLATE: Final = re.compile(r"\{([^{}]*)\}|[{}]")


class Case(TypedDict):
    tcId: int
    comment: str
    flags: list[str]
    result: Literal["valid", "invalid"]


class HelloProofCase(Case):
    token: str
    nonce: str
    pid: int
    otherPid: NotRequired[int]
    message: NotRequired[str]
    proof: str


class EnrollmentProofCase(Case):
    token: str
    challenge: str
    otherChallenge: NotRequired[str]
    message: NotRequired[str]
    proof: str
    header: NotRequired[str]


class WindowsContext(TypedDict):
    userName: str
    sessionId: int
    pid: int


class PosixContext(TypedDict):
    uid: int
    pid: int


class TemplateExpansionCase(Case):
    endpoint: str
    expanded: NotRequired[str]


class WindowsTemplateExpansionCase(TemplateExpansionCase):
    platform: Literal["windows"]
    context: WindowsContext


class PosixTemplateExpansionCase(TemplateExpansionCase):
    platform: Literal["posix"]
    context: PosixContext


type PlatformTemplateExpansionCase = (
    WindowsTemplateExpansionCase | PosixTemplateExpansionCase
)


class VectorFile[CaseT: Case](TypedDict):
    kind: str
    description: str
    notes: dict[str, str]
    tests: list[CaseT]


class InvalidEndpoint(Exception):
    """The endpoint breaks the grammar, as given or after expansion."""


def file_name(kind: str) -> str:
    return f"{kind.replace('_', '-')}.json"


def read_vectors(kind: str) -> Any:
    return json.loads((VECTORS / file_name(kind)).read_bytes())


HELLO_PROOFS: Final[VectorFile[HelloProofCase]] = read_vectors("hello_proof")
ENROLLMENT_PROOFS: Final[VectorFile[EnrollmentProofCase]] = read_vectors(
    "enrollment_proof"
)
TEMPLATE_EXPANSIONS: Final[VectorFile[PlatformTemplateExpansionCase]] = read_vectors(
    "template_expansion"
)
VECTOR_FILES: Final = {
    "hello_proof": HELLO_PROOFS,
    "enrollment_proof": ENROLLMENT_PROOFS,
    "template_expansion": TEMPLATE_EXPANSIONS,
}


def case_ids[CaseT: Case](vectors: VectorFile[CaseT]) -> list[str]:
    return [f"{vectors['kind']}-tcId{case['tcId']}" for case in vectors["tests"]]


def hello_mistake(flag: str) -> HelloMistake:
    for mistake in HELLO_MISTAKES:
        if mistake == flag:
            return mistake
    pytest.fail(f"runner.proofs derives no hello proof for the flag {flag}")


def enrollment_mistake(flag: str) -> EnrollmentMistake:
    for mistake in ENROLLMENT_MISTAKES:
        if mistake == flag:
            return mistake
    pytest.fail(f"runner.proofs derives no enrollment proof for the flag {flag}")


def hello_case_input(case: HelloProofCase, flag: str | None) -> ProofInput:
    """The case's proof input, by the rules or with the mistake a flag names."""
    mistake = None if flag is None else hello_mistake(flag)
    if mistake == "RelayedProof":
        assert "otherPid" in case, f"a case flagged {mistake} gives it"
    return hello_proof_input(
        case["token"],
        case["nonce"],
        case["pid"],
        mistake,
        other_pid=case.get("otherPid"),
    )


def enrollment_case_input(case: EnrollmentProofCase, flag: str | None) -> ProofInput:
    """The case's proof input, by the rules or with the mistake a flag names."""
    mistake = None if flag is None else enrollment_mistake(flag)
    if mistake == "OtherChallenge":
        assert "otherChallenge" in case, f"a case flagged {mistake} gives it"
    return enrollment_proof_input(
        case["token"],
        case["challenge"],
        mistake,
        other_challenge=case.get("otherChallenge"),
    )


def check_proof(
    case: HelloProofCase | EnrollmentProofCase,
    proof_input: Callable[[str | None], ProofInput],
) -> None:
    """Check the proof as a verifier would, and an invalid one against its mistake."""
    rules = proof_input(None)
    matches = hmac.compare_digest(rules.digest, decode_b64u_32(case["proof"]))
    mistakes = [flag for flag in case["flags"] if flag not in PROOF_INPUT_FLAGS]
    if case["result"] == "valid":
        assert mistakes == [], "a valid case's flags all describe its input"
        assert case.get("message") == rules.message.hex()
        assert matches, f"the proof is {encode_b64u_32(rules.digest)}"
    else:
        assert len(mistakes) == 1, "an invalid case's flags name exactly one mistake"
        [mistake] = mistakes
        assert not matches, "an invalid case's proof is the one the rules give"
        mistaken = proof_input(mistake).proof
        assert case["proof"] == mistaken, f"the proof isn't the one {mistake} gives"


def template_values(case: PlatformTemplateExpansionCase) -> dict[str, str]:
    if case["platform"] == "windows":
        windows = case["context"]
        return {
            "user": windows["userName"],
            "session": str(windows["sessionId"]),
            "pid": str(windows["pid"]),
        }
    posix = case["context"]
    return {"user": str(posix["uid"]), "pid": str(posix["pid"])}


def expand_templates(text: str, values: Mapping[str, str]) -> str:
    """Expand each template in one pass, refusing any brace outside a known one."""

    def value(template: re.Match[str]) -> str:
        name = template[1]
        if name is None or name not in values:
            raise InvalidEndpoint(f"{template[0]} is no template here")
        return values[name]

    return TEMPLATE.sub(value, text)


def expand_endpoint(case: PlatformTemplateExpansionCase) -> str:
    """Expand and validate the case's endpoint, as a connector does."""
    endpoint = case["endpoint"]
    values = template_values(case)
    unsupported = UNIX_PREFIX if case["platform"] == "windows" else NPIPE_PREFIX
    if endpoint.startswith(unsupported):
        raise InvalidEndpoint(f"{case['platform']} doesn't support {unsupported}")
    if endpoint.startswith(UNIX_PREFIX):
        unix_values = {name: values[name] for name in UNIX_TEMPLATES & values.keys()}
        path = expand_templates(endpoint.removeprefix(UNIX_PREFIX), unix_values)
        if not path.startswith("/"):
            raise InvalidEndpoint(f"{path} isn't an absolute path")
        return UNIX_PREFIX + path
    if endpoint.startswith(NPIPE_PREFIX):
        name = expand_templates(endpoint.removeprefix(NPIPE_PREFIX), values)
        if not name or "/" in name or "\\" in name:
            raise InvalidEndpoint(f"{name!r} isn't a pipe name")
        code_units = len((PIPE_PATH_PREFIX + name).encode("utf-16-le")) // 2
        if code_units > MAX_PIPE_PATH_CODE_UNITS:
            raise InvalidEndpoint(f"the pipe name {name} is too long")
        return NPIPE_PREFIX + name
    tcp = TCP_ENDPOINT.fullmatch(endpoint)
    if tcp is None:
        raise InvalidEndpoint(f"{endpoint} is no endpoint")
    port = int(tcp[1])
    if port > MAX_PORT or port in REFUSED_PORTS:
        raise InvalidEndpoint(f"{port} isn't a port an endpoint may name")
    return endpoint


@pytest.mark.parametrize("case", HELLO_PROOFS["tests"], ids=case_ids(HELLO_PROOFS))
def test_the_rules_give_each_hello_proof_case_its_result(
    case: HelloProofCase,
) -> None:
    check_proof(case, partial(hello_case_input, case))


@pytest.mark.parametrize(
    "case", ENROLLMENT_PROOFS["tests"], ids=case_ids(ENROLLMENT_PROOFS)
)
def test_the_rules_give_each_enrollment_proof_case_its_result(
    case: EnrollmentProofCase,
) -> None:
    check_proof(case, partial(enrollment_case_input, case))
    if case["result"] == "valid":
        header = enrollment_header(case["token"], case["challenge"])
        assert header == f"{case['challenge']}.{case['proof']}"
        assert case.get("header") == header


@pytest.mark.parametrize("kind", MISTAKES_OF)
def test_the_runner_knows_exactly_the_mistakes_a_proof_vector_file_flags(
    kind: str,
) -> None:
    vectors = VECTOR_FILES[kind]
    flags = {flag for case in vectors["tests"] for flag in case["flags"]}
    assert flags - PROOF_INPUT_FLAGS == MISTAKES_OF[kind]


@pytest.mark.parametrize(
    "case", TEMPLATE_EXPANSIONS["tests"], ids=case_ids(TEMPLATE_EXPANSIONS)
)
def test_the_rules_give_each_template_expansion_case_its_result(
    case: PlatformTemplateExpansionCase,
) -> None:
    if case["result"] == "valid":
        assert expand_endpoint(case) == case.get("expanded")
    else:
        with pytest.raises(InvalidEndpoint):
            expand_endpoint(case)


def test_the_directory_holds_one_file_of_each_kind_and_no_other() -> None:
    found = {
        path.name
        for path in VECTORS.glob("*.json")
        if not path.name.endswith(".schema.json")
    }
    assert found == {file_name(kind) for kind in VECTOR_FILES}


@pytest.mark.parametrize("kind", VECTOR_FILES)
def test_a_vector_file_holds_the_kind_it_is_named_for(kind: str) -> None:
    assert VECTOR_FILES[kind]["kind"] == kind


@pytest.mark.parametrize("kind", VECTOR_FILES)
def test_a_vector_files_cases_count_up_from_one(kind: str) -> None:
    tc_ids = [case["tcId"] for case in VECTOR_FILES[kind]["tests"]]
    assert tc_ids == list(range(1, len(tc_ids) + 1))


@pytest.mark.parametrize("kind", VECTOR_FILES)
def test_every_flag_is_a_note_and_every_note_flags_a_case(kind: str) -> None:
    vectors = VECTOR_FILES[kind]
    flags = {flag for case in vectors["tests"] for flag in case["flags"]}
    notes = set(vectors["notes"])
    assert flags - notes == set(), "flags with no note"
    assert notes - flags == set(), "notes no case carries"
