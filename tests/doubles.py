"""Test doubles. RecordingSink can fail on demand, for partial-failure cases (E-5)."""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from tweet_relay.models import DeliveryFailed, SourceUnavailable, Tweet, TweetKind

BASE = datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc)


def tweet(id: int, kind=TweetKind.ORIGINAL, minutes: int = 0, author="santtiagom_"):
    return Tweet(id=id, author=author, text=f"post {id}",
                 published_at=BASE + timedelta(minutes=minutes), kind=kind)


class FakeSource:
    name = "fake"

    def __init__(self, tweets=None, error: str | None = None):
        self.tweets = tweets or []
        self.error = error
        self.calls = 0

    def fetch(self, handle):
        self.calls += 1
        if self.error:
            raise SourceUnavailable(self.error)
        return list(self.tweets)


class RecordingSink:
    name = "recording"

    def __init__(self, fail_on: set[int] | None = None):
        self.sent: list[str] = []
        self.fail_on = fail_on or set()      # 1-based send ordinals that must fail
        self.attempts = 0

    def send(self, message: str) -> None:
        self.attempts += 1
        if self.attempts in self.fail_on:
            raise DeliveryFailed(f"simulated failure on send #{self.attempts}")
        self.sent.append(message)


# ---------- spec 002 mirror-health doubles ----------

class FixtureMirrorProbe:
    """Maps host -> ProbeOutcome; records the probe order (DD-12: sequential)."""
    def __init__(self, outcomes):
        self.outcomes = outcomes
        self.calls: list[str] = []

    def probe(self, host, handle):
        self.calls.append(host)
        return self.outcomes[host]


class StaticDirectory:
    def __init__(self, read=None, error=None):
        self.read, self.error = read, error

    def list(self):
        if self.error:
            raise self.error
        return self.read


class MemoryHistoryStore:
    def __init__(self, history=None):
        from tweet_relay.mirrors.history import EMPTY_LATEST, History
        self.history = history or History(results=[], latest=EMPTY_LATEST)
        self.saved = None

    def load(self):
        return self.history

    def save(self, history, now):
        self.saved = history
        self.history = history


class FakeTracker:
    def __init__(self, open_now=None, fail=False):
        self.open_now = dict(open_now or {})
        self.fail = fail
        self.calls: list[tuple] = []

    def _check(self):
        if self.fail:
            from tweet_relay.mirrors.tracker import TrackerUnavailable
            raise TrackerUnavailable("simulated")

    def open_warnings(self):
        self._check()
        return dict(self.open_now)

    def open(self, host, since, reason):
        self._check()
        self.calls.append(("open", host, since, reason))
        self.open_now[host] = since

    def update(self, host, reason):
        self._check()
        self.calls.append(("update", host, reason))

    def close(self, host):
        self._check()
        self.calls.append(("close", host))
        self.open_now.pop(host, None)
