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
