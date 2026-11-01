"""Talk to the ESP32-C6 border router's OpenThread CLI over USB serial.

The ot_br firmware exposes the standard OpenThread CLI (plus Espressif's
`wifi` command) on the C6's USB-Serial-JTAG port. This sends commands and
collects the reply, which ends with "Done" or "Error ...".

    uv run python tools/ot_console.py "state" "dataset active -x"
    uv run python tools/ot_console.py --port /dev/ttyACM0 "ifconfig up"

Secrets note: anything passed here lands in your shell history. For the Wi-Fi
password use the --stdin form, which reads one command per line instead:

    printf 'wifi connect -s MySSID -p %s\\n' "$PASS" | \\
        uv run python tools/ot_console.py --stdin
"""

from __future__ import annotations

import argparse
import sys
import time

import serial


def read_until_idle(port: serial.Serial, quiet_for: float = 0.6,
                    overall: float = 20.0) -> str:
    """Collect output until the device stops talking for `quiet_for` seconds."""
    chunks: list[bytes] = []
    last = time.time()
    start = time.time()
    while time.time() - start < overall:
        data = port.read(4096)
        if data:
            chunks.append(data)
            last = time.time()
        elif time.time() - last > quiet_for and chunks:
            break
        elif not chunks and time.time() - start > 2.0:
            break
    return b"".join(chunks).decode(errors="replace")


def send(port: serial.Serial, command: str, *, echo: bool = True) -> str:
    port.reset_input_buffer()
    port.write((command + "\r\n").encode())
    port.flush()
    out = read_until_idle(port)
    if echo:
        # Strip the echoed command and the bare prompt for readability.
        lines = [
            line.rstrip()
            for line in out.splitlines()
            if line.strip() and line.strip() not in (command, ">")
        ]
        print(f"> {command}")
        for line in lines:
            print(f"  {line}")
        print()
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("commands", nargs="*", help="CLI commands to run in order")
    parser.add_argument("--port", default="/dev/ttyACM0")
    parser.add_argument(
        "--stdin",
        action="store_true",
        help="read commands from stdin, one per line (keeps secrets out of argv)",
    )
    parser.add_argument("--quiet", action="store_true", help="suppress echo")
    args = parser.parse_args()

    commands = list(args.commands)
    if args.stdin:
        commands += [line.strip() for line in sys.stdin if line.strip()]
    if not commands:
        commands = ["state"]

    with serial.Serial(args.port, 115200, timeout=0.3) as port:
        time.sleep(0.3)
        port.reset_input_buffer()
        # A bare newline flushes any partial line and gets us a prompt.
        port.write(b"\r\n")
        port.flush()
        read_until_idle(port, quiet_for=0.4, overall=3.0)

        for command in commands:
            send(port, command, echo=not args.quiet)
    return 0


if __name__ == "__main__":
    sys.exit(main())
