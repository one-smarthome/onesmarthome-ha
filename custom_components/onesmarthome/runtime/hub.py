"""The shared data source every entity reads from and writes through.

One :class:`GrentonHub` per config entry owns the UDP connection to each CLU and
the in-memory :class:`StateStore` that mirrors their values. It is a
``DataUpdateCoordinator`` so HA entities can subscribe and re-render whenever the
mirror changes, but it never polls: fresh data arrives either as the reply to a
periodic re-subscription or as an unsolicited push report, and both paths apply
values positionally against the CLU's full subscription order.

The hub also judges each CLU's health: a run of failed pings marks the CLU
offline (entities show as unavailable), and the first successful exchange
afterwards brings it back, re-registering its subscriptions right away.

Two long-lived tasks run while the entry is loaded:

* a keep-alive loop that pings every CLU so it keeps streaming reports, and
* a re-subscribe loop that re-registers the tracked slots, because a CLU forgets
  its subscriptions after a while.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Coroutine
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from ..const import (
    DOMAIN,
    KEEPALIVE_INTERVAL,
    PING_FAIL_THRESHOLD,
    RESUBSCRIBE_INTERVAL,
)
from ..iface import Clu, Encryption
from ..protocol.cipher import DatagramCipher
from ..protocol.clu_client import CluClient
from .action import WriteAction
from .state import StateStore
from .state_object import ReadTarget
from .values import OshValue

_LOGGER = logging.getLogger(__name__)


class GrentonHub(DataUpdateCoordinator[StateStore]):
    """Connections, background loops and the read/write API for one entry."""

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        clus: list[Clu],
        encryption: Encryption,
    ) -> None:
        super().__init__(hass, _LOGGER, name=DOMAIN)
        self.config_entry = config_entry

        cipher = DatagramCipher(encryption.key, encryption.iv)
        self._store = StateStore([clu.clu_id for clu in clus])
        self._clients: dict[str, CluClient] = {}
        for clu in clus:
            client = CluClient(clu.clu_id, clu.name, clu.ip, clu.port, cipher)
            client.on_report = self._report_handler(clu.clu_id)
            self._clients[clu.clu_id] = client

        self._tasks: list[asyncio.Task[None]] = []
        # Short-lived fire-and-forget work (e.g. the prompt re-register after a
        # CLU comes back) stays referenced here until it finishes.
        self._misc_tasks: set[asyncio.Task[None]] = set()
        # CLU health: consecutive failed pings, the resulting online flag, and
        # when each CLU last pushed a report (monotonic clock).
        self._ping_failures: dict[str, int] = {clu.clu_id: 0 for clu in clus}
        self._clu_online: dict[str, bool] = {clu.clu_id: True for clu in clus}
        self._last_report: dict[str, float] = {}
        # Re-registration replaces a CLU's subscription sockets, so two runs
        # for the same CLU must never interleave.
        self._register_locks: dict[str, asyncio.Lock] = {
            clu.clu_id: asyncio.Lock() for clu in clus
        }

    async def _async_update_data(self) -> StateStore:
        # Updates are push-driven; the periodic refresh just returns the mirror.
        return self._store

    # --- read/write API entities and channels use --------------------------

    def subscribe(self, target: ReadTarget) -> None:
        """Declare that some entity tracks ``target``; called at entity build."""
        self._store.subscribe(target)

    def read(self, target: ReadTarget) -> OshValue | None:
        """Latest cached value for ``target`` (synchronous, no I/O)."""
        return self._store.read(target)

    async def send(self, action: WriteAction) -> bool:
        """Execute one write action against its owning CLU."""
        client = self._clients.get(action.clu_id)
        if client is None:
            _LOGGER.warning("[%s] no client for action", action.clu_id)
            return False
        return await client.send_action(action)

    # --- CLU health ---------------------------------------------------------

    def clu_available(self, clu_id: str) -> bool:
        """Whether ``clu_id`` is currently considered reachable."""
        return self._clu_online.get(clu_id, False)

    def _mark_alive(self, clu_id: str) -> None:
        """Record a successful exchange; brings an offline CLU back online."""
        self._ping_failures[clu_id] = 0
        if self._clu_online.get(clu_id, True):
            return
        self._clu_online[clu_id] = True
        _LOGGER.info("[%s] back online; re-registering subscriptions", clu_id)
        # Refresh this CLU's subscriptions right away instead of waiting out
        # the resubscribe interval, and let entities re-render as available.
        self._spawn(self._register(clu_id))
        self.async_set_updated_data(self._store)

    def _mark_ping_failed(self, clu_id: str) -> None:
        """Count one failed ping; enough in a row takes the CLU offline."""
        failures = self._ping_failures.get(clu_id, 0) + 1
        self._ping_failures[clu_id] = failures
        if failures < PING_FAIL_THRESHOLD or not self._clu_online.get(clu_id, False):
            return
        self._clu_online[clu_id] = False
        _LOGGER.warning("[%s] offline after %d failed pings", clu_id, failures)
        self.async_set_updated_data(self._store)

    def _spawn(self, coro: Coroutine[Any, Any, None]) -> None:
        """Run ``coro`` as a background task kept referenced until it is done."""
        task = asyncio.create_task(coro)
        self._misc_tasks.add(task)
        task.add_done_callback(self._misc_tasks.discard)

    # --- report ingestion --------------------------------------------------

    def _report_handler(self, clu_id: str):
        async def handle(values: list[OshValue]) -> None:
            self._apply_report(clu_id, values)

        return handle

    def _apply_report(self, clu_id: str, values: list[OshValue]) -> None:
        store = self._store.clu(clu_id)
        if store is None:
            return
        keys = store.ordered_keys()
        _LOGGER.debug(
            "[%s] push report: %d value(s) for %d subscribed key(s)",
            clu_id,
            len(values),
            len(keys),
        )
        self._last_report[clu_id] = time.monotonic()
        self._mark_alive(clu_id)
        store.apply_chunk(keys, values)
        self.async_set_updated_data(self._store)

    # --- lifecycle ---------------------------------------------------------

    async def async_setup(self) -> None:
        """Connect every CLU, prime values once, then start the loops."""
        await asyncio.gather(
            *(client.connect() for client in self._clients.values()),
            return_exceptions=True,
        )
        await self._ping_all()
        await self._register_all()
        self._tasks = [
            asyncio.create_task(self._keepalive_loop()),
            asyncio.create_task(self._resubscribe_loop()),
        ]

    async def async_shutdown(self) -> None:
        """Cancel the loops and close every socket."""
        for task in [*self._tasks, *self._misc_tasks]:
            task.cancel()
        for task in [*self._tasks, *self._misc_tasks]:
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._tasks = []
        self._misc_tasks.clear()
        for client in self._clients.values():
            client.disconnect()

    # --- background work ---------------------------------------------------

    async def _ping_all(self) -> None:
        await asyncio.gather(
            *(self._ping(clu_id) for clu_id in self._clients),
            return_exceptions=True,
        )

    async def _ping(self, clu_id: str) -> None:
        try:
            alive = await self._clients[clu_id].ping()
        except Exception:  # noqa: BLE001 - one bad ping must not break the loop
            _LOGGER.exception("[%s] ping error", clu_id)
            alive = False
        if alive:
            self._mark_alive(clu_id)
        else:
            _LOGGER.warning("[%s] ping failed", clu_id)
            self._mark_ping_failed(clu_id)

    async def _register_all(self) -> None:
        await asyncio.gather(
            *(self._register(clu_id) for clu_id in self._clients),
            return_exceptions=True,
        )

    async def _register(self, clu_id: str) -> None:
        store = self._store.clu(clu_id)
        if store is None or not store.has_subscriptions:
            return
        client = self._clients[clu_id]
        keys = store.ordered_keys()
        async with self._register_locks[clu_id]:
            try:
                values = await client.register(keys)
            except Exception:  # noqa: BLE001 - keep the loop alive on a bad round
                _LOGGER.exception("[%s] register error", clu_id)
                return
        if values is None:
            _LOGGER.warning(
                "[%s] registration of %d key(s) not confirmed", clu_id, len(keys)
            )
            return
        self._last_report[clu_id] = time.monotonic()
        self._mark_alive(clu_id)
        store.apply_chunk(keys, values)
        self.async_set_updated_data(self._store)

    async def _keepalive_loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(KEEPALIVE_INTERVAL)
                await self._ping_all()
            except asyncio.CancelledError:
                break
            except Exception:  # noqa: BLE001
                _LOGGER.exception("keepalive loop error")

    async def _resubscribe_loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(RESUBSCRIBE_INTERVAL)
                await self._register_all()
            except asyncio.CancelledError:
                break
            except Exception:  # noqa: BLE001
                _LOGGER.exception("resubscribe loop error")

    # --- introspection -------------------------------------------------------

    def clu_diagnostics(self) -> dict[str, dict[str, Any]]:
        """Per-CLU health snapshot for the diagnostics download."""
        now = time.monotonic()
        snapshot: dict[str, dict[str, Any]] = {}
        for clu_id in self._clients:
            store = self._store.clu(clu_id)
            subscriptions = len(store.ordered_keys()) if store is not None else 0
            chunks = len(store.chunks()) if store is not None else 0
            last = self._last_report.get(clu_id)
            snapshot[clu_id] = {
                "available": self.clu_available(clu_id),
                "ping_failures": self._ping_failures.get(clu_id, 0),
                "subscriptions": subscriptions,
                "chunks": chunks,
                "last_report_age_s": round(now - last, 1) if last is not None else None,
            }
        return snapshot
