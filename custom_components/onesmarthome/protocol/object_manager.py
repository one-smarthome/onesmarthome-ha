"""HTTP client that downloads the interface definition from Object Manager.

Grenton's Object Manager serves the whole interface as a ZIP whose single
``mygrenton/data.json`` entry holds the JSON we parse. The token doubles as the
URL hash. Failures are sorted into three typed errors so the config flow can
show the right message.
"""

from __future__ import annotations

import io
import json
import logging
import zipfile
from typing import Any

import aiohttp

_LOGGER = logging.getLogger(__name__)

_INTERFACE_ENTRY = "mygrenton/data.json"


class ObjectManagerAuthError(Exception):
    """The access token was rejected (HTTP 401)."""


class ObjectManagerConnectionError(Exception):
    """The Object Manager was unreachable or returned an unexpected status."""


class ObjectManagerDataError(Exception):
    """The downloaded archive or its JSON could not be parsed."""


class ObjectManagerClient:
    """Fetches and unpacks the interface definition over HTTP."""

    def __init__(self, base_url: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._session: aiohttp.ClientSession | None = None

    async def __aenter__(self) -> "ObjectManagerClient":
        self._session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, *_exc: object) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None

    async def fetch_interface(self, token: str) -> dict[str, Any]:
        """Download and decode the interface JSON for ``token``."""
        if self._session is None:
            raise RuntimeError("use ObjectManagerClient as an async context manager")

        url = f"{self._base_url}/api/v1/interface/hash/{token}"
        try:
            async with self._session.get(url) as resp:
                if resp.status == 200:
                    return self._unpack(await resp.read())
                if resp.status == 401:
                    raise ObjectManagerAuthError("token rejected")
                raise ObjectManagerConnectionError(f"HTTP {resp.status}")
        except aiohttp.ClientError as err:
            raise ObjectManagerConnectionError(str(err)) from err

    @staticmethod
    def _unpack(archive: bytes) -> dict[str, Any]:
        try:
            with zipfile.ZipFile(io.BytesIO(archive)) as zf:
                _LOGGER.debug("interface archive entries: %s", zf.namelist())
                if _INTERFACE_ENTRY not in zf.namelist():
                    raise ObjectManagerDataError(f"archive missing {_INTERFACE_ENTRY}")
                with zf.open(_INTERFACE_ENTRY) as handle:
                    return json.loads(handle.read().decode("utf-8"))
        except zipfile.BadZipFile as err:
            raise ObjectManagerDataError("not a valid ZIP archive") from err
        except json.JSONDecodeError as err:
            raise ObjectManagerDataError("interface JSON is malformed") from err
