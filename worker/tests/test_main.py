import threading

from app.main import run


def test_run_exits_when_stop_is_set() -> None:
    stop = threading.Event()
    stop.set()
    run(stop, interval_seconds=0.01)
