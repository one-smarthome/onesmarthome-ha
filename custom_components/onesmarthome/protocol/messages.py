"""Building and parsing the CLU's text wire format.

Decrypted datagrams are colon-delimited UTF-8::

    request   req::<msg-id>:<lua-payload>
    response  resp:<clu-ip>:<msg-id>:<payload>

The payload itself may contain colons, so responses are split with a cap of
three. Reports the CLU pushes unprompted reuse the response shape with a
``clientReport:`` payload; neither their id slot nor the in-payload id is
reliable, so reports are recognised by payload alone and routed by the socket
they arrive on.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass

from ..const import (
    CLIENT_REPORT_TAG,
    RESPONSE_PREFIX,
)
from ..runtime.action import WriteAction
from ..runtime.state import AttributeKey, SubscriptionKey, VariableKey

PING_PAYLOAD = "checkAlive()"


def new_message_id() -> str:
    """A fresh 8-hex-char request id (lower case for case-insensitive match)."""
    return secrets.token_hex(4)


def build_request(payload: str, msg_id: str | None = None) -> tuple[str, str]:
    """Return ``(msg_id, wire_string)`` for a request carrying ``payload``."""
    mid = (msg_id or new_message_id()).lower()
    return mid, f"req::{mid}:{payload}"


def build_ping(msg_id: str | None = None) -> tuple[str, str]:
    return build_request(PING_PAYLOAD, msg_id)


def _render_key(key: SubscriptionKey) -> str:
    # Variables register as a quoted name; attributes as a bare {object,name}.
    if isinstance(key, VariableKey):
        return f'"{key.name}"'
    return f"{{{key.object_name},{key.name}}}"


def build_register(keys: list[SubscriptionKey], msg_id: str | None = None) -> tuple[str, str]:
    """Build a subscription request for the given ordered keys.

    The exact v1.0.0 wire form (session slot 0): the CLU pushes the resulting
    clientReport notifications to the ip:port this request came from, and the
    values line up positionally against ``keys``.
    """
    if not keys:
        raise ValueError("refusing to build an empty registration")
    body = ",".join(_render_key(k) for k in keys)
    return build_request(f"SYSTEM:clientRegister(0,0,1,{{{body}}})", msg_id)


def build_action(action: WriteAction, msg_id: str | None = None) -> tuple[str, str]:
    """Build a write request from a runtime action."""
    return build_request(_action_payload(action), msg_id)


def _action_payload(action: WriteAction) -> str:
    if action.kind == "script":
        # Scripts take their value verbatim as call arguments.
        return f"{action.object_name}({action.value})"

    # The other verbs re-wrap the value in quotes, so strip any it already has.
    value = action.value.strip('"')
    if action.kind == "variable":
        return f'setVar("{action.index}","{value}")'
    if action.kind == "attribute":
        return f'{action.object_name}:set({action.index},"{value}")'
    if action.kind == "method":
        return f'{action.object_name}:execute({action.index},"{value}")'
    raise ValueError(f"unknown action kind: {action.kind!r}")


@dataclass(frozen=True)
class Response:
    """A parsed inbound datagram."""

    clu_ip: str
    msg_id: str
    payload: str

    @property
    def is_report(self) -> bool:
        """True if this carries a subscription report payload."""
        return self.payload.startswith(f"{CLIENT_REPORT_TAG}:")


def parse_response(wire: str) -> Response | None:
    """Parse a decrypted datagram, or None if it is not a valid response."""
    if not wire.startswith(RESPONSE_PREFIX):
        return None
    parts = wire.split(":", 3)
    if len(parts) != 4:
        return None
    _, clu_ip, msg_id, payload = parts
    return Response(clu_ip=clu_ip, msg_id=msg_id.lower(), payload=payload)
