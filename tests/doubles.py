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

    def __init__(self, fail_on: set[int] | None = None, private: bool = True):
        self.sent: list[str] = []
        self.previews: list[str | None] = []   # spec 003: the card URL of each sent message
        self.fail_on = fail_on or set()      # 1-based send ordinals that must fail
        self.attempts = 0
        self.private = private
        self.chat_checks = 0

    def send(self, message: str, *, preview_url: str | None = None) -> None:
        self.attempts += 1
        if self.attempts in self.fail_on:
            raise DeliveryFailed(f"simulated failure on send #{self.attempts}")
        self.sent.append(message)
        self.previews.append(preview_url)

    def chat_is_private(self) -> bool:
        self.chat_checks += 1
        return self.private


class ScriptedInbox:
    """Spec 003 contract command-inbox. Returns `batches` in turn (then empty ones), or
    raises `error`. Records the offsets it was asked for."""

    def __init__(self, *batches, error: Exception | None = None):
        self.batches = list(batches)
        self.error = error
        self.offsets: list[int] = []

    def read(self, offset: int):
        from tweet_relay.commands import InboxBatch
        self.offsets.append(offset)
        if self.error:
            raise self.error
        if self.batches:
            return self.batches.pop(0)
        return InboxBatch(messages=[], next_offset=offset)


OPERATOR = 111222333


def msg(update_id: int, text: str, chat_id: int = OPERATOR, chat_type: str = "private"):
    from tweet_relay.commands import IncomingMessage
    return IncomingMessage(update_id=update_id, chat_id=chat_id, chat_type=chat_type, text=text)


def batch(*messages, next_offset: int | None = None):
    from tweet_relay.commands import InboxBatch
    last = max((m.update_id for m in messages), default=0)
    return InboxBatch(messages=list(messages), next_offset=next_offset or last + 1)


# ---------- spec 002 mirror-health doubles ----------

class FixtureMirrorProbe:
    """Maps host -> ProbeOutcome; records the probe order (DD-12: sequential)."""
    def __init__(self, outcomes):
        self.outcomes = outcomes
        self.calls: list[str] = []

    def probe(self, host, handle):
        self.calls.append(host)
        return self.outcomes[host]

    def close(self):
        pass


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
