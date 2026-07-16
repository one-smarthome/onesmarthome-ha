"""The value type that flows between the CLU and Home Assistant, plus coercion.

CLU values travel as text. Once decoded we turn each token into the closest
native Python type so entities can use it directly.
"""

from __future__ import annotations

from dataclasses import dataclass

# Anything a CLU variable/attribute can hold once typed.
OshValue = str | bool | int | float | None


def coerce_value(token: object) -> OshValue:
    """Turn a raw wire token into a typed value.

    Non-string inputs pass straight through; strings are de-quoted then matched
    against ``nil``/``true``/``false`` before falling back to int, float, str.
    """
    if not isinstance(token, str):
        return token  # type: ignore[return-value]

    text = token.strip().strip('"')
    lowered = text.lower()
    if lowered == "nil":
        return None
    if lowered == "true":
        return True
    if lowered == "false":
        return False

    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        return text


@dataclass(frozen=True)
class Report:
    """A parsed ``clientReport`` payload: its session id and positional values."""

    session_id: int | None
    values: list[OshValue]


def _split_values(inner: str) -> list[str]:
    """Split a brace-list body on top-level commas, honouring quoted strings.

    A quoted value may itself contain commas; splitting on those would shift
    every following slot, so only commas outside quotes separate values.
    """
    items: list[str] = []
    current: list[str] = []
    in_quotes = False
    for char in inner:
        if char == '"':
            in_quotes = not in_quotes
            current.append(char)
        elif char == "," and not in_quotes:
            items.append("".join(current))
            current = []
        else:
            current.append(char)
    items.append("".join(current))
    return items


def parse_report(payload: str) -> Report | None:
    """Parse a ``clientReport:<session-id>:{a,b,c}`` payload.

    Returns None for anything that is not a well-formed brace-wrapped report
    body. A session id that is not numeric survives as None so the caller can
    decide what to do with an unattributable report.
    """
    if not payload.startswith("clientReport:"):
        return None

    # clientReport : <session-id> : <brace-list>  -> keep the body whole.
    parts = payload.split(":", 2)
    if len(parts) != 3:
        return None

    try:
        session_id: int | None = int(parts[1].strip())
    except ValueError:
        session_id = None

    body = parts[2]
    if not (body.startswith("{") and body.endswith("}")):
        return None

    inner = body[1:-1].strip()
    if not inner:
        return Report(session_id=session_id, values=[])

    values = [coerce_value(item.strip().strip('"')) for item in _split_values(inner)]
    return Report(session_id=session_id, values=values)
