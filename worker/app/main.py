"""Minimal worker entrypoint: load config, log, idle until stopped.

The SQS polling loop lands in spec task 10.
"""

import signal
import threading
from types import FrameType

from lusiform_common import BaseAppSettings, configure_logging, get_logger


def run(stop: threading.Event, interval_seconds: float = 5.0) -> None:
    settings = BaseAppSettings()
    configure_logging(settings.service_name, settings.log_level)
    log = get_logger("worker")
    log.info("worker started", environment=settings.environment)
    while not stop.wait(interval_seconds):
        log.debug("worker idle")
    log.info("worker stopped")


def main() -> None:
    stop = threading.Event()

    def _handle(_signum: int, _frame: FrameType | None) -> None:
        stop.set()

    signal.signal(signal.SIGTERM, _handle)
    signal.signal(signal.SIGINT, _handle)
    run(stop)


if __name__ == "__main__":
    main()
