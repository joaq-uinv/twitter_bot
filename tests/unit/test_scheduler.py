import random
from tweet_relay.scheduler import Stopper, next_delay, run_forever
from tests.doubles import FakeSource, RecordingSink


def test_jitter_stays_within_bounds():
    rng = random.Random(0)
    for _ in range(200):
        d = next_delay(900, 0.1, rng)
        assert 810 <= d <= 990


def test_jitter_is_not_constant():
    rng = random.Random(1)
    assert len({next_delay(900, 0.1, rng) for _ in range(20)}) > 1


def test_never_returns_a_busy_loop_delay():
    assert next_delay(1, 0.9, random.Random(2)) >= 1.0


class Boom:
    def run_once(self):
        raise RuntimeError("check exploded")


def test_a_failing_check_does_not_kill_the_loop():
    """§7: the relay must survive a bad check and try again."""
    assert run_forever(Boom(), interval=0, max_cycles=3) == 3


def test_stop_event_ends_the_loop():
    s = Stopper(); s.event.set()
    assert run_forever(Boom(), interval=0, stopper=s) == 0
