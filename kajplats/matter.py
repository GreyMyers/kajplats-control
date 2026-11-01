"""Matter backend: a WebSocket client for matterjs-server.

matterjs-server (the successor to python-matter-server, which was archived in
June 2026) exposes an RPC-style JSON protocol on ws://host:5580/ws. Every
request carries a `message_id` that its reply echoes back; the server also
pushes unsolicited `event` messages when a device's attributes change, which
is how we learn about changes made from a phone app or a wall switch.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from itertools import count
from typing import Any

import websockets

from .model import (
    ATTR_COLOR_CAPABILITIES,
    ATTR_COLOR_MODE,
    ATTR_COLOR_TEMP_MIREDS,
    ATTR_CT_PHYS_MAX,
    ATTR_CT_PHYS_MIN,
    ATTR_CURRENT_HUE,
    ATTR_CURRENT_LEVEL,
    ATTR_CURRENT_SATURATION,
    ATTR_NODE_LABEL,
    ATTR_ON_OFF,
    ATTR_PRODUCT_NAME,
    ATTR_VENDOR_NAME,
    CLUSTER_BASIC_INFO,
    CLUSTER_COLOR,
    CLUSTER_LEVEL,
    CLUSTER_ON_OFF,
    Bulb,
    ColorMode,
)

LOGGER = logging.getLogger(__name__)

DEFAULT_URL = "ws://localhost:5580/ws"

#: Transitions are expressed in tenths of a second. Two ticks reads as
#: instant to the eye but still lets the bulb interpolate instead of stepping.
TRANSITION_TICKS = 2

#: Most commands answer immediately.
DEFAULT_TIMEOUT = 30.0

#: Commissioning does not: BLE handshake, Thread credential push, mesh join,
#: then a full attribute read. Three minutes is the realistic ceiling, and
#: giving up early strands a device that is halfway onto the fabric.
COMMISSION_TIMEOUT = 300.0

#: ColorCapabilities bitmap (cluster 0x0300, attribute 0x401A).
CAP_HUE_SAT = 1 << 0
CAP_COLOR_TEMP = 1 << 4


class MatterError(RuntimeError):
    """A command was rejected by the server or the device."""


class MatterBackend:
    """Drives real bulbs over a matterjs-server fabric."""

    def __init__(self, url: str = DEFAULT_URL) -> None:
        self._url = url
        self._ws: Any = None
        self._reader: asyncio.Task | None = None
        self._pending: dict[str, asyncio.Future] = {}
        self._ids = count(1)
        self._bulbs: dict[str, Bulb] = {}
        self._server_info: dict[str, Any] = {}
        self._listener = None

    # Backend protocol surface -------------------------------------------

    def on_state(self, listener) -> None:
        self._listener = listener

    def _publish(self, connected: bool, detail: str = "") -> None:
        if self._listener is not None:
            self._listener(list(self._bulbs.values()), connected, detail)

    @property
    def can_commission(self) -> bool:
        return bool(self._server_info.get("bluetooth_enabled"))

    @property
    def server_info(self) -> dict[str, Any]:
        return dict(self._server_info)

    # -- lifecycle ---------------------------------------------------------

    async def start(self) -> None:
        self._ws = await websockets.connect(
            self._url,
            max_size=32 * 1024 * 1024,
            # Commissioning goes quiet for minutes; the defaults are tight
            # enough to tear the connection down mid-pairing.
            ping_interval=30,
            ping_timeout=60,
        )
        # The server greets us with server_info before we send anything.
        greeting = json.loads(await self._ws.recv())
        self._server_info = greeting
        LOGGER.info("connected to %s", greeting.get("sdk_version", "matter-server"))
        self._reader = asyncio.create_task(self._read_loop())
        await self.refresh()

    async def stop(self) -> None:
        if self._reader is not None:
            self._reader.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._reader
            self._reader = None
        if self._ws is not None:
            await self._ws.close()
            self._ws = None

    async def refresh(self) -> None:
        nodes = await self._send("get_nodes", {"only_available": False})
        bulbs: dict[str, Bulb] = {}
        for node in nodes or []:
            for bulb in self._bulbs_from_node(node):
                # Preserve any name the user has overridden locally.
                existing = self._bulbs.get(bulb.key)
                if existing is not None and existing.name != bulb.name:
                    bulb = bulb.with_changes(name=existing.name)
                bulbs[bulb.key] = bulb
        self._bulbs = bulbs
        detail = self._server_info.get("sdk_version", self._url)
        self._publish(True, detail)

    # -- commands ----------------------------------------------------------

    async def set_power(self, bulb: Bulb, on: bool) -> None:
        await self._device_command(bulb, CLUSTER_ON_OFF, "on" if on else "off", {})

    async def set_level(self, bulb: Bulb, level: int) -> None:
        await self._device_command(
            bulb,
            CLUSTER_LEVEL,
            # ...WithOnOff so that dragging up from zero also wakes the bulb.
            "moveToLevelWithOnOff",
            {
                "level": int(level),
                "transitionTime": TRANSITION_TICKS,
                "optionsMask": 0,
                "optionsOverride": 0,
            },
        )

    async def set_hs(self, bulb: Bulb, hue: int, saturation: int) -> None:
        await self._device_command(
            bulb,
            CLUSTER_COLOR,
            "moveToHueAndSaturation",
            {
                "hue": int(hue),
                "saturation": int(saturation),
                "transitionTime": TRANSITION_TICKS,
                "optionsMask": 0,
                "optionsOverride": 0,
            },
        )

    async def set_ct(self, bulb: Bulb, mireds: int) -> None:
        await self._device_command(
            bulb,
            CLUSTER_COLOR,
            "moveToColorTemperature",
            {
                "colorTemperatureMireds": int(mireds),
                "transitionTime": TRANSITION_TICKS,
                "optionsMask": 0,
                "optionsOverride": 0,
            },
        )

    async def commission(self, code: str) -> str:
        """Add a bulb to the fabric from its QR payload or 11-digit pin."""
        node = await self._send(
            "commission_with_code",
            {"code": code.strip(), "network_only": False},
            timeout=COMMISSION_TIMEOUT,
        )
        await self.refresh()
        node_id = (node or {}).get("node_id", "?")
        return f"Commissioned node {node_id}"

    async def set_thread_dataset(self, dataset_hex: str, name: str | None = None) -> None:
        """Store the Thread network that commissioned devices should join.

        Passing an `id` registers a *named additional* credential and leaves
        the primary dataset unset, so commissioning then has no network to put
        the device on. Omitting it sets the primary, which is what we want
        unless the caller explicitly asks for a named one.
        """
        args: dict[str, Any] = {"dataset": dataset_hex.strip()}
        if name:
            args["id"] = name
        await self._send("set_thread_dataset", args)
        self._server_info["thread_credentials_set"] = True

    # -- RPC plumbing ------------------------------------------------------

    async def _device_command(
        self, bulb: Bulb, cluster_id: int, command_name: str, payload: dict
    ) -> Any:
        return await self._send(
            "device_command",
            {
                "node_id": bulb.node_id,
                "endpoint_id": bulb.endpoint_id,
                "cluster_id": cluster_id,
                "command_name": command_name,
                "payload": payload,
            },
        )

    async def _send(
        self, command: str, args: dict | None = None, timeout: float = DEFAULT_TIMEOUT
    ) -> Any:
        if self._ws is None:
            raise MatterError("not connected to a Matter server")
        message_id = str(next(self._ids))
        future: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[message_id] = future
        await self._ws.send(
            json.dumps(
                {"message_id": message_id, "command": command, "args": args or {}}
            )
        )
        try:
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError as exc:
            raise MatterError(f"{command} timed out after {timeout:g}s") from exc
        finally:
            self._pending.pop(message_id, None)

    async def _read_loop(self) -> None:
        try:
            async for raw in self._ws:
                try:
                    self._dispatch(json.loads(raw))
                except Exception:  # a malformed frame must not kill the loop
                    LOGGER.exception("failed to handle server message")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            LOGGER.warning("connection lost: %s", exc)
            self._publish(False, f"disconnected: {exc}")

    def _dispatch(self, message: dict) -> None:
        message_id = message.get("message_id")
        if message_id is not None:
            future = self._pending.get(message_id)
            if future is None or future.done():
                return
            if "error_code" in message:
                future.set_exception(
                    MatterError(message.get("details") or f"error {message['error_code']}")
                )
            else:
                future.set_result(message.get("result"))
            return

        event = message.get("event")
        if event == "attribute_updated":
            self._on_attribute_event(message.get("data"))
        elif event in ("node_updated", "node_added"):
            self._on_node_event(message.get("data"))
        elif event == "node_removed":
            self._on_node_removed(message.get("data"))

    def _on_attribute_event(self, data: Any) -> None:
        # Pushed as [node_id, "endpoint/cluster/attribute", value].
        if not isinstance(data, (list, tuple)) or len(data) != 3:
            return
        node_id, path, value = data
        parsed = _parse_path(path)
        if parsed is None:
            return
        endpoint, cluster, attribute = parsed
        key = f"{node_id}:{endpoint}"
        bulb = self._bulbs.get(key)
        if bulb is None:
            return
        changes = _attribute_to_change(cluster, attribute, value)
        if changes:
            self._bulbs[key] = bulb.with_changes(**changes)
            self._publish(True)

    def _on_node_event(self, data: Any) -> None:
        if not isinstance(data, dict):
            return
        changed = False
        for bulb in self._bulbs_from_node(data):
            existing = self._bulbs.get(bulb.key)
            if existing is not None:
                bulb = bulb.with_changes(name=existing.name)
            self._bulbs[bulb.key] = bulb
            changed = True
        if changed:
            self._publish(True)

    def _on_node_removed(self, data: Any) -> None:
        node_id = data.get("node_id") if isinstance(data, dict) else data
        removed = [k for k in self._bulbs if k.startswith(f"{node_id}:")]
        for key in removed:
            self._bulbs.pop(key, None)
        if removed:
            self._publish(True)

    # -- node parsing ------------------------------------------------------

    def _bulbs_from_node(self, node: dict) -> list[Bulb]:
        """Pick out every dimmable/colour light endpoint on one node."""
        node_id = node.get("node_id")
        attributes = node.get("attributes") or {}
        if node_id is None or not attributes:
            return []

        # Index attributes as {endpoint: {(cluster, attribute): value}}.
        by_endpoint: dict[int, dict[tuple[int, int], Any]] = {}
        for path, value in attributes.items():
            parsed = _parse_path(path)
            if parsed is None:
                continue
            endpoint, cluster, attribute = parsed
            by_endpoint.setdefault(endpoint, {})[(cluster, attribute)] = value

        root = by_endpoint.get(0, {})
        label = root.get((CLUSTER_BASIC_INFO, ATTR_NODE_LABEL)) or ""
        product = root.get((CLUSTER_BASIC_INFO, ATTR_PRODUCT_NAME)) or ""
        vendor = root.get((CLUSTER_BASIC_INFO, ATTR_VENDOR_NAME)) or ""
        online = bool(node.get("available", True))

        bulbs: list[Bulb] = []
        for endpoint, attrs in sorted(by_endpoint.items()):
            if endpoint == 0 or (CLUSTER_ON_OFF, ATTR_ON_OFF) not in attrs:
                continue

            capabilities = attrs.get((CLUSTER_COLOR, ATTR_COLOR_CAPABILITIES))
            if capabilities is not None:
                supports_hs = bool(capabilities & CAP_HUE_SAT)
                supports_ct = bool(capabilities & CAP_COLOR_TEMP)
            else:
                # No capabilities attribute: infer from which attributes the
                # device actually exposes. A colour-temperature-only light
                # still has a ColorControl cluster, so the cluster's mere
                # presence says nothing about hue support - but it will not
                # publish CurrentHue unless it can actually do hue.
                supports_hs = (CLUSTER_COLOR, ATTR_CURRENT_HUE) in attrs
                supports_ct = (CLUSTER_COLOR, ATTR_COLOR_TEMP_MIREDS) in attrs

            mode_value = attrs.get((CLUSTER_COLOR, ATTR_COLOR_MODE))
            # ColorMode 0 = hue/sat, 1 = X/Y, 2 = colour temperature.
            mode = ColorMode.CT if mode_value in (2, None) else ColorMode.HS

            name = label or product or f"Light {node_id}"
            if len([e for e in by_endpoint if e != 0]) > 1:
                name = f"{name} · {endpoint}"

            bulbs.append(
                Bulb(
                    node_id=int(node_id),
                    endpoint_id=int(endpoint),
                    name=name,
                    online=online,
                    on=bool(attrs.get((CLUSTER_ON_OFF, ATTR_ON_OFF), False)),
                    level=int(attrs.get((CLUSTER_LEVEL, ATTR_CURRENT_LEVEL)) or 254),
                    hue=int(attrs.get((CLUSTER_COLOR, ATTR_CURRENT_HUE)) or 0),
                    saturation=int(
                        attrs.get((CLUSTER_COLOR, ATTR_CURRENT_SATURATION)) or 0
                    ),
                    mireds=int(
                        attrs.get((CLUSTER_COLOR, ATTR_COLOR_TEMP_MIREDS)) or 370
                    ),
                    mode=mode,
                    ct_min=int(attrs.get((CLUSTER_COLOR, ATTR_CT_PHYS_MIN)) or 153),
                    ct_max=int(attrs.get((CLUSTER_COLOR, ATTR_CT_PHYS_MAX)) or 454),
                    supports_color=supports_hs,
                    supports_ct=supports_ct,
                    vendor=str(vendor),
                    product=str(product),
                )
            )

        # A colour-temperature-only bulb still belongs in the UI, just
        # without the wheel, so endpoints are kept regardless of capabilities.
        return bulbs


def _parse_path(path: Any) -> tuple[int, int, int] | None:
    """Split an "endpoint/cluster/attribute" attribute path."""
    if not isinstance(path, str):
        return None
    parts = path.split("/")
    if len(parts) != 3:
        return None
    try:
        return int(parts[0]), int(parts[1]), int(parts[2])
    except ValueError:
        return None


def _attribute_to_change(cluster: int, attribute: int, value: Any) -> dict:
    """Map one pushed attribute update onto `Bulb` fields."""
    if cluster == CLUSTER_ON_OFF and attribute == ATTR_ON_OFF:
        return {"on": bool(value)}
    if cluster == CLUSTER_LEVEL and attribute == ATTR_CURRENT_LEVEL:
        return {"level": int(value)} if value is not None else {}
    if cluster == CLUSTER_COLOR:
        if attribute == ATTR_CURRENT_HUE and value is not None:
            return {"hue": int(value)}
        if attribute == ATTR_CURRENT_SATURATION and value is not None:
            return {"saturation": int(value)}
        if attribute == ATTR_COLOR_TEMP_MIREDS and value is not None:
            return {"mireds": int(value)}
        if attribute == ATTR_COLOR_MODE and value is not None:
            return {"mode": ColorMode.CT if value == 2 else ColorMode.HS}
    return {}
