"""FEAT-009 envelope rendering and body validation.

Builds the structured prompt envelope per FR-001 / FR-002 and validates
the body per FR-003 / FR-004.

The envelope text shape (FR-001):

    Message-Id: <uuidv4>
    From: <agent_id> "<label>" <role>[ [capability=<cap>]]
    To: <agent_id> "<label>" <role>[ [capability=<cap>]]
    Type: prompt
    Priority: normal
    Requires-Reply: yes

    <body bytes verbatim, including \\n and \\t>

A single blank line (``\\n\\n``) separates the headers from the body
(FR-002). The body is appended VERBATIM in bytes — no encoding,
escaping, or normalization.

Body validation (FR-003) rejects:

* empty bodies (``body_empty``)
* non-UTF-8 bodies (``body_invalid_encoding``)
* bodies containing NUL (``\\x00``) or any ASCII control character
  other than ``\\n`` (0x0a) and ``\\t`` (0x09) (``body_invalid_chars``)

Size cap (FR-004) is enforced AFTER rendering against the full
serialized envelope (not the raw body), preventing header-stuffing
bypass.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from agenttower.routing.errors import (
    BODY_EMPTY,
    BODY_INVALID_CHARS,
    BODY_INVALID_ENCODING,
    BODY_TOO_LARGE,
    QueueServiceError,
)


__all__ = [
    "DEFAULT_ENVELOPE_BODY_MAX_BYTES",
    "BodyValidationError",
    "EnvelopeIdentity",
    "render_envelope",
    "serialize_and_check_size",
    "validate_body",
]


DEFAULT_ENVELOPE_BODY_MAX_BYTES: Final[int] = 65_536
"""Default cap on the SERIALIZED envelope (headers + body) per FR-004 +
Assumptions "Body size cap" (64 KiB). Operators override via the
``[routing]`` section of ``config.toml``."""


# Bytes that FR-003 forbids in the body. Computed once at module load:
#   0x00 (NUL) + 0x01..0x08 + 0x0B..0x1F (every ASCII control < 0x20
#   EXCEPT \t=0x09 and \n=0x0a) + 0x7F (DEL).
_FORBIDDEN_BODY_BYTES: Final[frozenset[int]] = (
    frozenset(range(0x00, 0x20)) | {0x7F}
) - {0x09, 0x0A}


class BodyValidationError(QueueServiceError):
    """Raised by :func:`validate_body` and :func:`serialize_and_check_size`.

    The ``code`` attribute carries one of the four FR-003 / FR-004
    closed-set string codes: ``body_empty``, ``body_invalid_encoding``,
    ``body_invalid_chars``, ``body_too_large``. The CLI maps each to a
    distinct operator remediation surface; the codes are deliberately
    NOT unified to keep operator messages actionable.
    """


@dataclass(frozen=True)
class EnvelopeIdentity:
    """Captured identity for one side (sender or target) of the envelope.

    Mirrors the FEAT-006 :class:`AgentRecord` shape for the four fields
    that appear in the envelope headers. The :class:`QueueService`
    snapshots these from the resolved :class:`AgentRecord` at enqueue
    time and persists them into the ``message_queue`` row's
    ``sender_*`` / ``target_*`` columns (data-model.md §5 — identity
    capture is enqueue-frozen).
    """

    agent_id: str
    label: str
    role: str
    capability: str | None


def validate_body(body_bytes: bytes) -> None:
    """Enforce FR-003 on the raw body bytes.

    Raises :class:`BodyValidationError` with a closed-set ``code`` on
    failure; returns ``None`` on success. Cheap and deterministic —
    runs in O(len(body)) and never touches I/O.

    The order matters: empty → encoding → chars. The CLI surface
    distinguishes the three (different exit codes / different operator
    remediation) per FR-049.
    """
    if not isinstance(body_bytes, (bytes, bytearray)):
        raise BodyValidationError(
            BODY_INVALID_ENCODING,
            f"body must be bytes-like; got {type(body_bytes).__name__}",
        )
    if len(body_bytes) == 0:
        raise BodyValidationError(BODY_EMPTY, "body must not be empty")
    try:
        body_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise BodyValidationError(
            BODY_INVALID_ENCODING,
            f"body is not valid UTF-8: {exc}",
        ) from None
    for byte in body_bytes:
        if byte in _FORBIDDEN_BODY_BYTES:
            raise BodyValidationError(
                BODY_INVALID_CHARS,
                f"body contains disallowed byte 0x{byte:02x} "
                f"(only \\n and \\t are allowed among ASCII controls)",
            )


def render_envelope(
    message_id: str,
    sender: EnvelopeIdentity,
    target: EnvelopeIdentity,
    body_bytes: bytes,
) -> bytes:
    """Produce the FR-001 envelope as raw bytes.

    Does NOT validate the body — call :func:`validate_body` first (the
    typical caller chain is ``validate_body → render_envelope →
    serialize_and_check_size``). The header text is built from
    ASCII-safe fields (FEAT-006 invariant on labels / capabilities) and
    encoded as UTF-8; the body is appended VERBATIM as bytes.

    The blank line separator (``\\n\\n``) is between the last header
    and the body (FR-002).
    """
    sender_cap = f" [capability={sender.capability}]" if sender.capability else ""
    target_cap = f" [capability={target.capability}]" if target.capability else ""
    headers = (
        f"Message-Id: {message_id}\n"
        f'From: {sender.agent_id} "{sender.label}" {sender.role}{sender_cap}\n'
        f'To: {target.agent_id} "{target.label}" {target.role}{target_cap}\n'
        "Type: prompt\n"
        "Priority: normal\n"
        "Requires-Reply: yes\n"
        "\n"
    )
    return headers.encode("utf-8") + body_bytes


def serialize_and_check_size(
    message_id: str,
    sender: EnvelopeIdentity,
    target: EnvelopeIdentity,
    body_bytes: bytes,
    *,
    max_bytes: int = DEFAULT_ENVELOPE_BODY_MAX_BYTES,
) -> bytes:
    """Validate the body, render the envelope, and check the FR-004 size cap.

    Returns the rendered envelope bytes on success. Raises
    :class:`BodyValidationError` with the matching closed-set code on
    any of the four failure modes:

    * Body validation rejection → ``body_empty`` / ``body_invalid_encoding``
      / ``body_invalid_chars``.
    * Serialized envelope length exceeds ``max_bytes`` → ``body_too_large``.

    The size check applies to the SERIALIZED envelope (headers + body),
    not the raw body, per FR-004 — this prevents an attacker from
    stuffing the body cap full of header-shaped junk.
    """
    validate_body(body_bytes)
    rendered = render_envelope(message_id, sender, target, body_bytes)
    if len(rendered) > max_bytes:
        raise BodyValidationError(
            BODY_TOO_LARGE,
            f"serialized envelope is {len(rendered)} bytes; max {max_bytes}",
        )
    return rendered
