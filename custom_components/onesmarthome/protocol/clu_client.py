"""UDP client for a single CLU.

One persistent UDP socket per CLU carries ALL of its traffic: the periodic
keep-alive ping (stable message id), the periodic clientRegister of every
subscribed key (stable message id, session slot 0) and write actions. This is
byte-for-byte the traffic layout of v1.0.0 — the only configuration the main
CLU generation here has been proven to keep streaming push reports to (its
keep-alive is what keeps the CLU-side registration alive, so the ping must
come from the same ip:port that registered). Replies are correlated to
requests by the echoed message id; any unmatched datagram carrying a
clientReport payload is a push and goes to :pyattr:`on_report`.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Coroutine

from ..const import RESPONSE_TIMEOUT
from ..runtime.action import WriteAction
from ..runtime.state import SubscriptionKey
from ..runtime.values import OshValue, parse_report
from . import messages
from .cipher import DatagramCipher

_LOGGER = logging.getLogger(__name__)

# Called with the freshly reported values, positional against the full
# subscription order of this CLU.
ReportHandler = Callable[[list[OshValue]], Awaitable[None]]


class CluClient:
    """Talks to one CLU over its encrypted UDP API."""

    def __init__(
        self,
        clu_id: str,
        name: str,
        ip: str,
        port: int,
        cipher: DatagramCipher,
    ) -> None:
        self.clu_id = clu_id
        self.name = name
        self.ip = ip
        self.port = port
        self._cipher = cipher
        # Stable ids for the recurring ping/subscribe traffic from this client.
        self._ping_id = messages.new_message_id()
        self._register_id = messages.new_message_id()
        self._transport: asyncio.DatagramTransport | None = None
        self._protocol: "_CluProtocol | None" = None
        self.on_report: ReportHandler | None = None

    async def connect(self) -> bool:
        loop = asyncio.get_running_loop()
        try:
            self._protocol = _CluProtocol(self)
            self._transport, _ = await loop.create_datagram_endpoint(
                lambda: self._protocol,
                local_addr=("0.0.0.0", 0),
            )
        except OSError as err:
            _LOGGER.error("[%s] could not open UDP socket: %s", self.name, err)
            return False
        _LOGGER.debug("[%s] UDP socket open -> %s:%d", self.name, self.ip, self.port)
        return True

    def disconnect(self) -> None:
        if self._transport is not None:
            self._transport.close()
            self._transport = None

    async def ping(self) -> bool:
        _, wire = messages.build_ping(self._ping_id)
        return await self._exchange(self._ping_id, wire) is not None

    async def register(self, keys: list[SubscriptionKey]) -> list[OshValue] | None:
        """Register ``keys`` as this client's one subscription session.

        Returns their initial values, or None when the registration was not
        confirmed (the caller should keep whatever values it already holds).
        """
        if not keys:
            return None
        _, wire = messages.build_register(keys, self._register_id)
        reply = await self._exchange(self._register_id, wire)
        if reply is None:
            return None
        parsed = messages.parse_response(reply)
        if parsed is None:
            return None
        report = parse_report(parsed.payload)
        if report is None:
            return None
        _LOGGER.debug("[%s] registered %d key(s)", self.name, len(keys))
        return report.values

    async def send_action(self, action: WriteAction) -> bool:
        msg_id, wire = messages.build_action(action)
        return await self._exchange(msg_id, wire) is not None

    async def _exchange(self, msg_id: str, wire: str) -> str | None:
        if self._protocol is None or self._transport is None:
            _LOGGER.warning("[%s] transport not connected", self.name)
            return None
        return await self._protocol.request(msg_id, wire)

    # Used by the protocol callback.
    def _decrypt(self, data: bytes) -> bytes | None:
        return self._cipher.decrypt(data)

    def _encrypt(self, data: bytes) -> bytes | None:
        return self._cipher.encrypt(data)

    def _send(self, data: bytes) -> None:
        assert self._transport is not None
        self._transport.sendto(data, (self.ip, self.port))


class _CluProtocol(asyncio.DatagramProtocol):
    """Correlates UDP replies with awaiting requests for one CluClient."""

    def __init__(self, client: CluClient) -> None:
        self._client = client
        self._pending: dict[str, asyncio.Future[str]] = {}
        self._lock = asyncio.Lock()
        # Fire-and-forget tasks stay referenced here until done so the garbage
        # collector can never drop one mid-flight.
        self._tasks: set[asyncio.Task[None]] = set()

    def _spawn(self, coro: Coroutine[None, None, None]) -> None:
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def datagram_received(self, data: bytes, _addr: tuple[str, int]) -> None:
        plain = self._client._decrypt(data)
        if plain is None:
            _LOGGER.warning("[%s] undecryptable datagram dropped", self._client.name)
            return
        try:
            wire = plain.decode().strip()
        except UnicodeDecodeError:
            _LOGGER.warning("[%s] non-text datagram dropped", self._client.name)
            return

        parsed = messages.parse_response(wire)
        if parsed is None:
            _LOGGER.debug("[%s] ignored: %s", self._client.name, wire)
            return
        self._spawn(self._dispatch(parsed, wire))

    async def _dispatch(self, parsed: messages.Response, wire: str) -> None:
        async with self._lock:
            future = self._pending.pop(parsed.msg_id, None)

        if future is not None and not future.done():
            future.set_result(wire)
            return

        # No awaiting request: only an unsolicited report is interesting.
        if not parsed.is_report:
            _LOGGER.debug(
                "[%s][%s] unmatched response dropped", self._client.name, parsed.msg_id
            )
            return
        if self._client.on_report is None:
            return
        report = parse_report(parsed.payload)
        if report is not None:
            await self._client.on_report(report.values)

    async def request(self, msg_id: str, wire: str) -> str | None:
        payload = self._client._encrypt(wire.encode())
        if payload is None:
            _LOGGER.error("[%s] could not encrypt request", self._client.name)
            return None

        loop = asyncio.get_running_loop()
        future: asyncio.Future[str] = loop.create_future()
        async with self._lock:
            self._pending[msg_id] = future

        try:
            self._client._send(payload)
        except OSError as err:
            async with self._lock:
                self._pending.pop(msg_id, None)
            _LOGGER.error("[%s] send failed: %s", self._client.name, err)
            return None

        try:
            return await asyncio.wait_for(future, timeout=RESPONSE_TIMEOUT)
        except asyncio.TimeoutError:
            async with self._lock:
                self._pending.pop(msg_id, None)
            _LOGGER.warning("[%s][%s] request timed out", self._client.name, msg_id)
            return None
        except ConnectionError:
            # The socket was closed under us (shutdown/reload).
            async with self._lock:
                self._pending.pop(msg_id, None)
            return None

    def connection_lost(self, exc: Exception | None) -> None:
        if exc is not None:
            _LOGGER.debug("[%s] connection lost: %s", self._client.name, exc)

        async def _drain() -> None:
            async with self._lock:
                pending = list(self._pending.values())
                self._pending.clear()
            for future in pending:
                if not future.done():
                    future.set_exception(ConnectionError("UDP socket closed"))

        self._spawn(_drain())
