"""Typed view over the downloaded Object Manager interface JSON.

The raw ``data.json`` is a deep dict tree. This package turns the parts the
integration actually uses into small frozen dataclasses: connection details for
each CLU, the shared AES material, and one flat list of widgets (the per-page
grouping is irrelevant once entities exist). Widgets that name an unsupported
type are skipped rather than aborting the whole load.
"""

from __future__ import annotations

from .interface import Clu, Encryption, Interface, parse_interface

__all__ = ["Clu", "Encryption", "Interface", "parse_interface"]
