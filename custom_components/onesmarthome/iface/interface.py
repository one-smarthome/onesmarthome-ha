"""Top-of-tree view over the downloaded interface JSON.

The Object Manager export is a deep dict describing CLUs, shared crypto, and a
list of UI pages that each own a handful of widget tiles. The integration only
ever needs three things out of it: how to reach and decrypt each CLU, and a
single flat roster of widgets to turn into entities. :func:`parse_interface`
pulls exactly those out and discards everything else (themes, icons, page
grouping, push declarations).

A widget whose ``type`` is unsupported makes :func:`parse_widget` raise; that is
caught per tile here so a single odd widget is dropped rather than failing the
whole import.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from .widgets import Widget, parse_widget

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class Encryption:
    """Base64 AES-CBC material shared by every CLU in this interface."""

    key: str
    iv: str


@dataclass(frozen=True)
class Clu:
    """Everything needed to open and address one CLU's UDP endpoint."""

    clu_id: str
    name: str
    ip: str
    port: int
    serial: str


@dataclass(frozen=True)
class Interface:
    """The parts of the export the integration actually consumes."""

    interface_id: str
    encryption: Encryption
    clus: tuple[Clu, ...]
    widgets: tuple[Widget, ...]


def _encryption(raw: dict) -> Encryption:
    return Encryption(key=raw["key"], iv=raw["iv"])


def _clu(raw: dict) -> Clu:
    return Clu(
        clu_id=raw["id"],
        name=raw["name"],
        ip=raw["ip"],
        # Some exports serialise the port as a string.
        port=int(raw["port"]),
        serial=raw["serialNumber"],
    )


def _widgets(raw: dict) -> tuple[Widget, ...]:
    widgets: list[Widget] = []
    for page in raw["pages"]:
        for tile in page.get("widgets", []):
            try:
                widgets.append(parse_widget(tile))
            except Exception:  # noqa: BLE001 - one bad tile must not sink the load
                _LOGGER.debug("Dropping unsupported widget: %s", tile.get("type"))
    return tuple(widgets)


def parse_interface(raw: dict) -> Interface:
    """Build the trimmed :class:`Interface` from the raw export dict."""
    return Interface(
        interface_id=str(raw["id"]),
        encryption=_encryption(raw["encryption"]),
        clus=tuple(_clu(c) for c in raw["clus"]),
        widgets=_widgets(raw),
    )
