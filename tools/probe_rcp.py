"""Ask the ESP32-C6 RCP who it is, over Spinel/HDLC.

otbr-agent is a large AUR build, so it is worth confirming the radio actually
answers before going near it. This speaks just enough of the protocol to ask
for the NCP version string and the radio capabilities, which together prove
the firmware is alive and is a 15.4 radio co-processor.

    uv run python tools/probe_rcp.py [/dev/ttyACM0]
"""

from __future__ import annotations

import subprocess
import sys

import serial

PORT = sys.argv[1] if len(sys.argv) > 1 else "/dev/ttyACM0"

# HDLC-lite framing (RFC 1662 style) as OpenThread uses it.
FLAG = 0x7E
ESCAPE = 0x7D
ESCAPE_MASK = 0x20
MUST_ESCAPE = {0x7E, 0x7D, 0x11, 0x13, 0xF8}

# Spinel basics. The transaction id in the low nibble of the header must be
# non-zero for a command that expects a reply: tid 0 marks a message as
# unsolicited, and the NCP simply will not answer a GET sent that way.
HEADER = 0x81       # flag bits 10, interface 0, tid 1
HEADER_NO_REPLY = 0x80
CMD_RESET = 1
CMD_PROP_VALUE_GET = 2
CMD_PROP_VALUE_IS = 6
PROP_LAST_STATUS = 0
PROP_PROTOCOL_VERSION = 1
PROP_NCP_VERSION = 2
PROP_CAPS = 5
CAP_CONFIG_RADIO = 34


def fcs16(data: bytes) -> int:
    """CRC-16/X.25 — the frame check sequence HDLC-lite appends."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0x8408 if crc & 1 else crc >> 1
    return crc ^ 0xFFFF


def encode(payload: bytes) -> bytes:
    """Wrap a Spinel frame in HDLC: escape, append FCS, delimit."""
    body = payload + fcs16(payload).to_bytes(2, "little")
    out = bytearray([FLAG])
    for byte in body:
        if byte in MUST_ESCAPE:
            out += bytes([ESCAPE, byte ^ ESCAPE_MASK])
        else:
            out.append(byte)
    out.append(FLAG)
    return bytes(out)


def decode(stream: bytearray) -> list[bytes]:
    """Pull every complete, FCS-valid frame out of the buffer, in place."""
    frames: list[bytes] = []
    while True:
        try:
            start = stream.index(FLAG)
        except ValueError:
            stream.clear()
            return frames
        try:
            end = stream.index(FLAG, start + 1)
        except ValueError:
            del stream[:start]  # keep the partial frame for the next read
            return frames

        raw = bytes(stream[start + 1 : end])
        # Consume up to but not including the closing flag: back-to-back
        # frames share it, so it doubles as the next frame's opening flag.
        del stream[:end]
        if not raw:
            continue

        unescaped = bytearray()
        escaping = False
        for byte in raw:
            if escaping:
                unescaped.append(byte ^ ESCAPE_MASK)
                escaping = False
            elif byte == ESCAPE:
                escaping = True
            else:
                unescaped.append(byte)

        if len(unescaped) < 3:
            continue
        body, received_fcs = bytes(unescaped[:-2]), int.from_bytes(unescaped[-2:], "little")
        if fcs16(body) == received_fcs:
            frames.append(body)


def read_uint(data: bytes, offset: int = 0) -> tuple[int, int]:
    """Spinel packed unsigned integer: 7 bits per byte, little-endian."""
    value = shift = 0
    while offset < len(data):
        byte = data[offset]
        offset += 1
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            break
        shift += 7
    return value, offset


def request(port: serial.Serial, prop: int) -> bytes | None:
    port.reset_input_buffer()
    port.write(encode(bytes([HEADER, CMD_PROP_VALUE_GET, prop])))
    port.flush()

    buffer = bytearray()
    for _ in range(40):
        chunk = port.read(512)
        if chunk:
            buffer += chunk
            for frame in decode(buffer):
                if len(frame) < 2 or frame[1] != CMD_PROP_VALUE_IS:
                    continue
                got, offset = read_uint(frame, 2)
                if got == prop:
                    return frame[offset:]
    return None


def _otbr_running() -> bool:
    try:
        result = subprocess.run(
            ["systemctl", "is-active", "--quiet", "otbr-agent"],
            timeout=5,
        )
        return result.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def main() -> int:
    # otbr-agent holds the RCP's serial port exclusively. Opening it from here
    # steals the port, the agent dies, and systemd restarts it - which tears
    # down the Thread mesh for a few seconds. Refuse rather than do that by
    # accident.
    if _otbr_running():
        print("otbr-agent is running and owns this port.")
        print("Stop it first if you really need to probe:")
        print("    sudo systemctl stop otbr-agent")
        print("Probing now would kill the Thread mesh for a few seconds.")
        return 2

    print(f"probing {PORT}\n")
    with serial.Serial(PORT, 460800, timeout=0.25) as port:
        # A reset puts the RCP in a known state; the firmware announces itself
        # with a LAST_STATUS frame afterwards.
        port.write(encode(bytes([HEADER_NO_REPLY, CMD_RESET])))
        port.flush()
        port.read(512)

        version = request(port, PROP_NCP_VERSION)
        if version is None:
            print("  no reply — the RCP is not answering Spinel on this port.")
            print("  Check that the ot_rcp build had CONFIG_OPENTHREAD_RCP_USB_SERIAL_JTAG=y.")
            return 1
        text = version.rstrip(b"\x00").decode(errors="replace")
        print(f"  NCP version      : {text}")

        protocol = request(port, PROP_PROTOCOL_VERSION)
        if protocol:
            major, offset = read_uint(protocol)
            minor, _ = read_uint(protocol, offset)
            print(f"  Spinel protocol  : {major}.{minor}")

        caps = request(port, PROP_CAPS)
        if caps:
            values, offset = [], 0
            while offset < len(caps):
                capability, offset = read_uint(caps, offset)
                values.append(capability)
            # Capability 34 is SPINEL_CAP_CONFIG_RADIO: the device is a
            # radio co-processor rather than a full Thread stack.
            print(f"  capabilities     : {len(values)} advertised")
            is_rcp = CAP_CONFIG_RADIO in values
            print(f"  RCP mode         : {'yes' if is_rcp else 'NO - wrong firmware'}")

    print("\nRCP OK — ready for otbr-agent.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
