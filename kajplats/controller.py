"""Bridge between the Qt main thread and the backend's asyncio loop.

Qt widgets may only be touched from the GUI thread, and the WebSocket client
may only be driven from its own event loop, so the controller owns a worker
thread running asyncio and translates in both directions: UI calls go in as
coroutines, backend state comes back out as Qt signals (which Qt queues across
threads for us).

Dragging a colour wheel or a slider produces hundreds of values per second,
far more than a Thread mesh will absorb. Each bulb/channel pair therefore gets
a "rail" that keeps at most one command in flight, discards superseded values,
and spaces sends out — so the bulb always ends up at the value you released
on, without a backlog of stale ones arriving afterwards.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import Awaitable, Callable

from PySide6.QtCore import QObject, Signal

from .model import Bulb

LOGGER = logging.getLogger(__name__)

CoroFactory = Callable[[], Awaitable[None]]

#: Minimum spacing between two sends on the same channel, in seconds.
RAIL_INTERVAL = 0.06


class _Rail:
    """One serialised, rate-limited command channel. Newest value wins."""

    def __init__(self, min_interval: float = RAIL_INTERVAL) -> None:
        self._min_interval = min_interval
        self._pending: CoroFactory | None = None
        self._wake = asyncio.Event()
        self._task = asyncio.create_task(self._pump())
        self.on_error: Callable[[Exception], None] | None = None

    def submit(self, factory: CoroFactory) -> None:
        """Replace any not-yet-sent command on this channel. Loop-thread only."""
        self._pending = factory
        self._wake.set()

    def close(self) -> None:
        self._task.cancel()

    async def _pump(self) -> None:
        while True:
            await self._wake.wait()
            self._wake.clear()
            factory, self._pending = self._pending, None
            if factory is None:
                continue
            try:
                await factory()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                LOGGER.warning("command failed: %s", exc)
                if self.on_error is not None:
                    self.on_error(exc)
            await asyncio.sleep(self._min_interval)


class Controller(QObject):
    """Thread-safe facade the UI talks to."""

    stateChanged = Signal(list, bool, str)  # list[Bulb], connected, detail
    errorRaised = Signal(str)
    noticePosted = Signal(str)

    def __init__(self, backend) -> None:
        super().__init__()
        self._backend = backend
        self._loop = asyncio.new_event_loop()
        self._ready = threading.Event()
        self._rails: dict[tuple[str, str], _Rail] = {}
        self._closed = False
        self._thread = threading.Thread(
            target=self._run_loop, name="kajplats-io", daemon=True
        )
        backend.on_state(self._on_state)

    @property
    def backend(self):
        return self._backend

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        self._thread.start()
        self._ready.wait(timeout=5)
        self._call(self._start_backend())

    def shutdown(self) -> None:
        """Close the backend and stop the worker thread. Safe to call twice."""
        if self._closed or not self._thread.is_alive():
            return
        self._closed = True

        async def teardown() -> None:
            for rail in self._rails.values():
                rail.close()
            self._rails.clear()
            # Give the cancelled rail tasks a cycle to actually unwind before
            # the loop stops underneath them.
            await asyncio.sleep(0)
            try:
                await self._backend.stop()
            except Exception as exc:
                LOGGER.warning("backend shutdown failed: %s", exc)

        try:
            asyncio.run_coroutine_threadsafe(teardown(), self._loop).result(timeout=3)
        except Exception as exc:
            LOGGER.warning("shutdown timed out: %s", exc)
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=3)

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.call_soon(self._ready.set)
        try:
            self._loop.run_forever()
        finally:
            self._loop.close()

    async def _start_backend(self) -> None:
        try:
            await self._backend.start()
        except Exception as exc:
            LOGGER.error("backend failed to start: %s", exc)
            self.stateChanged.emit([], False, str(exc))
            self.errorRaised.emit(f"Could not reach the bulbs: {exc}")

    # -- state in ----------------------------------------------------------

    def _on_state(self, bulbs: list[Bulb], connected: bool, detail: str) -> None:
        # Called on the asyncio thread; Qt marshals this to the GUI thread.
        self.stateChanged.emit(list(bulbs), connected, detail)

    # -- commands out ------------------------------------------------------

    def set_power(self, bulb: Bulb, on: bool) -> None:
        self._rail(bulb, "power", lambda: self._backend.set_power(bulb, on))

    def set_level(self, bulb: Bulb, level: int) -> None:
        self._rail(bulb, "level", lambda: self._backend.set_level(bulb, level))

    def set_hs(self, bulb: Bulb, hue: int, saturation: int) -> None:
        self._rail(bulb, "color", lambda: self._backend.set_hs(bulb, hue, saturation))

    def set_ct(self, bulb: Bulb, mireds: int) -> None:
        # Shares the "color" rail with hue/saturation: the two are alternative
        # ways of driving the same output, so a later one should win outright.
        self._rail(bulb, "color", lambda: self._backend.set_ct(bulb, mireds))

    def refresh(self) -> None:
        self._call(self._guarded(self._backend.refresh()))

    def commission(self, code: str) -> None:
        async def run() -> None:
            try:
                message = await self._backend.commission(code)
            except Exception as exc:
                self.errorRaised.emit(f"Commissioning failed: {exc}")
            else:
                self.noticePosted.emit(message)

        self._call(run())

    def set_thread_dataset(self, dataset: str) -> None:
        async def run() -> None:
            try:
                await self._backend.set_thread_dataset(dataset)
            except Exception as exc:
                self.errorRaised.emit(f"Could not set Thread dataset: {exc}")
            else:
                self.noticePosted.emit("Thread dataset stored on the server")

        self._call(run())

    # -- plumbing ----------------------------------------------------------

    def _rail(self, bulb: Bulb, channel: str, factory: CoroFactory) -> None:
        def install() -> None:
            key = (bulb.key, channel)
            rail = self._rails.get(key)
            if rail is None:
                rail = _Rail()
                rail.on_error = lambda exc: self.errorRaised.emit(str(exc))
                self._rails[key] = rail
            rail.submit(factory)

        self._loop.call_soon_threadsafe(install)

    async def _guarded(self, awaitable: Awaitable[None]) -> None:
        try:
            await awaitable
        except Exception as exc:
            self.errorRaised.emit(str(exc))

    def _call(self, coro: Awaitable[None]) -> None:
        asyncio.run_coroutine_threadsafe(coro, self._loop)
