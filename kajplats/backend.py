"""Backend interface, plus an offline simulator that implements it.

A backend is the thing that actually talks to bulbs. It is deliberately thin:
four setters, a refresh, and a callback it fires whenever its view of a bulb
changes. The UI never knows which implementation it is driving, so the mock
backend below is a complete stand-in while no Thread radio is attached.
"""

from __future__ import annotations

import asyncio
import random
from abc import ABC, abstractmethod
from typing import Awaitable, Callable

from .model import Bulb, ColorMode, LEVEL_MAX, kelvin_to_mireds

StateCallback = Callable[[list[Bulb], bool, str], Awaitable[None] | None]


class Backend(ABC):
    """Abstract bulb transport."""

    def __init__(self) -> None:
        self._listener: StateCallback | None = None

    def on_state(self, listener: StateCallback) -> None:
        self._listener = listener

    def _publish(self, bulbs: list[Bulb], connected: bool, detail: str = "") -> None:
        if self._listener is not None:
            self._listener(bulbs, connected, detail)

    @abstractmethod
    async def start(self) -> None:
        """Connect and perform an initial discovery."""

    @abstractmethod
    async def stop(self) -> None:
        """Release connections."""

    @abstractmethod
    async def refresh(self) -> None:
        """Re-read state from the devices."""

    @abstractmethod
    async def set_power(self, bulb: Bulb, on: bool) -> None: ...

    @abstractmethod
    async def set_level(self, bulb: Bulb, level: int) -> None:
        """`level` is Matter's 1-254 brightness scale."""

    @abstractmethod
    async def set_hs(self, bulb: Bulb, hue: int, saturation: int) -> None:
        """`hue` and `saturation` are Matter's 0-254 scale."""

    @abstractmethod
    async def set_ct(self, bulb: Bulb, mireds: int) -> None: ...

    @property
    def can_commission(self) -> bool:
        return False

    async def commission(self, code: str) -> str:
        raise NotImplementedError


class MockBackend(Backend):
    """Simulates two KAJPLATS colour/white-spectrum bulbs.

    Mirrors the real backend's behaviour closely enough to build and tune the
    whole interface against: it echoes commands back as state changes after a
    short delay, and it models the physical colour-temperature range of the
    E26/E27 colour and white spectrum bulb.
    """

    #: Roughly the KAJPLATS CWS range: 2202 K to 6536 K.
    CT_MIN = 153
    CT_MAX = 454

    def __init__(self, count: int = 2, latency: float = 0.04) -> None:
        super().__init__()
        self._latency = latency
        self._bulbs: dict[str, Bulb] = {}
        for index in range(count):
            bulb = Bulb(
                node_id=index + 1,
                endpoint_id=1,
                name=f"KAJPLATS {index + 1}",
                on=True,
                level=LEVEL_MAX,
                mireds=kelvin_to_mireds(2700),
                mode=ColorMode.CT,
                ct_min=self.CT_MIN,
                ct_max=self.CT_MAX,
                vendor="IKEA of Sweden",
                product="KAJPLATS_CWS",
            )
            self._bulbs[bulb.key] = bulb

    # -- lifecycle ----------------------------------------------------------

    async def start(self) -> None:
        await asyncio.sleep(0.1)
        self._emit("simulator — no radio attached")

    async def stop(self) -> None:
        return None

    async def refresh(self) -> None:
        self._emit("simulator — no radio attached")

    # -- commands -----------------------------------------------------------

    async def set_power(self, bulb: Bulb, on: bool) -> None:
        await self._apply(bulb, on=on)

    async def set_level(self, bulb: Bulb, level: int) -> None:
        await self._apply(bulb, level=level)

    async def set_hs(self, bulb: Bulb, hue: int, saturation: int) -> None:
        await self._apply(bulb, hue=hue, saturation=saturation, mode=ColorMode.HS)

    async def set_ct(self, bulb: Bulb, mireds: int) -> None:
        await self._apply(bulb, mireds=mireds, mode=ColorMode.CT)

    # -- internals ----------------------------------------------------------

    async def _apply(self, bulb: Bulb, **changes) -> None:
        # Jitter the acknowledgement so the UI gets exercised against
        # out-of-order and late replies, which a real mesh will produce.
        await asyncio.sleep(self._latency * random.uniform(0.5, 1.5))
        current = self._bulbs.get(bulb.key)
        if current is None:
            return
        self._bulbs[bulb.key] = current.with_changes(**changes)
        self._emit("simulator — no radio attached")

    def _emit(self, detail: str) -> None:
        self._publish(list(self._bulbs.values()), True, detail)
