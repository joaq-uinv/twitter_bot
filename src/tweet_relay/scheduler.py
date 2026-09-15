"""Poll loop. Jittered so restarts do not synchronise onto one mirror."""
from __future__ import annotations

import logging
import random
import signal
import threading

log = logging.getLogger(__name__)


class Stopper:
    def __init__(self):
        self.event = threading.Event()

    def install(self) -> None:
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                signal.signal(sig, self._handle)
            except ValueError:
                pass   # not on the main thread (tests)

    def _handle(self, signum, _frame) -> None:
        log.info("received signal %s, shutting down after this check", signum)
        self.event.set()

    @property
    def stopped(self) -> bool:
        return self.event.is_set()

    def wait(self, seconds: float) -> None:
        self.event.wait(seconds)


def next_delay(interval: int, jitter_fraction: float = 0.1,
               rng: random.Random | None = None) -> float:
    """Interval ± jitter, never below 1s."""
    r = rng or random
    spread = interval * jitter_fraction
    return max(1.0, interval + r.uniform(-spread, spread))


def run_forever(pipeline, interval: int, stopper: Stopper | None = None,
                max_cycles: int | None = None) -> int:
    stopper = stopper or Stopper()
    stopper.install()
    cycles = 0
    while not stopper.stopped:
        try:
            pipeline.run_once()
        except Exception:
            # A check must never kill the loop; the next one may well succeed.
            log.exception("check raised unexpectedly; continuing")
        cycles += 1
        if max_cycles is not None and cycles >= max_cycles:
            break
        if stopper.stopped:
            break
        stopper.wait(next_delay(interval))
    log.info("stopped after %d checks", cycles)
    return cycles
