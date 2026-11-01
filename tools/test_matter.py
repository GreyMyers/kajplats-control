"""Protocol test for the Matter backend against a stub matterjs-server.

This is the half that cannot be checked by eye: it asserts the backend reads
a node payload into bulbs correctly and emits exactly the cluster commands
the Matter spec expects, so the first contact with a real bulb is not also
the first test of the wire format.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

import websockets

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kajplats.matter import MatterBackend  # noqa: E402
from kajplats.model import ColorMode  # noqa: E402

# One colour+white KAJPLATS on endpoint 1, shaped like a real get_nodes reply.
NODE = {
    "node_id": 4,
    "available": True,
    "attributes": {
        "0/40/1": "IKEA of Sweden",
        "0/40/3": "KAJPLATS_CWS",
        "0/40/5": "Hallway",
        "1/6/0": True,
        "1/8/0": 180,
        "1/768/0": 85,          # CurrentHue
        "1/768/1": 200,         # CurrentSaturation
        "1/768/7": 320,         # ColorTemperatureMireds
        "1/768/8": 0,           # ColorMode = hue/saturation
        "1/768/16395": 153,     # CT physical min
        "1/768/16396": 454,     # CT physical max
        "1/768/16410": 0b11001, # ColorCapabilities: HS + CT
    },
}

received: list[dict] = []


async def server(connection) -> None:
    await connection.send(
        json.dumps(
            {
                "fabric_id": 1,
                "schema_version": 14,
                "sdk_version": "stub/1.0",
                "bluetooth_enabled": True,
                "thread_credentials_set": False,
            }
        )
    )
    async for raw in connection:
        message = json.loads(raw)
        received.append(message)
        command = message["command"]
        if command == "get_nodes":
            result = [NODE]
        elif command == "commission_with_code":
            result = {"node_id": 9}
        else:
            result = {}
        await connection.send(
            json.dumps({"message_id": message["message_id"], "result": result})
        )


def check(condition: bool, label: str) -> None:
    if not condition:
        raise AssertionError(label)
    print(f"  ok  {label}")


async def main() -> None:
    async with websockets.serve(server, "127.0.0.1", 0) as running:
        port = running.sockets[0].getsockname()[1]
        backend = MatterBackend(f"ws://127.0.0.1:{port}/ws")

        published: list[tuple] = []
        backend.on_state(lambda bulbs, ok, detail: published.append((bulbs, ok, detail)))

        await backend.start()

        print("node parsing")
        bulbs, connected, _ = published[-1]
        check(connected, "reports connected")
        check(len(bulbs) == 1, "found exactly one light endpoint (endpoint 0 skipped)")
        bulb = bulbs[0]
        check(bulb.node_id == 4 and bulb.endpoint_id == 1, "addressed node 4 endpoint 1")
        check(bulb.name == "Hallway", "prefers NodeLabel over ProductName")
        check(bulb.on is True and bulb.level == 180, "read on/off and level")
        check(bulb.hue == 85 and bulb.saturation == 200, "read hue and saturation")
        check(bulb.mireds == 320, "read colour temperature")
        check(bulb.mode is ColorMode.HS, "ColorMode 0 maps to hue/saturation")
        check(bulb.ct_min == 153 and bulb.ct_max == 454, "read physical CT range")
        check(bulb.supports_color and bulb.supports_ct, "decoded ColorCapabilities")
        check(backend.can_commission, "offers commissioning when BLE is enabled")

        print("outbound commands")
        received.clear()
        await backend.set_power(bulb, True)
        args = received[-1]["args"]
        check(args["cluster_id"] == 0x0006 and args["command_name"] == "on", "on/off")

        await backend.set_level(bulb, 42)
        args = received[-1]["args"]
        check(
            args["cluster_id"] == 0x0008
            and args["command_name"] == "moveToLevelWithOnOff"
            and args["payload"]["level"] == 42,
            "level uses moveToLevelWithOnOff",
        )

        await backend.set_hs(bulb, 100, 254)
        args = received[-1]["args"]
        check(
            args["cluster_id"] == 0x0300
            and args["command_name"] == "moveToHueAndSaturation"
            and args["payload"]["hue"] == 100
            and args["payload"]["saturation"] == 254,
            "hue/saturation command and payload",
        )

        await backend.set_ct(bulb, 370)
        args = received[-1]["args"]
        check(
            args["command_name"] == "moveToColorTemperature"
            and args["payload"]["colorTemperatureMireds"] == 370,
            "colour temperature command and payload",
        )
        check(
            all(
                "transitionTime" in message["args"]["payload"]
                for message in received
                if message["args"].get("payload")
            ),
            "every movement command carries a transition time",
        )

        print("pushed attribute events")
        backend._dispatch(
            {"event": "attribute_updated", "data": [4, "1/6/0", False]}
        )
        check(published[-1][0][0].on is False, "external on/off change is reflected")
        backend._dispatch(
            {"event": "attribute_updated", "data": [4, "1/768/8", 2]}
        )
        check(
            published[-1][0][0].mode is ColorMode.CT,
            "ColorMode 2 switches the UI to white mode",
        )
        backend._dispatch({"event": "attribute_updated", "data": [4, "nonsense", 1]})
        check(True, "malformed attribute path is ignored rather than fatal")

        print("errors")
        await backend.stop()
        try:
            await backend.set_power(bulb, True)
        except Exception as exc:
            check("not connected" in str(exc), "commands fail cleanly when closed")
        else:
            raise AssertionError("expected a failure after stop()")

    print("\nMATTER PROTOCOL OK")


asyncio.run(main())
