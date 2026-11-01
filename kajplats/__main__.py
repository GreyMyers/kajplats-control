"""Entry point.

    kajplats                       # offline simulator, no hardware needed
    kajplats --matter              # talk to matterjs-server on localhost
    kajplats --matter --url ws://pi.local:5580/ws
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from .backend import MockBackend
from .controller import Controller
from .matter import DEFAULT_URL, MatterBackend
from .theme import STYLESHEET
from .window import MainWindow


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="kajplats", description="Colour control for IKEA KAJPLATS bulbs."
    )
    parser.add_argument(
        "--matter",
        action="store_true",
        help="drive real bulbs through matterjs-server instead of the simulator",
    )
    parser.add_argument(
        "--url",
        default=DEFAULT_URL,
        help=f"matterjs-server WebSocket URL (default: {DEFAULT_URL})",
    )
    parser.add_argument(
        "--bulbs",
        type=int,
        default=2,
        help="how many bulbs the simulator should pretend to have (default: 2)",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    if args.matter:
        backend = MatterBackend(args.url)
        label = f"matter · {args.url}"
    else:
        backend = MockBackend(count=args.bulbs)
        label = "simulator"

    app = QApplication(sys.argv[:1])
    app.setApplicationName("KAJPLATS")
    app.setStyleSheet(STYLESHEET)

    controller = Controller(backend)
    window = MainWindow(controller, label)
    window.show()
    controller.start()

    # Let Ctrl-C in the launching terminal close the window. Qt blocks in its
    # own event loop, so a periodic no-op timer is needed for Python to run
    # the signal handler at all.
    signal.signal(signal.SIGINT, lambda *_: app.quit())
    keepalive = QTimer()
    keepalive.timeout.connect(lambda: None)
    keepalive.start(200)

    exit_code = app.exec()
    controller.shutdown()
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
