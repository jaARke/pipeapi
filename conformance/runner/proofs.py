import base64
import binascii
import hashlib
import hmac
import secrets
from dataclasses import dataclass
from typing import Final, Literal, assert_never, get_args

from runner.contract import PROTOCOL_VERSION, load_contract

type HelloMistake = Literal[
    "WrongLabel",
    "MissingSeparator",
    "DecodedTokenKey",
    "TrimmedTokenKey",
    "NonceAsText",
    "PidLittleEndian",
    "PidAsText",
    "RelayedProof",
]
"""A mistake a hello proof can be computed with, as the hello-proof vectors flag it."""

type EnrollmentMistake = Literal[
    "WrongLabel",
    "MissingSeparator",
    "DecodedTokenKey",
    "ChallengeAsText",
    "OtherChallenge",
]
"""A mistake an enrollment proof can be computed with, as its vectors flag it."""

HELLO_MISTAKES: Final[frozenset[HelloMistake]] = frozenset(
    get_args(HelloMistake.__value__)
)
ENROLLMENT_MISTAKES: Final[frozenset[EnrollmentMistake]] = frozenset(
    get_args(EnrollmentMistake.__value__)
)

# The vectors in protocol/v1/vectors/ are computed with the registry's labels.
HELLO_LABEL: Final = load_contract(PROTOCOL_VERSION).constant("hello_label").encode()
ENROLLMENT_LABEL: Final = (
    load_contract(PROTOCOL_VERSION).constant("enrollment_label").encode()
)
SEPARATOR: Final = b"\x00"
B64U_BYTES: Final = 32
"""The length of what b64u(32) encodes: a nonce, a challenge, a proof or a secret."""
PID_BYTES: Final = 4
PID_LIMIT: Final = 2 ** (8 * PID_BYTES)
"""One past the largest PID, which fits the PID's 4 bytes."""
# What separates the challenge from the proof in the enrollment header.
ENROLLMENT_SEPARATOR: Final = "."


@dataclass(frozen=True)
class ProofInput:
    """The key and the message a proof's HMAC-SHA256 is computed from."""

    key: bytes
    message: bytes

    @property
    def digest(self) -> bytes:
        """The proof's 32 bytes."""
        return hmac.digest(self.key, self.message, hashlib.sha256)

    @property
    def proof(self) -> str:
        """The proof, in b64u(32), as the protocol carries it."""
        return encode_b64u_32(self.digest)


def encode_b64u_32(data: bytes) -> str:
    """
    Encode 32 bytes in canonical, unpadded base64url.

    Args:
        data: The bytes.

    Returns:
        Their 43 characters.

    Raises:
        ValueError: The bytes aren't 32.
    """
    if len(data) != B64U_BYTES:
        raise ValueError(f"b64u(32) encodes {B64U_BYTES} bytes, not {len(data)}")
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def decode_b64u_32(text: str) -> bytes:
    """
    Decode 32 bytes from canonical, unpadded base64url, refusing any other form.

    Args:
        text: The text.

    Returns:
        The 32 bytes.

    Raises:
        ValueError: The text is padded, uses another alphabet, isn't 43 characters,
            or sets its last character's unused bits.
    """
    try:
        decoded = base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    except binascii.Error, ValueError:
        decoded = b""
    # Decoding forgives padding, stray characters and unused bits, which this refuses.
    if len(decoded) != B64U_BYTES or encode_b64u_32(decoded) != text:
        raise ValueError(f"{text!r} isn't canonical base64url of {B64U_BYTES} bytes")
    return decoded


def random_b64u_32() -> str:
    """
    Make a fresh nonce, challenge or session secret: 32 random bytes in b64u(32).

    Returns:
        Its text.
    """
    return encode_b64u_32(secrets.token_bytes(B64U_BYTES))


def token_key(token: str) -> bytes:
    """
    Make the key of a proof from the token.

    Args:
        token: The token, exactly as given.

    Returns:
        The token's UTF-8 text, never what it decodes to, whatever it looks like.
    """
    return token.encode()


def hello_proof_input(
    token: str,
    nonce: str,
    pid: int,
    mistake: HelloMistake | None = None,
    *,
    other_pid: int | None = None,
) -> ProofInput:
    """
    Make the input of a hello proof, by the rules or with one mistake.

    The message is the hello label, 0x00, the nonce's 32 bytes and the PID's 4 bytes
    big-endian; the key is the token's UTF-8 text.

    Args:
        token: The token.
        nonce: The client's nonce, in b64u(32).
        pid: The PID the hello names.
        mistake: The mistake to make, as the vectors flag it, or None for the rules.
        other_pid: The PID a ``RelayedProof`` covers, which only it needs.

    Returns:
        The input.

    Raises:
        ValueError: The nonce isn't b64u(32), the PID doesn't fit 4 bytes, the
            mistake needs an input not given (``other_pid``, or a token in b64u(32)
            for ``DecodedTokenKey``), or it changes nothing for this input.
    """
    key = token_key(token)
    label = HELLO_LABEL
    separator = SEPARATOR
    nonce_part = decode_b64u_32(nonce)
    pid_part = _pid_bytes(pid)
    rules = ProofInput(key, label + separator + nonce_part + pid_part)
    match mistake:
        case None:
            return rules
        case "WrongLabel":
            label = ENROLLMENT_LABEL
        case "MissingSeparator":
            separator = b""
        case "DecodedTokenKey":
            key = decode_b64u_32(token)
        case "TrimmedTokenKey":
            key = token_key(token.strip(" "))
        case "NonceAsText":
            nonce_part = nonce.encode()
        case "PidLittleEndian":
            pid_part = pid.to_bytes(PID_BYTES, "little")
        case "PidAsText":
            pid_part = str(pid).encode()
        case "RelayedProof":
            if other_pid is None:
                raise ValueError(f"{mistake} covers other_pid, which isn't given")
            pid_part = _pid_bytes(other_pid)
        case _:
            assert_never(mistake)
    return _mistaken(rules, ProofInput(key, label + separator + nonce_part + pid_part))


