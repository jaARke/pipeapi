import base64
import hashlib
import hmac
import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Any, Final, Literal, NotRequired, TypedDict

import pytest

VECTORS: Final = Path(__file__).resolve().parents[2] / "protocol" / "v1" / "vectors"

# protocol/v1/registry.yaml's constants.hello_label and constants.enrollment_label.
HELLO_LABEL: Final = b"pipeapi-hello-v1"
ENROLLMENT_LABEL: Final = b"pipeapi-enroll-v1"

SEPARATOR: Final = b"\x00"
# A nonce or a challenge.
RANDOM_BYTES: Final = 32
PID_BYTES: Final = 4
# The flags that describe a proof case's input. Every other flag of a proof case names
# the one mistake its proof was computed with, which the test derives.
PROOF_INPUT_FLAGS: Final = frozenset(
    {"GeneratedToken", "UserToken", "MultiByteToken", "PidRange", "UntrimmedToken"}
)

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


@dataclass(frozen=True)
class ProofInput:
    """The key and the message a proof's HMAC-SHA256 is computed from."""

    key: bytes
    message: bytes

    @property
    def proof(self) -> bytes:
        return hmac.digest(self.key, self.message, hashlib.sha256)


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


def encode_base64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def decode_base64url_32(text: str) -> bytes:
    """Decode 32 bytes from unpadded, canonical base64url, refusing any other form."""
    decoded = base64.urlsafe_b64decode(text + "=")
    assert len(decoded) == RANDOM_BYTES and encode_base64url(decoded) == text, (
        f"{text!r} isn't canonical base64url of {RANDOM_BYTES} bytes"
    )
    return decoded


def token_key(token: str) -> bytes:
    """The token's text, never what it decodes to, whatever it looks like."""
    return token.encode()


def encode_pid(pid: int) -> bytes:
    return pid.to_bytes(PID_BYTES, "big")


def hello_proof_input(case: HelloProofCase, mistake: str | None) -> ProofInput:
    """The case's proof input, by the rules or with the mistake a flag names."""
    key = token_key(case["token"])
    label = HELLO_LABEL
    separator = SEPARATOR
    nonce = decode_base64url_32(case["nonce"])
    pid = encode_pid(case["pid"])
    match mistake:
        case None:
            pass
        case "WrongLabel":
            label = ENROLLMENT_LABEL
        case "MissingSeparator":
            separator = b""
        case "DecodedTokenKey":
            key = decode_base64url_32(case["token"])
        case "TrimmedTokenKey":
            key = token_key(case["token"].strip(" "))
        case "NonceAsText":
            nonce = case["nonce"].encode()
        case "PidLittleEndian":
            pid = case["pid"].to_bytes(PID_BYTES, "little")
        case "PidAsText":
            pid = str(case["pid"]).encode()
        case "RelayedProof":
            assert "otherPid" in case, f"a case flagged {mistake} gives otherPid"
            pid = encode_pid(case["otherPid"])
        case _:
            pytest.fail(f"the test derives no hello proof for the flag {mistake}")
    return ProofInput(key, label + separator + nonce + pid)


def enrollment_proof_input(
    case: EnrollmentProofCase, mistake: str | None
) -> ProofInput:
    """The case's proof input, by the rules or with the mistake a flag names."""
    key = token_key(case["token"])
    label = ENROLLMENT_LABEL
    separator = SEPARATOR
    challenge = decode_base64url_32(case["challenge"])
    match mistake:
        case None:
            pass
        case "WrongLabel":
            label = HELLO_LABEL
        case "MissingSeparator":
            separator = b""
        case "DecodedTokenKey":
            key = decode_base64url_32(case["token"])
        case "ChallengeAsText":
            challenge = case["challenge"].encode()
        case "OtherChallenge":
            assert "otherChallenge" in case, (
                f"a case flagged {mistake} gives otherChallenge"
            )
            challenge = decode_base64url_32(case["otherChallenge"])
        case _:
            pytest.fail(f"the test derives no enrollment proof for the flag {mistake}")
    return ProofInput(key, label + separator + challenge)


def check_proof(
    case: HelloProofCase | EnrollmentProofCase,
    proof_input: Callable[[str | None], ProofInput],
) -> None:
    """Check the proof as a verifier would, and an invalid one against its mistake."""
    rules = proof_input(None)
    matches = hmac.compare_digest(rules.proof, decode_base64url_32(case["proof"]))
    mistakes = [flag for flag in case["flags"] if flag not in PROOF_INPUT_FLAGS]
    if case["result"] == "valid":
        assert mistakes == [], "a valid case's flags all describe its input"
        assert case.get("message") == rules.message.hex()
        assert matches, f"the proof is {encode_base64url(rules.proof)}"
    else:
        assert len(mistakes) == 1, "an invalid case's flags name exactly one mistake"
        [mistake] = mistakes
        assert not matches, "an invalid case's proof is the one the rules give"
        mistaken = encode_base64url(proof_input(mistake).proof)
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
    check_proof(case, partial(hello_proof_input, case))


@pytest.mark.parametrize(
    "case", ENROLLMENT_PROOFS["tests"], ids=case_ids(ENROLLMENT_PROOFS)
)
def test_the_rules_give_each_enrollment_proof_case_its_result(
    case: EnrollmentProofCase,
) -> None:
    check_proof(case, partial(enrollment_proof_input, case))
    if case["result"] == "valid":
        assert case.get("header") == f"{case['challenge']}.{case['proof']}"


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