def hello_proof(
    token: str,
    nonce: str,
    pid: int,
    mistake: HelloMistake | None = None,
    *,
    other_pid: int | None = None,
) -> str:
    """
    Compute a hello proof, by the rules or with one mistake.

    Args:
        token: The token.
        nonce: The client's nonce, in b64u(32).
        pid: The PID the hello names.
        mistake: The mistake to make, or None for the rules.
        other_pid: The PID a ``RelayedProof`` covers, which only it needs.

    Returns:
        The proof, in b64u(32).

    Raises:
        ValueError: As :func:`hello_proof_input` raises it.
    """
    return hello_proof_input(token, nonce, pid, mistake, other_pid=other_pid).proof


def hello_proof_verifies(proof: str, *, token: str, nonce: str, pid: int) -> bool:
    """
    Check a hello's proof as a client does, in constant time.

    Args:
        proof: The proof the hello carries.
        token: The token.
        nonce: The nonce the hello request carried.
        pid: The PID the hello names.

    Returns:
        Whether the proof is the one the rules give.

    Raises:
        ValueError: The nonce isn't b64u(32), or the PID doesn't fit 4 bytes.
    """
    expected = hello_proof(token, nonce, pid)
    return hmac.compare_digest(expected.encode(), proof.encode())


def enrollment_proof_input(
    token: str,
    challenge: str,
    mistake: EnrollmentMistake | None = None,
    *,
    other_challenge: str | None = None,
) -> ProofInput:
    """
    Make the input of an enrollment proof, by the rules or with one mistake.

    The message is the enrollment label, 0x00 and the challenge's 32 bytes; the key
    is the token's UTF-8 text.

    Args:
        token: The token.
        challenge: The hello's challenge, in b64u(32).
        mistake: The mistake to make, as the vectors flag it, or None for the rules.
        other_challenge: The challenge an ``OtherChallenge`` answers, which only it
            needs.

    Returns:
        The input.

    Raises:
        ValueError: A challenge isn't b64u(32), the mistake needs an input not given
            (``other_challenge``, or a token in b64u(32) for ``DecodedTokenKey``), or
            it changes nothing for this input.
    """
    key = token_key(token)
    label = ENROLLMENT_LABEL
    separator = SEPARATOR
    challenge_part = decode_b64u_32(challenge)
    rules = ProofInput(key, label + separator + challenge_part)
    match mistake:
        case None:
            return rules
        case "WrongLabel":
            label = HELLO_LABEL
        case "MissingSeparator":
            separator = b""
        case "DecodedTokenKey":
            key = decode_b64u_32(token)
        case "ChallengeAsText":
            challenge_part = challenge.encode()
        case "OtherChallenge":
            if other_challenge is None:
                message = f"{mistake} answers other_challenge, which isn't given"
                raise ValueError(message)
            challenge_part = decode_b64u_32(other_challenge)
        case _:
            assert_never(mistake)
    return _mistaken(rules, ProofInput(key, label + separator + challenge_part))


def enrollment_proof(
    token: str,
    challenge: str,
    mistake: EnrollmentMistake | None = None,
    *,
    other_challenge: str | None = None,
) -> str:
    """
    Compute an enrollment proof, by the rules or with one mistake.

    Args:
        token: The token.
        challenge: The hello's challenge, in b64u(32).
        mistake: The mistake to make, or None for the rules.
        other_challenge: The challenge an ``OtherChallenge`` answers, which only it
            needs.

    Returns:
        The proof, in b64u(32).

    Raises:
        ValueError: As :func:`enrollment_proof_input` raises it.
    """
    return enrollment_proof_input(
        token, challenge, mistake, other_challenge=other_challenge
    ).proof


def enrollment_header(
    token: str,
    challenge: str,
    mistake: EnrollmentMistake | None = None,
    *,
    other_challenge: str | None = None,
) -> str:
    """
    Compute the enrollment header's value: the challenge, a period, then the proof.

    Args:
        token: The token.
        challenge: The hello's challenge, in b64u(32), as the hello gave it.
        mistake: The mistake to make in the proof, or None for the rules.
        other_challenge: The challenge an ``OtherChallenge`` answers, which only it
            needs.

    Returns:
        The value.

    Raises:
        ValueError: As :func:`enrollment_proof_input` raises it.
    """
    proof = enrollment_proof(token, challenge, mistake, other_challenge=other_challenge)
    return f"{challenge}{ENROLLMENT_SEPARATOR}{proof}"


def _pid_bytes(pid: int) -> bytes:
    if not 0 <= pid < PID_LIMIT:
        raise ValueError(f"the PID {pid} doesn't fit {PID_BYTES} bytes")
    return pid.to_bytes(PID_BYTES, "big")


def _mistaken(rules: ProofInput, mistaken: ProofInput) -> ProofInput:
    # Such as a trimmed key for a token without spaces, which would prove nothing.
    if mistaken == rules:
        raise ValueError("the mistake changes nothing for this input")
    return mistaken
